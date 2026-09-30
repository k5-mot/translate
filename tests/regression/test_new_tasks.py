"""新しいTaskの決定的な契約を検証する。"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import pytest
from PIL import Image as PILImage

from translate.glossary import relevant_glossary
from translate.models.artifacts import ReviewResult
from translate.models.document import (
    Block,
    Document,
    Image,
    Page,
    TableCell,
    TextSpan,
    TextUnit,
)
from translate.models.review import ReviewTarget, Revision, TextEdit
from translate.tasks.converter.unpack import _validate_entries
from translate.tasks.preprocess.load import (
    _assign_cell_images,
    _inline,
    _normalized_cells,
    load_document,
)
from translate.tasks.preprocess.structure import (
    MAX_VISION_PIXELS,
    StructurePatch,
    StructureResponse,
    _apply_page,
    _bound_image,
    _schema,
)
from translate.tasks.preprocess.structure import (
    _chunks as structure_chunks,
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


def test_load_keeps_cells_when_docling_spans_overlap() -> None:
    """Doclingの矛盾した結合範囲を縮退し、両方のセル本文を保持する。"""

    item = {
        "data": {
            "num_rows": 1,
            "num_cols": 2,
            "table_cells": [
                {
                    "start_row_offset_idx": 0,
                    "start_col_offset_idx": 0,
                    "end_row_offset_idx": 1,
                    "end_col_offset_idx": 2,
                    "row_span": 1,
                    "col_span": 2,
                    "text": "first",
                },
                {
                    "start_row_offset_idx": 0,
                    "start_col_offset_idx": 1,
                    "end_row_offset_idx": 1,
                    "end_col_offset_idx": 2,
                    "row_span": 1,
                    "col_span": 1,
                    "text": "second",
                },
            ],
        }
    }

    cells = [source.cell for source in _normalized_cells(item, "#/tables/0")]

    assert [(cell.row, cell.column, cell.rowspan, cell.colspan) for cell in cells] == [
        (0, 0, 1, 1),
        (0, 1, 1, 1),
    ]
    assert [cell.content.text("source") for cell in cells] == ["first", "second"]


def test_load_keeps_unowned_picture_that_partially_overlaps_table() -> None:
    """明示的な所属がない表境界上の画像を独立図として保持する。"""

    page = Page(
        number=1,
        width=100,
        height=100,
        blocks=[
            Block(id="#/tables/0", order=0, kind="table", cells=[]),
            Block(
                id="#/pictures/0",
                order=1,
                kind="figure",
                image=Image(id="#/pictures/0/image", asset_path="assets/image.png"),
            ),
        ],
    )
    document = {
        "tables": [
            {
                "self_ref": "#/tables/0",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 0,
                            "t": 80,
                            "r": 80,
                            "b": 20,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
                "data": {
                    "num_rows": 1,
                    "num_cols": 1,
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 0,
                            "end_row_offset_idx": 1,
                            "end_col_offset_idx": 1,
                            "row_span": 1,
                            "col_span": 1,
                            "text": "cell",
                        }
                    ],
                },
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "parent": {"$ref": "#/body"},
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 70,
                            "t": 70,
                            "r": 90,
                            "b": 30,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
            }
        ],
    }

    _assign_cell_images(document, {1: page})

    assert [block.id for block in page.blocks] == ["#/tables/0", "#/pictures/0"]


def test_structure_chunks_single_long_block_with_bounded_excerpt() -> None:
    """長文Blockでも分類用抜粋を上限内に収めてSTRUCTUREへ渡す。"""

    block = Block(
        id="#/texts/0",
        order=0,
        kind="paragraph",
        content=_unit("#/texts/0/content", "long source " * 2_000),
    )

    chunks = structure_chunks([block], maximum_blocks=20, maximum_bytes=2_980)

    assert chunks == [[block]]


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


def test_structure_ignores_caption_returned_as_block_kind() -> None:
    """caption誤返却で応答全体を失敗させず、種別変更だけを無視する。"""

    patch = StructurePatch.model_validate({"block_id": "block", "kind": "caption"})

    assert patch.kind is None


def test_structure_rejects_kind_without_required_block_content() -> None:
    """tableをcontent必須kindへ変える不整合patchだけを適用しない。"""

    block = Block(
        id="table",
        order=0,
        kind="table",
        cells=[
            TableCell(
                id="cell",
                row=0,
                column=0,
                content=_unit("cell-content", "value"),
            )
        ],
    )
    page = Page(number=1, blocks=[block])
    diagnostics: list[str] = []

    _apply_page(
        page,
        [
            (
                "call",
                StructureResponse(
                    patches=[StructurePatch(block_id="table", kind="code")]
                ),
            )
        ],
        diagnostics,
    )

    assert block.kind == "table"
    assert diagnostics == ["call invalid_kind table code"]


def test_load_splits_long_text_without_loss() -> None:
    """長大Docling文字列を安定IDと有限byteのSpanへ欠落なく分ける。"""

    source = "English 日本語 " * 300

    spans = _inline("#/texts/0/content", source)

    assert len(spans) > 1
    assert "".join(span.source for span in spans) == source
    assert all(len(span.source.encode("utf-8")) <= 1024 for span in spans)
    assert spans[1].id == "#/texts/0/content/span-0002"


def test_glossary_keeps_only_terms_found_in_english_source() -> None:
    """巨大用語集のうち英語原文へ現れる行だけをprompt用CSVへ残す。"""

    glossary = (
        "english-short,english-long,japanese-short,japanese-long\n"
        "API,Application Programming Interface,API,API\n"
        "ART,Artillery,砲兵,砲兵\n"
        "VLM,Vision Language Model,VLM,視覚言語モデル\n"
    )

    selected = relevant_glossary(
        glossary,
        "The application uses an API; partial must not trigger a shorter term.",
    )

    assert "API,Application Programming Interface" in selected
    assert "ART,Artillery" not in selected
    assert "VLM,Vision Language Model" not in selected


def test_glossary_keeps_complete_matching_rows_within_byte_limit() -> None:
    """多数の該当用語があってもCSV行を壊さずprompt枠へ収める。"""

    glossary = "english-short,english-long,japanese-short,japanese-long\n" + "".join(
        f"TERM{index},Long Term {index},用語{index},用語{index}\n"
        for index in range(20)
    )
    source = " ".join(f"TERM{index}" for index in range(20))

    selected = relevant_glossary(glossary, source, maximum_bytes=180)

    assert len(selected.encode("utf-8")) <= 180
    assert selected.startswith("english-short,english-long")
    assert 0 < len(selected.splitlines()) - 1 < 20


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


def test_review_chunks_split_large_target_without_losing_source_or_spans() -> None:
    """単一ReviewTargetが大きくても原文と修正単位を保って分割する。"""

    spans = [
        TextSpan(id=f"span-{index}", source="English " * 80, translated="訳" * 200)
        for index in range(6)
    ]
    target = ReviewTarget(
        id="target",
        source="".join(span.source for span in spans),
        translation="".join(span.text() for span in spans),
        target_ids=["unit"],
        spans=spans,
    )

    parts = [part for chunk in review_chunks([target], 32, 3000) for part in chunk]

    assert len(parts) > 1
    assert "".join(part.source for part in parts) == target.source
    assert [span.id for part in parts for span in part.spans] == [
        span.id for span in spans
    ]


def test_review_chunks_keep_one_large_translated_span_intact() -> None:
    """長い翻訳spanを壊さず、残余容量へ原文を分配して分割する。"""

    span = TextSpan(
        id="span",
        source="English source. " * 250,
        translated="訳" * 900,
    )
    target = ReviewTarget(
        id="target",
        source=span.source,
        translation=span.text(),
        target_ids=["unit"],
        spans=[span],
    )

    parts = [part for chunk in review_chunks([target], 32, 4952) for part in chunk]

    assert len(parts) > 1
    assert "".join(part.source for part in parts) == target.source
    assert [item.id for part in parts for item in part.spans] == [span.id]
