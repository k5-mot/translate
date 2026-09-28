"""Upgradeの決定的差分、既存訳再利用および翻訳対象選別を検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.tasks.review.align import align
from translate.tasks.review.diff import diff
from translate.tasks.translation.reuse import previous_context, reuse
from translate.tasks.translation.translate import _chunks, _user_payload

if TYPE_CHECKING:
    from pathlib import Path


def _document(*values: tuple[str, str, str]) -> Document:
    """role、ID、textの列から単一page Documentを作る。"""

    blocks = [
        Block(
            id=f"block-{identifier}",
            order=index,
            kind="heading" if role == "heading" else "paragraph",
            content=TextUnit(
                id=identifier,
                spans=[TextSpan(id=f"span-{identifier}", source=text)],
            ),
        )
        for index, (role, identifier, text) in enumerate(values)
    ]
    return Document(pages=[Page(number=1, blocks=blocks)])


def test_diff_and_reuse_preserve_moved_japanese_text(tmp_path: Path) -> None:
    """一意な同文の移動を検出し、対応する日本語v1だけを再利用する。"""

    source_v1 = _document(("body", "old-a", "Alpha"), ("body", "old-b", "Beta"))
    source_v2 = _document(("body", "new-b", "Beta"), ("body", "new-a", "Alpha"))
    translation_v1 = _document(
        ("body", "ja-a", "アルファ"),
        ("body", "ja-b", "ベータ"),
    )
    baseline = align(source_v1, translation_v1)

    plan = diff(
        source_v1,
        source_v2,
        translation_v1,
        baseline,
        tmp_path / "diff",
    )
    updated, report = reuse(
        source_v2,
        translation_v1,
        plan,
        tmp_path / "reuse",
    )

    assert [change.kind for change in plan.changes] == ["moved", "moved"]
    assert [change.action for change in plan.changes] == ["reuse", "reuse"]
    assert report.reused_unit_ids == ["new-b", "new-a"]
    assert report.translation_target_ids == []
    assert updated.pages[0].blocks[0].content is not None
    assert updated.pages[0].blocks[0].content.spans[0].translated == "ベータ"
    assert (tmp_path / "diff/plan.json").is_file()
    assert (tmp_path / "reuse/report.json").is_file()


def test_modified_unit_is_translated_with_previous_context(tmp_path: Path) -> None:
    """1対1の変更箇所を全文翻訳対象とし、対応する旧英日文脈を渡す。"""

    source_v1 = _document(
        ("body", "old-a", "Alpha"),
        ("body", "old-change", "Old sentence"),
        ("body", "old-b", "Beta"),
    )
    source_v2 = _document(
        ("body", "new-a", "Alpha"),
        ("body", "new-change", "New sentence"),
        ("body", "new-b", "Beta"),
    )
    translation_v1 = _document(
        ("body", "ja-a", "アルファ"),
        ("body", "ja-change", "以前の文"),
        ("body", "ja-b", "ベータ"),
    )
    plan = diff(
        source_v1,
        source_v2,
        translation_v1,
        align(source_v1, translation_v1),
        tmp_path / "diff",
    )
    updated, report = reuse(
        source_v2,
        translation_v1,
        plan,
        tmp_path / "reuse",
    )
    context = previous_context(plan, source_v1, source_v2, translation_v1)

    changed = next(item for item in plan.changes if item.kind == "modified")
    assert changed.source_v2_ids == ["new-change"]
    assert changed.action == "translate"
    assert report.translation_target_ids == ["new-change"]
    assert context == {"span-new-change": ("Old sentence", "以前の文")}
    chunks = _chunks(
        updated, maximum_units=64, maximum_bytes=8192, previous_context=context
    )
    assert [[span.id for span in chunk] for chunk in chunks] == [["span-new-change"]]
    payload = json.loads(
        _user_payload(chunks[0], "", [], 8192, previous_context=context)
    )
    assert payload["items"] == [
        {
            "span_id": "span-new-change",
            "source": "New sentence",
            "previous_source": "Old sentence",
            "previous_translation": "以前の文",
        }
    ]


def test_incompatible_span_shape_is_not_reused(tmp_path: Path) -> None:
    """Span件数が異なる既存訳は同文でも推測移植せず翻訳対象に残す。"""

    source_v1 = _document(("body", "old", "Alpha"))
    source_v2 = _document(("body", "new", "Alpha"))
    translation_v1 = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block-ja",
                        order=0,
                        kind="paragraph",
                        content=TextUnit(
                            id="ja",
                            spans=[
                                TextSpan(id="ja-1", source="アル"),
                                TextSpan(id="ja-2", source="ファ"),
                            ],
                        ),
                    )
                ],
            )
        ]
    )
    plan = diff(
        source_v1,
        source_v2,
        translation_v1,
        align(source_v1, translation_v1),
        tmp_path / "diff",
    )

    assert plan.changes[0].kind == "unchanged"
    assert plan.changes[0].action == "translate"
