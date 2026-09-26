"""本文・caption・表セルが検査と比較から漏れないことを検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from translate.document import (
    AlignmentGroup,
    Block,
    Document,
    Finding,
    Inline,
    Page,
    TableCell,
    TextUnit,
    block_text_units,
)
from translate.tasks import align, check, report, review, verify
from translate.workflows.comparison_review import _comparison_document

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def _inlines(text: str) -> list[Inline]:
    """検査層の識別可能な文字列fixtureを作る。"""

    return [Inline(id=f"inline/{text}", text=text)]


def _document() -> Document:
    """本文・空訳caption・数値欠落セル・同じ数値を保持するセルを作る。"""

    return Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="body",
                        order=0,
                        kind="paragraph",
                        source=_inlines("Text 2"),
                        translated=_inlines("本文2"),
                    ),
                    Block(
                        id="table",
                        order=1,
                        kind="table",
                        caption=_inlines("Caption 3"),
                        translated_caption=[],
                        final_caption=_inlines("候補3"),
                        cells=[
                            TableCell(
                                row=1,
                                column=0,
                                source=_inlines("10"),
                                translated=_inlines("10"),
                                final=_inlines("10"),
                            ),
                            TableCell(
                                row=0,
                                column=0,
                                colspan=2,
                                source=_inlines("10"),
                                translated=[],
                                final=_inlines("候補10"),
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


@pytest.mark.parametrize("translated", [None, [], _inlines(""), _inlines("訳")])
@pytest.mark.parametrize("final", [None, [], _inlines(""), _inlines("候補")])
def test_text_unit_falls_back_only_for_absent_layer(
    translated: list[Inline] | None,
    final: list[Inline] | None,
) -> None:
    """未作成の層は補い、空配列・空文字の訳と候補は空のまま保持する。"""

    unit = TextUnit("unit", _inlines("Source"), translated, final)
    before = "Source" if translated is None else "".join(i.text for i in translated)
    candidate = before if final is None else "".join(i.text for i in final)
    assert unit.text("source") == "Source"
    assert unit.text("translated") == before
    assert unit.text("final") == candidate


def test_units_preserve_order_ids_references_and_serialized_schema() -> None:
    """結合範囲を複製せず、空画像を除外し、保存モデルを変更しない。"""

    document = _document()
    before = document.model_dump_json()
    blocks = document.pages[0].blocks
    units = [unit for block in blocks for unit in block_text_units(block)]
    assert [unit.id for unit in units] == [
        "body",
        "table/caption",
        "table/cell/0/0",
        "table/cell/1/0",
    ]
    assert units[2].source is blocks[1].cells[1].source
    assert units[2].translated is blocks[1].cells[1].translated
    assert units[2].final is blocks[1].cells[1].final
    assert document.model_dump_json() == before
    assert list(block_text_units(Block(id="image", order=0, kind="figure"))) == []


def test_units_include_target_only_content_and_keep_line_breaks() -> None:
    """原文なしの追加も対象にし、既存Inlineの改行表現を再利用する。"""

    block = Block(
        id="added",
        order=0,
        kind="figure",
        translated=_inlines("追加"),
        final_caption=[Inline(id="break", kind="line_break")],
    )
    units = list(block_text_units(block))
    assert [unit.id for unit in units] == ["added", "added/caption"]
    assert units[0].text("source") == ""
    assert units[0].text("translated") == "追加"
    assert units[1].text("final") == "\n"


def test_check_reports_cell_specific_numbers_and_empty_caption(tmp_path: Path) -> None:
    """別セルの同数値で欠落が相殺されず、保存Findingにも対象IDが付く。"""

    findings = check.run(_document(), None, tmp_path / "check")[2]
    assert {(item.kind, tuple(item.target_ids)) for item in findings} == {
        ("number-unit", ("table/caption",)),
        ("omission", ("table/caption",)),
        ("number-unit", ("table/cell/0/0",)),
        ("omission", ("table/cell/0/0",)),
    }
    stored = json.loads((tmp_path / "check/page-0002.json").read_text(encoding="utf-8"))
    assert stored == [item.model_dump() for item in findings]


def test_review_sends_all_units_and_cell_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """REVIEWの実prompt生成を通し、対象漏れ・重複・空訳fallbackを検出する。"""

    document = _document()
    checks = check.run(document, None, tmp_path / "check")
    prompts: list[dict] = []

    def capture(*args: object, **_kwargs: object) -> review.ReviewResponse:
        """外部LLMを呼ばず、実際のJSON promptを記録する。"""

        assert isinstance(args[4], str)
        prompts.append(json.loads(args[4]))
        return review.ReviewResponse(findings=checks[2])

    monkeypatch.setattr(review, "structured", capture)
    # RAGも外部serviceを呼ばず、文字列の検査範囲だけを検証する。
    monkeypatch.setattr(review, "search", lambda *_args, **_kwargs: [])
    result = review.run(
        document,
        checks,
        "rules",
        [],
        settings_factory(),
        tmp_path / "review",
    )
    assert len(prompts) == 1
    assert prompts[0]["pairs"] == [
        {"id": "body", "source": "Text 2", "translation": "本文2"},
        {"id": "table/caption", "source": "Caption 3", "translation": ""},
        {"id": "table/cell/0/0", "source": "10", "translation": ""},
        {"id": "table/cell/1/0", "source": "10", "translation": "10"},
    ]
    assert prompts[0]["automatic_findings"] == [item.model_dump() for item in checks[2]]
    assert result == checks


@pytest.mark.parametrize("outcome", ["approved", "rejected", "exception"])
def test_verify_checks_each_layer_and_restores_rejected_units(
    outcome: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """全対象の3層を候補検証へ送り、失敗時はcaption・セルも初回訳へ戻す。"""

    document = _document()
    table = document.pages[0].blocks[1]
    table.translated_caption = _inlines("初回3")
    table.final_caption = []
    table.cells[1].translated = _inlines("初回10")
    prompts: list[dict] = []

    def capture(*args: object, **_kwargs: object) -> verify.VerifyResponse:
        """検証応答の採否・例外を再現して送信候補を記録する。"""

        assert isinstance(args[4], str)
        prompts.append(json.loads(args[4]))
        if outcome == "exception":
            raise TimeoutError
        return verify.VerifyResponse(approved=outcome == "approved", issues=["不合格"])

    monkeypatch.setattr(verify, "structured", capture)
    result = verify.run(
        document,
        {2: [Finding(kind="accuracy", message="要検証")]},
        settings_factory(),
        tmp_path / "verify",
    )
    assert len(prompts) == 1
    assert prompts[0]["pairs"] == [
        {"id": "body", "source": "Text 2", "before": "本文2", "candidate": "本文2"},
        {
            "id": "table/caption",
            "source": "Caption 3",
            "before": "初回3",
            "candidate": "",
        },
        {
            "id": "table/cell/0/0",
            "source": "10",
            "before": "初回10",
            "candidate": "候補10",
        },
        {"id": "table/cell/1/0", "source": "10", "before": "10", "candidate": "10"},
    ]
    verified = result.pages[0].blocks[1]
    if outcome == "approved":
        assert verified.final_caption == []
        assert verified.cells[1].final == table.cells[1].final
    else:
        assert verified.final_caption == verified.translated_caption
        assert verified.cells[1].final == verified.cells[1].translated
        assert verified.final_caption is not None
        assert verified.final_caption[0].fix_status == "skipped"
        assert verified.final_caption[0].fix_error
    assert table.final_caption == []


@pytest.mark.parametrize("kind", ["table", "caption"])
@pytest.mark.parametrize("missing_side", ["neither", "source", "target"])
def test_comparison_aligns_non_body_units_and_reports_unmatched(
    kind: str,
    missing_side: str,
    tmp_path: Path,
) -> None:
    """表だけ・captionだけの比較と片側欠落が公開reportまで到達する。"""

    documents: list[Document] = []
    for side in ("source", "target"):
        block = Block(id=side, order=0, kind="table" if kind == "table" else "figure")
        if side != missing_side:
            if kind == "table":
                block.cells = [TableCell(row=0, column=0, source=_inlines("10"))]
            else:
                block.caption = _inlines("10")
        documents.append(Document(pages=[Page(number=2, blocks=[block])]))
    source, target = documents
    groups = align.run(source, target, tmp_path / "align")
    assert len(groups) == 1
    group = groups[0]
    suffix = "cell/0/0" if kind == "table" else "caption"
    assert group.source_ids == (
        [] if missing_side == "source" else [f"source/{suffix}"]
    )
    assert group.target_ids == (
        [] if missing_side == "target" else [f"target/{suffix}"]
    )
    assert (
        group.kind
        == {
            "neither": "matched",
            "source": "target_only",
            "target": "source_only",
        }[missing_side]
    )
    comparison = _comparison_document(source, target, groups)
    unit = next(block_text_units(comparison.pages[0].blocks[0]))
    assert unit.text("source") == ("" if missing_side == "source" else "10")
    assert unit.text("translated") == ("" if missing_side == "target" else "10")
    checks = check.run(comparison, None, tmp_path / "check")[2]
    if missing_side == "target":
        assert any(item.kind == "omission" for item in checks)
    report.run(groups, checks, [], tmp_path / "report.md", tmp_path / "report")
    rendered = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert group.kind in rendered
    assert f"/{suffix}" in rendered


@pytest.mark.parametrize("kind", ["body", "caption", "cell"])
@pytest.mark.parametrize("source_text", ["Capital plan", "API plan"])
def test_glossary_scope_is_shared_by_quality_units_and_comparison(
    kind: str, source_text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """実CHECKと比較REPORTで領域別の誤一致を防ぎ、真の違反のID・根拠を残す。"""

    connection = Mock(
        side_effect=AssertionError("quality checks must not call services")
    )
    monkeypatch.setattr("socket.socket.connect", connection)
    glossary = tmp_path / "glossary.csv"
    glossary.write_text(
        ",".join(check.GLOSSARY_FIELDS) + "\nAPI,,指定訳,,,,,\n", encoding="utf-8"
    )
    documents: list[Document] = []
    for side, text in (("source", source_text), ("target", "計画")):
        block = Block(
            id=side,
            order=0,
            kind={"body": "paragraph", "caption": "figure", "cell": "table"}[kind],
            source=_inlines(text) if kind == "body" else [],
            translated=_inlines("計画") if kind == "body" else None,
            caption=_inlines(text) if kind == "caption" else [],
            translated_caption=_inlines("計画") if kind == "caption" else None,
            cells=[
                TableCell(
                    row=0,
                    column=0,
                    source=_inlines(text),
                    translated=_inlines("計画"),
                ),
            ]
            if kind == "cell"
            else [],
        )
        documents.append(Document(pages=[Page(number=2, blocks=[block])]))
    source, target = documents
    original = [document.model_dump_json() for document in documents]
    source_unit = next(block_text_units(source.pages[0].blocks[0]))
    target_unit = next(block_text_units(target.pages[0].blocks[0]))
    findings = check.run(source, glossary, tmp_path / "translation-check")[2]
    expected_ids = [[source_unit.id]] if source_text == "API plan" else []
    assert [item.target_ids for item in findings] == expected_ids
    groups = [
        AlignmentGroup(source_ids=[source_unit.id], target_ids=[target_unit.id]),
    ]
    comparison = _comparison_document(source, target, groups)
    findings = check.run(comparison, glossary, tmp_path / "comparison-check")[2]
    output = tmp_path / "review.md"
    report.run(groups, findings, [], output, tmp_path / "report")
    stored = json.loads((tmp_path / "report/review.json").read_text(encoding="utf-8"))
    if source_text == "API plan":
        assert len(findings) == 1
        assert findings[0].kind == "glossary"
        assert findings[0].severity == "error"
        assert findings[0].target_ids == ["alignment/0"]
        assert findings[0].evidence == "API"
        assert findings[0].suggestion == "指定訳"
        assert "API" in output.read_text(encoding="utf-8")
        assert stored["findings"] == [findings[0].model_dump()]
    else:
        assert findings == []
        assert stored["findings"] == []
    assert [document.model_dump_json() for document in documents] == original
    connection.assert_not_called()
