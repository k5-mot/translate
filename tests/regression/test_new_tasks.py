"""新しいTaskの決定的な契約を検証する。"""

from __future__ import annotations

import json
import zipfile
from importlib import import_module
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PIL import Image as PILImage

from translate.adapters.glossary import relevant_glossary
from translate.adapters.llm import (
    LLMClient,
    LLMInputExceededError,
    LLMInvalidResponseError,
    StructuredResult,
)
from translate.common.config import Config
from translate.models.artifacts import ReviewResult
from translate.models.document import (
    Block,
    Document,
    Image,
    Page,
    TableCell,
    TextSpan,
    TextUnit,
    iter_text_units,
)
from translate.models.review import (
    ReviewFinding,
    ReviewResponse,
    ReviewRevision,
    ReviewTarget,
    ReviewTextEdit,
    Revision,
    TextEdit,
)

_validate_entries = import_module("translate.tasks.02_unpack")._validate_entries  # noqa: SLF001
_assign_cell_images = import_module("translate.tasks.12_load")._assign_cell_images  # noqa: SLF001
_inline = import_module("translate.tasks.12_load")._inline  # noqa: SLF001
_normalized_cells = import_module("translate.tasks.12_load")._normalized_cells  # noqa: SLF001
load_document = import_module("translate.tasks.12_load").load_document
normalize = import_module("translate.tasks.11_normalize").normalize
MAX_VISION_PIXELS = import_module("translate.tasks.13_structure").MAX_VISION_PIXELS
StructurePatch = import_module("translate.tasks.13_structure").StructurePatch
StructureResponse = import_module("translate.tasks.13_structure").StructureResponse
_apply_page = import_module("translate.tasks.13_structure")._apply_page  # noqa: SLF001
_bound_image = import_module("translate.tasks.13_structure")._bound_image  # noqa: SLF001
_normalize_heading_levels = import_module(  # noqa: SLF001
    "translate.tasks.13_structure"
)._normalize_heading_levels
_schema = import_module("translate.tasks.13_structure")._schema  # noqa: SLF001
structure_chunks = import_module("translate.tasks.13_structure")._chunks  # noqa: SLF001
lint = import_module("translate.tasks.50_lint").lint
convert_block = import_module("translate.tasks.52_markdown").convert_block
apply_revisions = import_module("translate.tasks.42_fix").apply_revisions
review_chunks = import_module("translate.tasks.41_review")._chunks  # noqa: SLF001
execute_review = import_module("translate.tasks.41_review")._execute  # noqa: SLF001
review_user_payload = import_module("translate.tasks.41_review")._user_payload  # noqa: SLF001
run_review = import_module("translate.tasks.41_review").review
TranslationItem = import_module("translate.tasks.30_translate").TranslationItem
TranslationResponse = import_module("translate.tasks.30_translate").TranslationResponse
execute_translation = import_module("translate.tasks.30_translate")._execute  # noqa: SLF001
translation_schema = import_module("translate.tasks.30_translate")._schema  # noqa: SLF001
run_translation = import_module("translate.tasks.30_translate").translate

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


def test_translation_splits_missing_ids_after_retry(tmp_path: Path) -> None:
    """一括応答で欠けた訳を再送・分割し、全対象の訳を集める。"""

    config = Config(openai_base_url="http://llm", openai_translation_model="model")
    client = LLMClient(config)
    responses = [
        [("a", "訳A"), ("b", "訳B")],
        [],
        [("c", "訳C")],
        [("d", "訳D")],
    ]
    structured = MagicMock(
        side_effect=[
            StructuredResult(
                response=TranslationResponse(
                    translations=[
                        TranslationItem(span_id=key, text=value) for key, value in items
                    ]
                ),
                attempts=1,
                input_tokens=10,
                output_tokens=10,
            )
            for items in responses
        ]
    )
    client.structured = structured  # type: ignore[method-assign]

    calls = execute_translation(
        client=client,
        config=config,
        spans=[TextSpan(id=key, source=key) for key in "abcd"],
        task_directory=tmp_path,
        rules="",
        glossary="",
        lineage=["chunk-0000"],
        depth=0,
        allow_missing_retry=True,
        diagnostics=[],
        previous_context={},
    )

    assert structured.call_count == 4
    assert {
        item.span_id: item.text
        for _, response in calls
        for item in response.translations
    } == {"a": "訳A", "b": "訳B", "c": "訳C", "d": "訳D"}


def test_translation_rejects_missing_single_span(tmp_path: Path) -> None:
    """最小単位の再送後も訳が欠けたら空訳を確定せず失敗する。"""

    config = Config(openai_base_url="http://llm", openai_translation_model="model")
    client = LLMClient(config)
    structured = MagicMock(
        return_value=StructuredResult(
            response=TranslationResponse(translations=[]),
            attempts=1,
            input_tokens=10,
            output_tokens=10,
        )
    )
    client.structured = structured  # type: ignore[method-assign]

    with pytest.raises(LLMInvalidResponseError, match="span-a"):
        execute_translation(
            client=client,
            config=config,
            spans=[TextSpan(id="span-a", source="A")],
            task_directory=tmp_path,
            rules="",
            glossary="",
            lineage=["chunk-0000"],
            depth=0,
            allow_missing_retry=True,
            diagnostics=[],
            previous_context={},
        )

    assert structured.call_count == 2


