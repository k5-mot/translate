"""新しいTaskの決定的な契約を検証する。"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import pytest
from PIL import Image as PILImage

from translate.models.artifacts import ReviewResult
from translate.models.document import Block, Document, Image, Page, TextSpan, TextUnit
from translate.models.review import ReviewTarget, Revision, TextEdit
from translate.tasks.converter.unpack import _validate_entries
from translate.tasks.preprocess.load import load_document
from translate.tasks.preprocess.structure import (
    MAX_VISION_PIXELS,
    _bound_image,
    _schema,
)
from translate.tasks.publisher.lint import lint
from translate.tasks.publisher.markdown import convert_block
from translate.tasks.review.align import align
from translate.tasks.review.check import check, targets_from_document
from translate.tasks.review.fix import apply_revisions
from translate.tasks.review.review import _chunks as review_chunks

if TYPE_CHECKING:
    from pathlib import Path


def _unit(identifier: str, source: str, translated: str | None = None) -> TextUnit:
    """Test用の一Span TextUnitを作る。"""

    return TextUnit(
        id=identifier,
        spans=[
            TextSpan(
                id=f"{identifier}/span-0001",
                source=source,
                translated=translated,
            )
        ],
    )


def test_check_only_reports_empty_and_extreme_lengths() -> None:
    """CHECKが仕様で限定した三分類だけを返すことを確認する。"""

    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block",
                        order=0,
                        kind="paragraph",
                        content=_unit("unit", "a" * 80, ""),
                    )
                ],
            )
        ]
    )

    result = check(targets_from_document(document))

    assert [finding.category for finding in result.findings] == ["empty_translation"]


def test_fix_rejects_conflict_without_rolling_back_first_revision() -> None:
    """同一Spanへの後続候補だけを拒否し、先行修正を維持する。"""

    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block",
                        order=0,
                        kind="paragraph",
                        content=_unit("unit", "source", "初訳"),
                    )
                ],
            )
        ]
    )
    review = ReviewResult(
        findings=[],
        revisions=[
            Revision(
                id="first",
                target_id="unit",
                edits=[TextEdit(span_id="unit/span-0001", text="修正版")],
            ),
            Revision(
                id="second",
                target_id="unit",
                edits=[TextEdit(span_id="unit/span-0001", text="競合")],
            ),
        ],
    )

    result = apply_revisions(document, review)

    span = result.document.pages[0].blocks[0].content.spans[0]  # type: ignore[union-attr]
    assert span.revised == "修正版"
    assert [outcome.reason_code for outcome in result.outcomes] == [
        "applied",
        "conflicting_edit",
    ]


def test_align_uses_unique_figure_anchor_and_leaves_role_mismatch_unmatched() -> None:
    """図番号anchorは対応させ、role列が異なる区間は未対応に残す。"""

    source = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="s1",
                        order=0,
                        kind="paragraph",
                        content=_unit("su1", "before"),
                    ),
                    Block(
                        id="s2",
                        order=1,
                        kind="paragraph",
                        content=_unit("su2", "Figure 3"),
                    ),
                ],
            )
        ]
    )
    translation = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(id="t1", order=0, kind="heading", content=_unit("tu1", "前")),
                    Block(
                        id="t2", order=1, kind="paragraph", content=_unit("tu2", "図3")
                    ),
                ],
            )
        ]
    )

    result = align(source, translation)

    matched = [group for group in result.groups if group.kind == "matched"]
    assert len(matched) == 1
    assert matched[0].method == "unique_anchor"
    assert {group.kind for group in result.groups} >= {
        "source_only",
        "translation_only",
    }


def test_lint_checks_asset_existence_without_translation_quality(
    tmp_path: Path,
) -> None:
    """LINTが欠落assetを検出し、空訳自体は診断しないことを確認する。"""

    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="figure",
                        order=0,
                        kind="figure",
                        image=Image(id="image", asset_path="assets/missing.png"),
                    )
                ],
            )
        ]
    )

    result = lint(document, tmp_path)

    assert not result.valid
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["missing_asset"]


def test_markdown_alert_uses_bundled_word_style_name() -> None:
    """Alertをtemplate内の色付きWord styleへ一意に対応させる。"""

    block = Block(
        id="note",
        order=0,
        kind="alert",
        alert_kind="note",
        content=_unit("note/content", "Reference details."),
    )

    value = convert_block(block, 30.0)

    assert value == (
        '::: {custom-style="Note / 注記"}\n**NOTE:** Reference details\\.\n:::'
    )


def test_load_converts_minimal_docling_document() -> None:
    """LOADがDocling bodyを共通Documentと安定Spanへ変換する。"""

    value = {
        "schema_name": "DoclingDocument",
        "name": "sample",
        "pages": {"1": {"size": {"width": 100, "height": 200}}},
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Hello",
                "prov": [{"page_no": 1}],
            }
        ],
        "tables": [],
        "pictures": [],
        "key_value_items": [],
        "form_items": [],
        "groups": [],
        "body": {"children": [{"$ref": "#/texts/0"}]},
    }

    document = load_document(value)

    unit = document.pages[0].blocks[0].content
    assert unit is not None
    assert unit.id == "#/texts/0/content"
    assert unit.spans[0].source == "Hello"


def test_unpack_rejects_parent_path_before_extracting(tmp_path: Path) -> None:
    """UNPACKの前提となるZIP検査が親directory参照を拒否する。"""

    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.json", "{}")
    with (
        zipfile.ZipFile(archive_path) as archive,
        pytest.raises(ValueError, match="unsafe ZIP entry"),
    ):
        _validate_entries(archive.infolist(), tmp_path / "output")


def test_structure_bounds_page_image_for_local_vlm(tmp_path: Path) -> None:
    """STRUCTURE画像が縦横比を保ち、実測画素上限内へ縮小される。"""

    path = tmp_path / "page.png"
    PILImage.new("RGB", (2000, 1000), "white").save(path)

    _bound_image(path)

    with PILImage.open(path) as image:
        assert image.width * image.height <= MAX_VISION_PIXELS
        assert image.width / image.height == pytest.approx(2.0, rel=0.01)


def test_structure_native_schema_constrains_enum_values() -> None:
    """native structured outputがPydanticと同じBlock列挙値だけを許可する。"""

    schema = _schema(1)
    patches = schema["properties"]["patches"]  # type: ignore[index]
    properties = patches["items"]["properties"]  # type: ignore[index]

    assert "quote" not in properties["kind"]["enum"]
    assert "blockquote" in properties["kind"]["enum"]


def test_review_chunks_measure_compact_payload_without_duplicate_text() -> None:
    """REVIEWの上限計算が同じ原文と訳文を重複して数えないことを確認する。"""

    target = ReviewTarget(
        id="target",
        source="a" * 1500,
        translation="訳" * 500,
        target_ids=["unit"],
        spans=[
            TextSpan(
                id="span",
                source="a" * 1500,
                translated="訳" * 500,
            )
        ],
    )

    assert review_chunks([target], 32, 5000) == [[target]]