def test_translation_accepts_span_id_without_fragment_marker(tmp_path: Path) -> None:
    """LLMが先頭の#だけ落としたIDの訳を元のSpanへ適用する。"""

    config = Config(openai_base_url="http://llm", openai_translation_model="model")
    client = LLMClient(config)
    structured = MagicMock(
        return_value=StructuredResult(
            response=TranslationResponse(
                translations=[
                    TranslationItem(
                        span_id="/texts/48/content/span-0001", text="伝送媒体;"
                    )
                ]
            ),
            attempts=1,
            input_tokens=10,
            output_tokens=10,
        )
    )
    client.structured = structured  # type: ignore[method-assign]

    calls = execute_translation(
        client=client,
        config=config,
        spans=[
            TextSpan(id="#/texts/48/content/span-0001", source="Transmission Media;")
        ],
        task_directory=tmp_path,
        rules="",
        glossary="",
        lineage=["chunk-0000"],
        depth=0,
        allow_missing_retry=True,
        diagnostics=[],
        previous_context={},
    )

    assert structured.call_count == 1
    assert calls[0][1].translations == [
        TranslationItem(span_id="#/texts/48/content/span-0001", text="伝送媒体;")
    ]


def test_translation_does_not_restart_exhausted_schema_retries(tmp_path: Path) -> None:
    """AdapterのSchema再試行を使い切ったCallを別方式で追加送信しない。"""
    config = Config(openai_base_url="http://llm", openai_translation_model="model")
    client = MagicMock()
    client.structured.side_effect = LLMInvalidResponseError("invalid JSON")
    with pytest.raises(LLMInvalidResponseError):
        execute_translation(
            client=client,
            config=config,
            spans=[TextSpan(id="span-a", source="Original sentence.")],
            task_directory=tmp_path,
            rules="",
            glossary="",
            lineage=["chunk-0000"],
            depth=0,
            allow_missing_retry=True,
            diagnostics=[],
            previous_context={},
        )
    assert client.structured.call_count == 1
    calls = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in tmp_path.glob("calls/*/call.json")
    ]
    assert len(calls) == 1
    assert calls[0]["status"] == "failed"


def test_translation_retries_single_missing_span_after_split(tmp_path: Path) -> None:
    """分割済みCallの欠落一件を単独で再送して訳文を回収する。"""

    config = Config(openai_base_url="http://llm", openai_translation_model="model")
    client = LLMClient(config)
    structured = MagicMock(
        side_effect=[
            StructuredResult(
                response=TranslationResponse(
                    translations=[
                        TranslationItem(span_id="a", text="訳A"),
                    ]
                ),
                attempts=1,
                input_tokens=10,
                output_tokens=10,
            ),
            StructuredResult(
                response=TranslationResponse(translations=[]),
                attempts=1,
                input_tokens=10,
                output_tokens=10,
            ),
            StructuredResult(
                response=TranslationResponse(
                    translations=[TranslationItem(span_id="b", text="訳B")]
                ),
                attempts=1,
                input_tokens=10,
                output_tokens=10,
            ),
        ]
    )
    client.structured = structured  # type: ignore[method-assign]

    calls = execute_translation(
        client=client,
        config=config,
        spans=[TextSpan(id=key, source=key) for key in "ab"],
        task_directory=tmp_path,
        rules="",
        glossary="",
        lineage=["chunk-0000", "missing"],
        depth=1,
        allow_missing_retry=False,
        diagnostics=[],
        previous_context={},
    )

    assert structured.call_count == 3
    assert {
        item.span_id: item.text
        for _, response in calls
        for item in response.translations
        if item.text
    } == {"a": "訳A", "b": "訳B"}


@pytest.mark.parametrize(
    "translation", ["", "THE BIG PICTURE", "(省略)", "余計" * 300, "Army:"]
)
def test_translation_preserves_model_text_without_quality_retries(
    tmp_path: Path,
    translation: str,
) -> None:
    """長さ・同文・軍種名による補正や再送を行わず、品質判断をREVIEWへ渡す。"""
    client = MagicMock()
    client.structured.return_value = StructuredResult(
        response=TranslationResponse(
            translations=[TranslationItem(span_id="span-a", text=translation)]
        ),
        attempts=1,
        input_tokens=10,
        output_tokens=10,
    )
    calls = execute_translation(
        client=client,
        config=Config(openai_translation_model="model"),
        spans=[TextSpan(id="span-a", source="THE BIG PICTURE")],
        task_directory=tmp_path,
        rules="",
        glossary="",
        lineage=["chunk-0000"],
        depth=0,
        allow_missing_retry=True,
        diagnostics=[],
        previous_context={},
    )
    assert client.structured.call_count == 1
    assert calls[-1][1].translations[0].text == translation


def test_translation_reuses_calls_when_rules_and_model_change(tmp_path: Path) -> None:
    """入力が同じなら規則・用語集・modelの変更で成功応答を再送しない。"""
    client = MagicMock()
    client.structured.return_value = StructuredResult(
        response=TranslationResponse(
            translations=[TranslationItem(span_id="span-a", text="THE BIG PICTURE")]
        ),
        attempts=1,
        input_tokens=10,
        output_tokens=10,
    )
    kwargs = {
        "client": client,
        "spans": [TextSpan(id="span-a", source="THE BIG PICTURE")],
        "task_directory": tmp_path,
        "lineage": ["chunk-0000"],
        "depth": 0,
        "allow_missing_retry": True,
        "diagnostics": [],
        "previous_context": {},
    }
    first = execute_translation(
        **kwargs,
        config=Config(openai_translation_model="first"),
        rules="",
        glossary="",
    )
    second = execute_translation(
        **kwargs,
        config=Config(openai_translation_model="second"),
        rules="Updated rules",
        glossary="english-short,japanese\\nPICTURE,全体像",
    )
    assert first == second
    assert client.structured.call_count == 1


def test_translation_schema_constrains_ids_without_quality_threshold() -> None:
    """応答の件数とfieldを制約し、訳文の文字数を品質条件にしない。"""
    schema = translation_schema(2)
    translations = schema["properties"]["translations"]
    assert translations["minItems"] == translations["maxItems"] == 2
    assert translations["items"]["properties"]["text"] == {"type": "string"}


def test_translation_short_ids_restore_original_spans_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じ要素の複数Spanを短いIDで区別し、順不同の応答も元IDへ戻して保存する。"""
    config = Config(
        openai_base_url="http://llm",
        openai_llm_base_url=None,
        openai_translation_model="model",
        qdrant_uri=None,
        openai_embedding_model=None,
    )
    spans = [
        TextSpan(id=f"#/texts/33/content/span-{i:04d}", source=text)
        for i, text in enumerate(["Footnote.", "Use superscript."], 1)
    ]
    completion = MagicMock()
    completion.choices = [MagicMock(finish_reason="stop")]
    completion.choices[0].message.content = json.dumps(
        {
            "translations": [
                {"span_id": "2", "text": "上付きにする。"},
                {"span_id": "1", "text": "脚注。"},
            ]
        }
    )
    completion.usage = None
    client = LLMClient(config)
    create = MagicMock(return_value=completion)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    kwargs = {
        "client": client,
        "config": config,
        "spans": spans,
        "task_directory": tmp_path,
        "rules": "",
        "glossary": "",
        "lineage": ["chunk-0000"],
        "depth": 0,
        "allow_missing_retry": True,
        "diagnostics": [],
        "previous_context": {spans[1].id: ("Old source", "旧訳")},
    }
    try:
        result = execute_translation(**kwargs)
        user = json.loads(create.call_args.kwargs["messages"][1]["content"])
        assert [item["span_id"] for item in user["items"]] == ["1", "2"]
        assert user["items"][1]["previous_translation"] == "旧訳"
        assert {item.span_id: item.text for item in result[0][1].translations} == {
            spans[0].id: "脚注。",
            spans[1].id: "上付きにする。",
        }
        directory = tmp_path / "calls" / result[0][0]
        assert json.loads((directory / "call.json").read_text(encoding="utf-8"))[
            "target_ids"
        ] == [s.id for s in spans]
        assert (
            json.loads((directory / "response.json").read_text(encoding="utf-8"))[
                "translations"
            ][0]["span_id"]
            == spans[1].id
        )
        assert execute_translation(**kwargs) == result
        create.assert_called_once()
    finally:
        client.client.close()


def test_translation_ignores_ids_from_other_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """別Callの有効なSpan IDが応答に混入しても既存訳を上書きしない。"""

    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block-a", order=0, kind="paragraph", content=_unit("a", "A")
                    ),
                    Block(
                        id="block-b", order=1, kind="paragraph", content=_unit("b", "B")
                    ),
                ],
            )
        ]
    )
    responses = [
        TranslationResponse(
            translations=[
                TranslationItem(span_id="a/span-0001", text="正しいA"),
                TranslationItem(span_id="b/span-0001", text="誤訳B"),
            ]
        ),
        TranslationResponse(
            translations=[
                TranslationItem(span_id="b/span-0001", text="正しいB"),
                TranslationItem(span_id="a/span-0001", text="誤訳A"),
            ]
        ),
    ]
    monkeypatch.setattr(
        LLMClient,
        "structured",
        MagicMock(
            side_effect=[
                StructuredResult(
                    response=response,
                    attempts=1,
                    input_tokens=10,
                    output_tokens=10,
                )
                for response in responses
            ]
        ),
    )

    result = run_translation(
        document,
        tmp_path / "translation",
        tmp_path,
        Config(
            openai_base_url="http://llm",
            openai_translation_model="model",
            translate_max_units=1,
        ),
        "",
        "",
    )

    assert [unit.spans[0].translated for _, unit in iter_text_units(result)] == [
        "正しいA",
        "正しいB",
    ]
    diagnostics = json.loads((tmp_path / "task-translate.json").read_text())
    assert sum("unexpected_span" in item for item in diagnostics["diagnostics"]) == 2


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


@pytest.mark.parametrize("repeat", [5, 12])
def test_fix_applies_short_revision_without_length_threshold(
    repeat: int,
) -> None:
    """構造上有効な短い候補を文字数比で棄却せず適用する。"""

    original = "これは既存の翻訳文です。" * repeat
    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block",
                        order=0,
                        kind="paragraph",
                        content=_unit("unit", "source", original),
                    )
                ],
            )
        ]
    )
    review = ReviewResult(
        findings=[],
        revisions=[
            Revision(
                id="short",
                target_id="unit",
                edits=[TextEdit(span_id="unit/span-0001", text="一文だけ。")],
            )
        ],
    )

    result = apply_revisions(document, review)

    span = result.document.pages[0].blocks[0].content.spans[0]  # type: ignore[union-attr]
    assert span.revised == "一文だけ。"
    assert span.translated == original
    assert result.outcomes[0].reason_code == "applied"


@pytest.mark.parametrize(
    ("source", "translated", "proposed"),
    [
        (
            "Accelerating Assistance to Energy Employees",
            "エネルギー関係者に対する支援を加速",
            "$43 million",
        ),
        (
            "maintain the safety of nuclear weapons stockpile",
            "核兵器備蓄の安全性を維持する。" * 5,
            "原文の訳語について説明すべきである。" * 9,
        ),
        (
            "A long paragraph about the program",
            "日本語の本文です。" * 30,
            "日本語の本文です。" * 18,
        ),
        ("7,434", "7,434", "7,436"),
    ],
)
def test_fix_does_not_rejudge_revision_meaning(
    source: str, translated: str, proposed: str
) -> None:
    """REVIEWの候補を言語・文字数比・数値の固定ルールで再評価しない。"""

    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block",
                        order=0,
                        kind="paragraph",
                        content=_unit("unit", source, translated),
                    )
                ],
            )
        ]
    )
    review = ReviewResult(
        findings=[],
        revisions=[
            Revision(
                id="bad",
                target_id="unit",
                edits=[TextEdit(span_id="unit/span-0001", text=proposed)],
            )
        ],
    )

    result = apply_revisions(document, review)
    span = result.document.pages[0].blocks[0].content.spans[0]  # type: ignore[union-attr]
    assert span.revised == proposed
    assert span.translated == translated
    assert result.outcomes[0].reason_code == "applied"


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


def test_markdown_table_removes_dot_leaders_and_preserves_missing_value() -> None:
    """表の装飾点線を除き、欠損値のダッシュを水平線へ変えない。"""

    block = Block(
        id="table",
        order=0,
        kind="table",
        cells=[
            TableCell(
                id="label",
                row=0,
                column=0,
                content=_unit("label/content", "Revenue ........"),
            ),
            TableCell(
                id="value",
                row=0,
                column=1,
                content=_unit("value/content", "—"),
            ),
        ],
    )

    value = convert_block(block, 30.0)

    assert "Revenue" in value
    assert "........" not in value
    assert "\\-" in value


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


@pytest.mark.parametrize(
    ("body_kind", "index_title"),
    [
        ("long_text", "List of Figures"),
        ("short_text", "図一覧"),
        ("table", "表一覧"),
        ("code", "List of Tables"),
    ],
)
def test_index_heading_does_not_discard_body_on_same_page(
    tmp_path: Path, body_kind: str, index_title: str
) -> None:
    """目次と同じページにある本文を、段落の長さや表の形式によらず保持する。"""

    paragraph = "本文と図の説明が同じページに続きます。" * (
        12 if body_kind == "long_text" else 1
    )
    if body_kind == "code":
        paragraph = "# input ... 2"
    texts = [
        (1, "section_header", "Table of Contents"),
        (1, "text", "Chapter 1 ........ 1"),
        (2, "section_header", index_title),
        (2, "text", "Figure 1 ........ 2"),
        (2, "code" if body_kind == "code" else "text", paragraph),
    ]
    value = {
        "schema_name": "DoclingDocument",
        "name": "mixed-index",
        "pages": {
            str(number): {"size": {"width": 100, "height": 200}} for number in (1, 2)
        },
        "texts": [
            {
                "self_ref": f"#/texts/{index}",
                "label": label,
                "text": text,
                "prov": [{"page_no": page}],
            }
            for index, (page, label, text) in enumerate(texts)
        ],
        "tables": [],
        "pictures": [],
        "key_value_items": [],
        "form_items": [],
        "groups": [],
        "body": {
            "children": [{"$ref": f"#/texts/{index}"} for index in range(len(texts))]
        },
    }
    if body_kind == "table":
        value["texts"].pop()
        value["body"]["children"].pop()
        value["tables"] = [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "prov": [{"page_no": 2}],
                "data": {
                    "num_rows": 1,
                    "num_cols": 1,
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 0,
                            "end_row_offset_idx": 1,
                            "end_col_offset_idx": 1,
                            "text": "Document ID: SYS-DD-001",
                        }
                    ],
                },
            }
        ]
        value["body"]["children"].append({"$ref": "#/tables/0"})
    source = tmp_path / "source.json"
    source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    normalized = normalize(source, tmp_path / "normalized")
    document = load_document(json.loads(normalized.read_text(encoding="utf-8")))

    assert document.pages[0].blocks == []
    assert len(document.pages[1].blocks) == 1
    block = document.pages[1].blocks[0]
    if body_kind == "table":
        assert block.kind == "table"
        assert block.cells[0].content.text("source") == "Document ID: SYS-DD-001"
    else:
        assert block.content.text("source") == paragraph


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

    assert [(cell.row, cell.column) for cell in cells] == [
        (0, 0),
        (0, 1),
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


def test_structure_chunks_long_block_at_sentence_boundaries() -> None:
    """長文をSpan境界で分け、STRUCTURE入力から中間の本文を省略しない。"""
    text = "This sentence contains information that must be preserved. " * 100
    content = TextUnit(id="body/content", spans=_inline("body/content", text))
    block = Block(id="body", order=0, kind="paragraph", content=content)
    chunks = structure_chunks([block], maximum_blocks=20, maximum_bytes=2980)
    assert len(chunks) > 1
    assert (
        "".join(part.content.text("source") for chunk in chunks for part in chunk)
        == text
    )
    assert all(part.id == block.id for chunk in chunks for part in chunk)


def test_structure_rejects_oversized_sentence_without_truncation() -> None:
    """最小の文が上限を超える場合は本文を切り捨てず失敗する。"""
    block = Block(
        id="body", order=0, kind="paragraph", content=_unit("body", "word " * 2000)
    )
    with pytest.raises(ValueError, match="single sentence exceeds"):
        structure_chunks([block], maximum_blocks=20, maximum_bytes=2980)


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


def test_structure_preserves_existing_image_caption() -> None:
    """既存Captionと本文を、誤ったcaption移動patchで失わない。"""

    figure = Block(
        id="figure",
        order=0,
        kind="figure",
        image=Image(
            id="image",
            asset_path="image.png",
            caption=_unit("existing-caption", "Original caption"),
        ),
    )
    paragraph = Block(
        id="paragraph",
        order=1,
        kind="paragraph",
        content=_unit("paragraph-content", "Unrelated body text"),
    )
    page = Page(number=1, blocks=[figure, paragraph])
    diagnostics: list[str] = []

    _apply_page(
        page,
        [
            (
                "call",
                StructureResponse(
                    patches=[
                        StructurePatch(block_id="figure", caption_source_id="paragraph")
                    ]
                ),
            )
        ],
        diagnostics,
    )

    assert figure.image is not None
    assert figure.image.caption is not None
    assert figure.image.caption.id == "existing-caption"
    assert [block.id for block in page.blocks] == ["figure", "paragraph"]
    assert diagnostics == ["call caption_already_present figure"]


def test_structure_preserves_cross_page_heading_level_after_llm_reset() -> None:
    """ページ境界のlevel=1誤補正をDocling初期levelへ戻す。"""

    first = Block(
        id="h1",
        order=0,
        kind="heading",
        level=1,
        content=_unit("h1/content", "Document"),
    )
    second = Block(
        id="h2",
        order=0,
        kind="heading",
        level=1,
        content=_unit("h2/content", "Section"),
    )
    document = Document(
        pages=[Page(number=2, blocks=[first]), Page(number=3, blocks=[second])]
    )
    diagnostics: list[str] = []

    _normalize_heading_levels(document, {"h1": 1, "h2": 2}, diagnostics)

    assert second.level == 2
    assert diagnostics == [
        "h2 level_normalized llm=1 baseline=2 reason=page_boundary_reset"
    ]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    ("source_kind", "target_kind"),
    [("heading", "table"), ("paragraph", "table"), ("paragraph", "paragraph")],
)
def test_structure_caption_transfer_respects_final_block_roles(
    *, reverse: bool, source_kind: str, target_kind: str
) -> None:
    """応答の順序によらず、見出しをCaptionへ移さず、明示的な段落への補正は許可する。"""
    source = Block(
        id="source",
        order=0,
        kind="heading",
        level=1,
        content=_unit("source/content", "Table description"),
    )
    target = Block.model_validate(
        {
            "id": "target",
            "order": 1,
            "kind": target_kind,
            "content": _unit("target/content", "Body").model_dump()
            if target_kind == "paragraph"
            else None,
            "cells": [
                TableCell(id="cell", row=0, column=0, content=_unit("cell", "value"))
            ]
            if target_kind == "table"
            else [],
        }
    )
    patches = [
        StructurePatch.model_validate({"block_id": "source", "kind": source_kind}),
        StructurePatch(block_id="target", caption_source_id="source"),
    ]
    page = Page(number=2, blocks=[source, target])
    diagnostics: list[str] = []

    _apply_page(
        page,
        [
            (
                "call",
                StructureResponse(
                    patches=list(reversed(patches)) if reverse else patches
                ),
            )
        ],
        diagnostics,
    )

    if source_kind == "paragraph" and target_kind == "table":
        assert [block.id for block in page.blocks] == ["target"]
        assert target.caption.text("source") == "Table description"
        assert diagnostics == []
    else:
        assert [block.id for block in page.blocks] == ["source", "target"]
        assert target.caption is None
        assert diagnostics


@pytest.mark.parametrize(
    ("title", "initial_level", "expected_level"),
    [
        ("1 Document Control", 3, 1),
        ("2 Lists", 2, 1),
        ("7.1 Heading", 1, 2),
        ("7.1.1 Heading", 4, 3),
        ("2026 Results", 2, 2),
    ],
)
def test_structure_uses_section_depth_for_numbered_heading_level(
    title: str, initial_level: int, expected_level: int
) -> None:
    """番号付き見出しの深さを章番号から揃え、年号は章番号として扱わない。"""
    heading = Block(
        id="heading",
        order=0,
        kind="heading",
        level=initial_level,
        content=_unit("heading/content", title),
    )
    document = Document(pages=[Page(number=2, blocks=[heading])])

    _normalize_heading_levels(document, {"heading": initial_level}, [])

    assert heading.level == expected_level


@pytest.mark.parametrize(
    "title", ["CHAPTER II", "1 Document Control", "7 TOC Levels", "10 Notes"]
)
def test_structure_allows_explicit_chapter_reset_to_level_one(title: str) -> None:
    """先行見出しがあるページ境界でも、明示的な章番号のlevel=1補正を維持する。"""

    heading = Block(
        id="chapter",
        order=0,
        kind="heading",
        level=1,
        content=_unit("chapter/content", title),
    )
    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="prior",
                        order=0,
                        kind="heading",
                        level=1,
                        content=_unit("prior/content", "Introduction"),
                    )
                ],
            ),
            Page(number=3, blocks=[heading]),
        ]
    )
    diagnostics: list[str] = []

    _normalize_heading_levels(document, {"chapter": 2}, diagnostics)

    assert heading.level == 1
    assert diagnostics == []


def test_structure_does_not_normalize_same_page_heading_reset() -> None:
    """同一ページ内の明示的な階層変更は補正対象にしない。"""

    first = Block(
        id="h1",
        order=0,
        kind="heading",
        level=1,
        content=_unit("h1/content", "Document"),
    )
    second = Block(
        id="h2",
        order=1,
        kind="heading",
        level=1,
        content=_unit("h2/content", "Section"),
    )
    document = Document(pages=[Page(number=2, blocks=[first, second])])
    diagnostics: list[str] = []

    _normalize_heading_levels(document, {"h1": 1, "h2": 2}, diagnostics)

    assert second.level == 1
    assert diagnostics == []


def test_structure_keeps_cover_out_of_body_heading_hierarchy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """表紙を本文の親にせず、本文内のページ境界補正だけを維持する。"""
    module = import_module("translate.tasks.13_structure")
    document = Document(
        pages=[
            Page(
                number=number,
                blocks=[
                    Block(
                        id=key,
                        order=0,
                        kind="heading",
                        level=level,
                        content=_unit(f"{key}/content", title),
                    )
                ],
            )
            for number, key, level, title in (
                (1, "cover", 1, "System Design"),
                (2, "body", 3, "Introduction"),
                (3, "section", 2, "Requirements"),
            )
        ]
    )
    directory = tmp_path / "structure"
    (directory / "pages").mkdir(parents=True)
    for page in document.pages:
        PILImage.new("RGB", (20, 20)).save(
            directory / "pages" / f"page-{page.number:04d}.png"
        )
    client = MagicMock()
    client.structured.side_effect = [
        StructuredResult(
            response=StructureResponse(
                patches=[StructurePatch(block_id=key, kind="heading", level=1)]
            ),
            attempts=1,
            input_tokens=100,
            output_tokens=20,
        )
        for key in ("cover", "body", "section")
    ]
    monkeypatch.setattr(module, "LLMClient", MagicMock(return_value=client))

    result = module.structure(
        document,
        tmp_path / "source.pdf",
        directory,
        tmp_path,
        Config(openai_structure_model="model"),
        "rules",
    )

    requests = [
        json.loads(call.kwargs["user"]) for call in client.structured.call_args_list
    ]
    assert requests[1]["heading_history"] == []
    assert requests[2]["heading_history"] == [{"level": 1, "text": "Introduction"}]
    assert result.pages[1].blocks[0].level == 1
    assert result.pages[2].blocks[0].level == 2
    assert document.pages[1].blocks[0].level == 3


def test_load_splits_long_text_without_loss() -> None:
    """長文を文境界で分け、空白も含む原文と安定IDを保持する。"""

    source = "First sentence.\n Second sentence! " * 300

    spans = _inline("#/texts/0/content", source)

    assert len(spans) > 1
    assert "".join(span.source for span in spans) == source
    assert all(span.source.rstrip().endswith((".", "!")) for span in spans)
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
        TextSpan(
            id=f"span-{index}", source="English sentence. " * 40, translated="訳" * 200
        )
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


def test_review_reserves_json_envelope_for_split_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """分割対象が本文予算を使い切ってもJSON外枠を含む要求が収まる。"""

    class Client:
        def __init__(self, config: Config) -> None:
            """共通要求が参照する設定を保持する。"""
            self.config = config
            self.client = MagicMock()

        def structured(self, **values: object) -> StructuredResult[ReviewResponse]:
            """実要求のuser payloadが入力予算内か検査する。"""

            user = values["user"]
            assert isinstance(user, str)
            total = (
                len(
                    (values["system"] + "\n\n" + values["contract"] + user).encode(
                        "utf-8"
                    )
                )
                + 256
            )
            assert total <= values["input_tokens"]
            return StructuredResult(
                ReviewResponse(
                    reviewed_target_ids=[
                        target["id"] for target in json.loads(user)["targets"]
                    ]
                ),
                1,
                100,
                10,
            )

    monkeypatch.setattr("translate.tasks.41_review.LLMClient", Client)
    span = TextSpan(id="span", source="A sentence. " * 334, translated="訳" * 800)
    target = ReviewTarget(
        id="target",
        source=span.source,
        translation=span.text(),
        target_ids=["unit"],
        spans=[span],
    )
    result = run_review(
        [target],
        tmp_path / "review",
        tmp_path,
        Config(
            openai_base_url="http://llm",
            openai_review_model="model",
            review_input_tokens=8192,
        ),
        "r" * 2783,
        "",
    )

    assert result.findings == []
    assert result.revisions == []
    assert result.reviewed_target_ids == [target.id]
    assert len(list((tmp_path / "review/calls").glob("*/response.json"))) > 1


def test_review_discards_identical_model_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """同一候補を除き、入力中の別名だけを安全にTextUnit IDへ直す。"""

    finding = ReviewFinding(
        category="accuracy",
        severity="error",
        target_ids=["target"],
        message="誤訳",
    )
    revision = ReviewRevision(
        target_id="span",
        edits=[ReviewTextEdit(span_id="span", text="正しい訳")],
    )

    class Client:
        def __init__(self, config: Config) -> None:
            """共通要求が参照する設定を保持する。"""
            self.config = config
            self.client = MagicMock()

        def structured(self, **_values: object) -> StructuredResult[ReviewResponse]:
            """重複と異なる指摘・修正候補を返す。"""

            return StructuredResult(
                ReviewResponse(
                    reviewed_target_ids=["target", "other-target"],
                    findings=[
                        finding,
                        finding,
                        finding.model_copy(update={"message": "用語違い"}),
                    ],
                    revisions=[
                        revision,
                        revision,
                        revision.model_copy(
                            update={
                                "target_id": "target",
                                "edits": [
                                    ReviewTextEdit(span_id="span", text="別の訳")
                                ],
                            }
                        ),
                        ReviewRevision(
                            target_id="other-target",
                            edits=[ReviewTextEdit(span_id="span", text="誤った対象")],
                        ),
                    ],
                ),
                1,
                100,
                10,
            )

    monkeypatch.setattr("translate.tasks.41_review.LLMClient", Client)
    target = ReviewTarget(
        id="target",
        source="source",
        translation="訳",
        target_ids=["unit"],
        spans=[TextSpan(id="span", source="source", translated="訳")],
    )
    other = ReviewTarget(
        id="other-target",
        source="other",
        translation="別訳",
        target_ids=["other-unit"],
        spans=[TextSpan(id="other-span", source="other", translated="別訳")],
    )
    result = run_review(
        [target, other],
        tmp_path / "review",
        tmp_path,
        Config(openai_base_url="http://llm", openai_review_model="model"),
        "",
        "",
    )

    assert [item.message for item in result.findings] == ["誤訳", "用語違い"]
    assert [item.target_ids for item in result.findings] == [["unit"], ["unit"]]
    assert [item.edits[0].text for item in result.revisions] == [
        "正しい訳",
        "別の訳",
        "誤った対象",
    ]
    assert [item.target_id for item in result.revisions] == [
        "unit",
        "unit",
        "other-target",
    ]


def test_review_drops_optional_context_to_fit_target() -> None:
    """対象を削らず、RAG・用語集・既知指摘を必要時だけ省く。"""

    target = ReviewTarget(
        id="target",
        source="source",
        translation="訳",
        target_ids=["unit"],
        spans=[TextSpan(id="span", source="source", translated="訳")],
    )
    base = review_user_payload([target], [], "", [], 8192)
    payload = review_user_payload(
        [target],
        [{"message": "finding" * 100}],
        "term,訳語\n" * 100,
        [{"text": "reference" * 100}],
        len(base.encode("utf-8")),
    )

    assert json.loads(payload) == json.loads(base)


def test_review_retries_one_oversized_pre_split_target(tmp_path: Path) -> None:
    """単一対象の入力超過もさらに分割し、親Callを失敗で終わらせない。"""

    class SizeLimitedClient:
        config = Config(openai_base_url="http://llm", openai_review_model="review")

        def structured(self, **values: object) -> StructuredResult[ReviewResponse]:
            """3,000 bytesを超す入力だけprovider上限超過として拒否する。"""

            user = values["user"]
            assert isinstance(user, str)
            if len(user.encode("utf-8")) > 3000:
                message = "provider context limit"
                raise LLMInputExceededError(message)
            return StructuredResult(
                response=ReviewResponse(
                    reviewed_target_ids=[
                        target["id"] for target in json.loads(user)["targets"]
                    ]
                ),
                attempts=1,
                input_tokens=100,
                output_tokens=10,
            )

    spans = [
        TextSpan(
            id=f"span-{index}",
            source="English sentence. " * 50,
            translated="訳" * 300,
        )
        for index in range(4)
    ]
    target = ReviewTarget(
        id="target/part-0001",
        source="".join(span.source for span in spans),
        translation="".join(span.text() for span in spans),
        target_ids=["unit"],
        spans=spans,
    )

    responses = execute_review(
        client=SizeLimitedClient(),  # type: ignore[arg-type]
        config=Config(
            openai_base_url="http://localhost",
            openai_review_model="review",
            review_input_tokens=8192,
        ),
        targets=[target],
        task_directory=tmp_path,
        rules="",
        glossary="",
        lineage=["chunk-0000"],
        depth=0,
    )

    artifacts = [
        json.loads(path.read_text()) for path in tmp_path.glob("calls/*/call.json")
    ]
    statuses = [artifact["status"] for artifact in artifacts]
    assert "split" in statuses
    assert "failed" not in statuses
    assert len(responses) > 1
    assert all(
        response.reviewed_target_ids == [part.id for part in parts]
        for _, response, parts in responses
    )


@pytest.mark.parametrize("prefix", ["1 ", "10 ", "123 ", "1. ", "1.2 ", "1.2.3 "])
def test_heading_number_is_removed_only_when_publishing(prefix: str) -> None:
    """分割Spanの番号だけをMarkdownで除き、原文・書式・本文の数字を保つ。"""
    unit = TextUnit(
        id="heading/content",
        spans=[
            TextSpan(id="first", source=prefix[:2]),
            TextSpan(id="second", source=prefix[2:] + "Title", marks=["strong"]),
        ],
    )
    heading = Block(id="heading", order=0, kind="heading", level=2, content=unit)
    before = heading.model_dump()
    output = convert_block(heading, 30)
    assert output == "## **Title** {#heading}"
    assert heading.model_dump() == before
    paragraph = heading.model_copy(update={"kind": "paragraph"})
    assert convert_block(paragraph, 30) != "**Title**"


def test_heading_year_without_section_punctuation_is_preserved() -> None:
    """節番号の形式に合わない年度を見出し本文から除かない。"""
    heading = Block(
        id="heading",
        order=0,
        kind="heading",
        level=1,
        content=_unit("content", "2026 Outlook"),
    )
    assert "2026 Outlook" in convert_block(heading, 30)


def test_load_expands_merged_table_into_empty_grid_cells() -> None:
    """結合セル本文を起点だけに保存し、被覆セルは空Spanで保持する。"""
    item = {
        "data": {
            "num_rows": 2,
            "num_cols": 2,
            "table_cells": [
                {
                    "start_row_offset_idx": 0,
                    "start_col_offset_idx": 0,
                    "end_row_offset_idx": 2,
                    "end_col_offset_idx": 2,
                    "row_span": 2,
                    "col_span": 2,
                    "text": "Merged",
                }
            ],
        }
    }
    cells = [source.cell for source in _normalized_cells(item, "#/tables/0")]
    assert len(cells) == 4
    assert cells[0].content.text() == "Merged"
    assert all(cell.content.spans == [] for cell in cells[1:])
    assert all(
        "rowspan" not in cell.model_dump() and "colspan" not in cell.model_dump()
        for cell in cells
    )


@pytest.mark.parametrize("reviewed_ids", [[], ["unit"]])
def test_review_retries_coverage_error_before_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reviewed_ids: list[str]
) -> None:
    """確認済みIDの不一致も同じCall内で一度再要求し、正しい結果だけ成功保存する。"""
    config = Config(
        openai_base_url="http://llm",
        openai_review_model="review",
        openai_llm_base_url=None,
        qdrant_uri=None,
        openai_embedding_model=None,
    )
    client = LLMClient(config)
    target = ReviewTarget(
        id="translate/unit",
        source="Original",
        translation="訳",
        target_ids=["unit"],
        spans=[TextSpan(id="unit/span", source="Original", translated="訳")],
    )
    invalid = MagicMock()
    invalid.choices = [MagicMock(finish_reason="stop")]
    invalid.choices[0].message.content = ReviewResponse(
        reviewed_target_ids=reviewed_ids
    ).model_dump_json()
    invalid.usage = None
    valid = MagicMock()
    valid.choices = [MagicMock(finish_reason="stop")]
    valid.choices[0].message.content = ReviewResponse(
        reviewed_target_ids=[target.id]
    ).model_dump_json()
    valid.usage = None
    create = MagicMock(side_effect=[invalid, valid])
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    monkeypatch.setattr("translate.adapters.llm.time.sleep", MagicMock())
    try:
        responses = execute_review(
            client=client,
            config=config,
            targets=[target],
            task_directory=tmp_path,
            rules="",
            glossary="",
            lineage=[],
            depth=0,
        )
        assert create.call_count == 2
        assert responses[0][1].reviewed_target_ids == [target.id]
        call = json.loads(
            next(tmp_path.glob("calls/*/call.json")).read_text(encoding="utf-8")
        )
        assert call["status"] == "succeeded"
        assert call["attempts"] == 2
        assert "confirm every requested target" in str(create.call_args_list[1])
    finally:
        client.client.close()


def test_review_trims_rag_using_complete_native_prompt_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """単一の短い対象でもSchema込みで上限を守り、参考文だけを減らして評価する。"""
    config = Config(
        openai_base_url="http://llm",
        openai_llm_base_url=None,
        openai_review_model="review",
        llm_structured_output_mode="json_schema",
        review_input_tokens=11264,
        qdrant_uri="http://qdrant",
        qdrant_collection="test",
        openai_embedding_model="embed",
    )
    client = LLMClient(config)
    target = ReviewTarget(
        id="translate/unit",
        source="Original sentence.",
        translation="訳文。",
        target_ids=["unit"],
        spans=[TextSpan(id="span", source="Original sentence.", translated="訳文。")],
    )
    monkeypatch.setattr("translate.tasks.embed", MagicMock(return_value=[[1.0]]))
    monkeypatch.setattr(
        "translate.tasks.search",
        MagicMock(
            return_value=[{"text": "reference " * 140, "id": i} for i in range(5)]
        ),
    )
    completion = MagicMock()
    completion.choices = [MagicMock(finish_reason="stop")]
    completion.choices[0].message.content = ReviewResponse(
        reviewed_target_ids=[target.id]
    ).model_dump_json()
    completion.usage = None
    create = MagicMock(return_value=completion)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        result = execute_review(
            client=client,
            config=config,
            targets=[target],
            task_directory=tmp_path,
            rules="r" * 2800,
            glossary="",
            lineage=[],
            depth=0,
        )
        assert result[0][1].reviewed_target_ids == [target.id]
        create.assert_called_once()
        sent = json.loads(create.call_args.kwargs["messages"][1]["content"])
        assert 0 < len(sent["references"]) < 5
        assert sent["targets"][0]["source"] == target.source
        assert sent["targets"][0]["spans"][0]["text"] == target.translation
    finally:
        client.client.close()
