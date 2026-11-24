"""実際のAgent制御・保存・再開を、外部LLM応答だけ差し替えて検証する。"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from tests import successful_review
from translate.adapters.artifact_store import llm_call_id, write_model
from translate.adapters.llm import (
    LLMClient,
    LLMInputExceededError,
    LLMInvalidResponseError,
    LLMOutputTokenExceededError,
    StructuredResult,
)
from translate.common.config import Config
from translate.models.artifacts import LLMCallArtifact
from translate.models.document import (
    Block,
    Document,
    Page,
    TableCell,
    TextSpan,
    TextUnit,
)
from translate.models.review import (
    AlignmentResponse,
    ReviewResponse,
    ReviewTarget,
)
from translate.models.upgrade import DiffResponse
from translate.pipeline import (
    agent_deadline,
    agent_units,
    completed_agent_calls,
    narrowed,
    positional_candidates,
)
from translate.pipeline.review import ReviewAgent, _copied_translation_front_page_ids
from translate.pipeline.upgrade import UpgradeAgent
from translate.tasks import MATCHING_VERSION

_identical_changes = UpgradeAgent._identical_changes  # noqa: SLF001


def test_completed_agent_calls_filters_out_legacy_matching_calls(
    tmp_path: Path,
) -> None:
    """照合規則変更前の成功Callは再開時に再適用しない。"""
    now = datetime.now(UTC)
    for call_id, version in [("legacy", None), ("current", MATCHING_VERSION)]:
        write_model(
            tmp_path / "calls" / call_id / "call.json",
            LLMCallArtifact(
                call_id=call_id,
                task="REVIEW",
                operation="match",
                matching_version=version,
                status="succeeded",
                fingerprint="0" * 64,
                target_ids=["source:en", "translation:ja"],
                attempts=1,
                started_at=now,
                updated_at=now,
            ),
        )

    assert [
        call.call_id
        for call in completed_agent_calls(tmp_path, matching_version=MATCHING_VERSION)
    ] == ["current"]


def test_llm_call_id_changes_with_matching_version() -> None:
    """照合世代を変えると保存Callの再利用先も分離する。"""
    assert llm_call_id("REVIEW", ["source:en"], []) != llm_call_id(
        "REVIEW", ["source:en"], [], matching_version=5
    )


@pytest.fixture(autouse=True)
def agent_loop_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一本文の文書でもAgentの操作を検証できるよう事前照合を外す。"""
    monkeypatch.setattr(UpgradeAgent, "_identical_changes", lambda _self: [])


def document(**units: str) -> Document:
    """IDと本文を保持する小さな比較用文書を作る。"""
    return Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id=f"block-{key}",
                        order=index,
                        kind="paragraph",
                        content=TextUnit(
                            id=key, spans=[TextSpan(id=f"{key}/span", source=text)]
                        ),
                    )
                    for index, (key, text) in enumerate(units.items())
                ],
            )
        ]
    )


def test_agent_context_distinguishes_repeated_table_values() -> None:
    """同じ数値でも行の識別子と列見出しを渡し、PDF内の表番号に依存しない。"""
    doc = document(section="Measurements", formula="x = y")
    doc.pages[0].blocks[0].kind = "heading"
    doc.pages[0].blocks[1].kind = "formula"
    doc.pages.append(
        Page(
            number=2,
            blocks=[
                Block(
                    id="unrelated-table-number",
                    order=0,
                    kind="table",
                    cells=[
                        TableCell(
                            id=key,
                            row=row,
                            column=column,
                            header=header,
                            content=TextUnit(
                                id=key, spans=[TextSpan(id=f"{key}/span", source=text)]
                            ),
                        )
                        for key, row, column, header, text in [
                            ("label-header", 0, 0, True, "Record"),
                            ("value-header", 0, 1, True, "Count"),
                            ("row-5", 1, 0, False, "page_split_05"),
                            ("value-5", 1, 1, False, "5"),
                            ("row-7", 2, 0, False, "page_split_07"),
                            ("value-7", 2, 1, False, "5"),
                        ]
                    ],
                )
            ],
        )
    )
    contexts = doc.unit_contexts()
    assert contexts["formula"] == {
        "section": "Measurements",
        "kind": "formula",
        "position": "0.0",
    }
    assert contexts["value-5"] == {
        "kind": "table_cell",
        "section": "Measurements",
        "position": "1.0",
        "row_label": "page_split_05",
        "column_label": "Count",
        "adjacent_row_labels": "next: page_split_07",
    }
    assert contexts["value-7"]["row_label"] == "page_split_07"
    assert contexts["value-7"]["adjacent_row_labels"] == "previous: page_split_05"
    assert contexts["row-7"]["column_label"] == "Record"
    assert contexts["formula"]["position"] == "0.0"
    assert contexts["value-5"]["position"] == "1.0"


def test_agent_context_normalizes_page_position_for_candidate_ranking() -> None:
    """PDFのページ位置を0から1の候補順位補助情報として保持する。"""
    doc = Document(
        pages=[
            Page(
                number=number,
                blocks=[
                    Block(
                        id=f"heading-{number}",
                        order=0,
                        kind="heading",
                        content=TextUnit(
                            id=f"heading-{number}",
                            spans=[
                                TextSpan(id=f"heading-{number}/span", source="Heading")
                            ],
                        ),
                    )
                ],
            )
            for number in (1, 62, 100)
        ]
    )

    contexts = doc.unit_contexts()

    assert contexts["heading-1"]["position"] == "0.0"
    assert contexts["heading-62"]["position"] == "0.6161616161616161"
    assert contexts["heading-100"]["position"] == "1.0"


def test_agent_context_ignores_decorative_table_markers() -> None:
    """目次の箇条書き記号を行見出しとして使わず、隣の説明文を使う。"""
    doc = document()
    doc.pages[0].blocks.append(
        Block(
            id="table-of-contents",
            order=0,
            kind="table",
            cells=[
                TableCell(
                    id=identifier,
                    row=1,
                    column=column,
                    content=TextUnit(
                        id=identifier,
                        spans=[TextSpan(id=f"{identifier}/span", source=text)],
                    ),
                )
                for identifier, column, text in [
                    ("bullet", 0, "•"),
                    ("title", 1, "Planning Teams"),
                    ("page-number", 2, "III-1"),
                ]
            ],
        )
    )

    assert doc.unit_contexts()["page-number"]["row_label"] == "Planning Teams"


@pytest.mark.parametrize("task_name", ["REVIEW", "DIFF"])
def test_comparison_sends_context_separately_from_content(
    task_name: str, config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じ本文を持つ別行の区別を、ReviewとUpgradeの実LLM境界まで保持する。"""
    roles = (
        ("source", "translation")
        if task_name == "REVIEW"
        else ("source_v1", "source_v2", "translation_v1")
    )
    units = {
        role: [TextUnit(id=role, spans=[TextSpan(id=f"{role}/span", source="5")])]
        for role in roles
    }
    contexts = {
        role: {
            role: {
                "kind": "table_cell",
                "row_label": "Record 07",
                "column_label": "Count",
                "adjacent_row_labels": "previous: Record 06 | next: Record 08",
                "position": "0.0",
            }
        }
        for role in roles
    }
    if task_name == "REVIEW":
        response = AlignmentResponse.model_validate(
            {
                "groups": [
                    {
                        "source_ids": ["a1"],
                        "translation_ids": ["b1"],
                        "kind": "matched",
                    }
                ]
            }
        )
    else:
        response = DiffResponse.model_validate(
            {
                "changes": [
                    {
                        "kind": "unchanged",
                        "source_v1_ids": ["a1"],
                        "source_v2_ids": ["b1"],
                        "translation_v1_ids": ["c1"],
                        "summary": "Same record and value.",
                    }
                ],
                "reviewed_source_v1_ids": ["a1"],
                "reviewed_source_v2_ids": ["b1"],
            }
        )
    calls = scripted(monkeypatch, [response])
    client = LLMClient(config)
    try:
        if task_name == "REVIEW":
            import_module("translate.tasks.41_review").ReviewTask(
                config, tmp_path, "", "", contexts=contexts
            ).match_documents(units, client, 0)
        else:
            import_module("translate.tasks.21_diff").DiffTask(
                client, tmp_path, "", "", contexts=contexts
            ).run(units, "match", 0)
    finally:
        client.client.close()
    payload = json.loads(calls[0]["user"])
    for prefix, role in zip("abc", roles, strict=False):
        assert payload[role] == [
            {
                "id": f"{prefix}1",
                "text": "5",
                "context": {
                    key: value
                    for key, value in contexts[role][role].items()
                    if key != "position"
                },
            }
        ]
    if task_name == "REVIEW":
        assert response.groups[0].source_ids == ["source"]
        assert response.groups[0].translation_ids == ["translation"]
    else:
        assert response.changes[0].source_v1_ids == ["source_v1"]
        assert response.reviewed_source_v2_ids == ["source_v2"]


def test_quality_review_receives_context_and_invalidates_stale_response(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """品質確認にも項目の役割を渡し、構造文脈が異なる保存済み応答を再利用しない。"""
    calls = scripted(
        monkeypatch,
        [successful_review("review/current"), successful_review("review/current")],
    )
    context = {
        "translation": {
            "ja": {
                "kind": "table_cell",
                "row_label": "Author",
                "position": "0.0",
            }
        }
    }
    task = import_module("translate.tasks.41_review").ReviewTask(
        config, tmp_path, "", "", contexts=context
    )
    target = ReviewTarget(
        id="review/current",
        source="Engineering Documentation Team",
        translation="Engineering Documentation Team",
        target_ids=["ja"],
        spans=[TextSpan(id="span", source="Engineering Documentation Team")],
    )
    client = LLMClient(config)
    try:
        task.run([target], tmp_path, client=client)
        context["translation"]["ja"]["row_label"] = "Reviewer"
        task.run([target], tmp_path, client=client)
    finally:
        client.client.close()
    assert len(calls) == 2
    assert json.loads(calls[0]["user"])["targets"][0]["context"] == [
        {"kind": "table_cell", "row_label": "Author"}
    ]
    assert json.loads(calls[1]["user"])["targets"][0]["context"] == [
        {"kind": "table_cell", "row_label": "Reviewer"}
    ]


@pytest.mark.parametrize(
    "case",
    [
        ("Date", "2026/08/20", "2026/0820", False),
        ("Date", "2026/08/20", "2026/08/21", True),
        ("Version", "2026/08/20", "2026/0820", True),
        ("Date", "2026/02/28", "2026/02/29", True),
    ],
)
def test_review_distinguishes_date_format_from_changed_values(
    case: tuple[str, str, str, bool],
    tmp_path: Path,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同じ暦日の区切り差を誤検知せず、日付の値や識別子の変更は検証対象にする。"""
    label, source, current, has_issue = case
    payloads = [
        {
            "assessments": [
                {
                    "target_id": "1",
                    "reason": "日付が異なります。",
                    "verdict": "issue",
                    "edits": [{"span_id": "s1", "text": source}],
                    "category": "accuracy",
                    "severity": "error",
                }
            ]
        },
        {
            "assessments": [
                {
                    "target_id": "1",
                    "reason": "同じ日付です。",
                    "verdict": "correct",
                    "edits": [],
                    "category": None,
                    "severity": None,
                }
            ]
        },
    ]
    responses = []
    for payload in payloads:
        response = MagicMock()
        response.choices = [MagicMock(finish_reason="stop")]
        response.choices[0].message.content = json.dumps(payload)
        response.usage = None
        responses.append(response)
    client = LLMClient(config)
    create = MagicMock(side_effect=responses)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    target = ReviewTarget(
        id="review/date",
        source=source,
        translation=current,
        target_ids=["date"],
        spans=[TextSpan(id="span", source=current)],
    )
    task = import_module("translate.tasks.41_review").ReviewTask(
        config,
        tmp_path,
        "",
        "",
        contexts={"translation": {"date": {"row_label": label, "kind": "table_cell"}}},
    )
    try:
        result = task.run([target], tmp_path, client=client)
    finally:
        client.client.close()
    assert bool(result.findings) is has_issue
    assert create.call_count == 1


@pytest.mark.parametrize(
    "case",
    [
        ("Timeout こ のセルの説明。", "Timeout このセルの説明。", False),
        ("件数:9。", "件数:7。", True),
        ("now here", "nowhere", True),
        ("now\nhere", "nowhere", True),
    ],
)
def test_review_rejects_only_extraction_space_revisions(
    case: tuple[str, str, bool],
    tmp_path: Path,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """抽出空白だけの修正は再要求せず不備なしとし、数値や英単語の区切りの修正は残す。"""
    current, replacement, has_issue = case
    issue = {
        "assessments": [
            {
                "target_id": "1",
                "reason": "修正が必要です。",
                "verdict": "issue",
                "edits": [{"span_id": "s1", "text": replacement}],
                "category": "accuracy",
                "severity": "error",
            }
        ],
    }
    correct = successful_review("1").model_dump()
    responses = []
    for payload in [issue, correct]:
        response = MagicMock()
        response.choices = [MagicMock(finish_reason="stop")]
        response.choices[0].message.content = json.dumps(payload)
        response.usage = None
        responses.append(response)
    client = LLMClient(config)
    create = MagicMock(side_effect=responses)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    target = ReviewTarget(
        id="review/current",
        source="Original.",
        translation=current,
        target_ids=["ja"],
        spans=[TextSpan(id="span", source=current)],
    )
    task = import_module("translate.tasks.41_review").ReviewTask(
        config, tmp_path, "", ""
    )
    try:
        result = task.run([target], tmp_path, client=client)
    finally:
        client.client.close()
    assert bool(result.findings) is has_issue
    assert create.call_count == 1
    assert json.loads(create.call_args_list[0].kwargs["messages"][1]["content"])[
        "targets"
    ][0]["translation"] == [{"span_id": "s1", "text": current}]


def test_review_ignores_matching_table_dot_leaders(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一致する表内ドットリーダーへの誤指摘を除外する。"""
    response = ReviewResponse.model_validate(
        {
            "assessments": [
                {
                    "target_id": "row",
                    "reason": "ドットは不要です。",
                    "verdict": "issue",
                    "category": "style",
                    "severity": "info",
                    "edits": [{"span_id": "span", "text": "Nuclear Waste Disposal"}],
                }
            ]
        }
    )
    calls = scripted(monkeypatch, [response])
    current = (
        "Nuclear Waste Disposal ....................................................."
    )
    target = ReviewTarget(
        id="row",
        source=current,
        translation=current,
        target_ids=["cell"],
        spans=[TextSpan(id="span", source=current)],
    )
    task = import_module("translate.tasks.41_review").ReviewTask(
        config,
        tmp_path,
        "",
        "",
        contexts={"translation": {"cell": {"kind": "table_cell"}}},
    )
    client = LLMClient(config)
    try:
        result = task.run([target], tmp_path, client=client)
    finally:
        client.client.close()

    assert not result.findings
    assert len(calls) == 1


@pytest.fixture
def config() -> Config:
    """実サービスへ接続せず、RAGを明示的に無効にする設定。"""
    return Config(
        openai_base_url="http://127.0.0.1:1/v1",
        openai_llm_base_url=None,
        openai_review_model="test",
        openai_embedding_model=None,
        qdrant_uri=None,
        qdrant_collection=None,
    )


@pytest.mark.parametrize("operation", ["evaluate", "recheck"])
@pytest.mark.parametrize("prefix", ["review/alignment-", "translate/unit-"])
def test_review_schema_keeps_confirmation_ids_distinct_from_unit_ids(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: str,
    prefix: str,
) -> None:
    """実HTTP要求のSchemaが確認対象IDだけを許し、訳文要素IDとの混同を防ぐ。"""
    client = LLMClient(
        config.model_copy(update={"llm_structured_output_mode": "json_schema"})
    )
    targets = [
        ReviewTarget(
            id=f"{prefix}{index:06}",
            source="Document ID",
            translation="文書ID",
            target_ids=[f"unit-{index}"],
            spans=[TextSpan(id=f"span-{index}", source="文書ID")],
        )
        for index in (1, 2)
    ]
    expected = [target.id for target in targets]
    response = MagicMock()
    response.choices = [MagicMock(finish_reason="stop")]
    response.choices[0].message.content = json.dumps(
        {
            "assessments": [
                {
                    "target_id": str(index),
                    "reason": "適切な訳文",
                    "verdict": "correct",
                    "edits": [],
                    "category": None,
                    "severity": None,
                }
                for index, _ in enumerate(expected, 1)
            ]
        }
    )
    response.usage = None
    create = MagicMock(return_value=response)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        result = (
            import_module("translate.tasks.41_review")
            .ReviewTask(config, tmp_path / "review", "", "")
            .run(
                targets,
                tmp_path,
                client=client,
                operation=operation,
                span_owners={f"span-{index}": f"unit-{index}" for index in (1, 2)},
            )
        )
        schema = create.call_args.kwargs["response_format"]["json_schema"]["schema"]
        field = schema["properties"]["assessments"]
        assert schema["$defs"]["ReviewAssessment"]["properties"]["target_id"][
            "enum"
        ] == [str(index) for index in range(1, len(expected) + 1)]
        assert field["minItems"] == field["maxItems"] == len(expected)
        assert result.reviewed_target_ids == expected
    finally:
        client.client.close()


@pytest.mark.parametrize(
    "groups",
    [
        [{"source_ids": ["en"], "translation_ids": ["ja"], "kind": "matched"}],
        [
            {
                "source_ids": ["en"],
                "translation_ids": [],
                "kind": "source_only",
                "reason": "対応する訳文がない",
            },
            {
                "source_ids": [],
                "translation_ids": ["ja"],
                "kind": "translation_only",
                "reason": "対応する原文がない",
            },
        ],
    ],
)
def test_match_schema_requests_only_correspondence(
    tmp_path: Path,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    groups: list[dict[str, object]],
) -> None:
    """対応付け要求に品質評価欄を混在させず、実SDK境界で対応関係だけを受け取る。"""
    client = LLMClient(
        config.model_copy(update={"llm_structured_output_mode": "json_schema"})
    )
    response = MagicMock()
    response.choices = [MagicMock(finish_reason="stop")]
    response.choices[0].message.content = json.dumps(
        {
            "groups": [
                {
                    **group,
                    "source_ids": ["a1"] if group["source_ids"] else [],
                    "translation_ids": ["b1"] if group["translation_ids"] else [],
                }
                for group in groups
            ]
        }
    )
    response.usage = None
    create = MagicMock(return_value=response)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        units = agent_units(
            {
                "source": document(en="Original."),
                "translation": document(ja="訳文。"),
            }
        )
        _, result = (
            import_module("translate.tasks.41_review")
            .ReviewTask(client.config, tmp_path, "Compare document meanings.", "")
            .match_documents(
                {role: list(values.values()) for role, values in units.items()},
                client,
                0,
            )
        )
        schema = create.call_args.kwargs["response_format"]["json_schema"]["schema"]
        assert set(schema["properties"]) == {"groups"}
        candidate = schema["$defs"]["AlignmentCandidate"]
        assert list(candidate["properties"]) == [
            "reason",
            "kind",
            "source_ids",
            "translation_ids",
        ]
        assert set(candidate["required"]) == set(candidate["properties"])
        assert candidate["properties"]["reason"] == {"type": "string", "minLength": 1}
        assert candidate["properties"]["source_ids"]["items"]["enum"] == ["a1"]
        assert candidate["properties"]["translation_ids"]["items"]["enum"] == ["b1"]
        assert [key for group in result.groups for key in group.translation_ids] == [
            "ja"
        ]
        create.assert_called_once()
    finally:
        client.client.close()


@pytest.mark.parametrize("paired_count", [0, 1, 2])
def test_match_restores_original_ids_once_and_reuses_them(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch, paired_count: int
) -> None:
    """短縮IDが元IDと衝突しても再開時の参照を保ち、省略候補を未確認として残す。"""
    client = LLMClient(config)
    response = MagicMock()
    response.choices = [MagicMock(finish_reason="stop")]
    response.choices[0].message.content = json.dumps(
        {
            "groups": [
                {
                    "source_ids": [f"a{i}"],
                    "translation_ids": [f"b{i}"],
                    "kind": "matched",
                    "reason": "Same content.",
                }
                for i in range(1, paired_count + 1)
            ]
        }
    )
    response.usage = None
    create = MagicMock(return_value=response)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    units = {
        role: list(doc.unit_index().values())
        for role, doc in {
            "source": document(a2="First.", a1="Second."),
            "translation": document(b2="一つ目。", b1="二つ目。"),
        }.items()
    }
    task = import_module("translate.tasks.41_review").ReviewTask(
        config, tmp_path, "", ""
    )
    try:
        _, first = task.match_documents(units, client, 0)
        _, replay = task.match_documents(units, client, 0)
        assert first == replay
        assert [
            (group.source_ids, group.translation_ids)
            for group in first.groups
            if group.kind == "matched"
        ] == [(["a2"], ["b2"]), (["a1"], ["b1"])][:paired_count]
        assert sorted(key for group in first.groups for key in group.source_ids) == [
            "a1",
            "a2",
        ]
        assert sorted(
            key for group in first.groups for key in group.translation_ids
        ) == ["b1", "b2"]
        assert all(
            "文書全体に相手がないことは意味しません" in group.reason
            for group in first.groups
            if group.kind != "matched"
        )
        create.assert_called_once()
    finally:
        client.client.close()


@pytest.mark.parametrize(("output_tokens", "unit_chars"), [(4096, 4000), (17920, 8000)])
def test_match_keeps_large_pair_within_review_input_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    output_tokens: int,
    unit_chars: int,
) -> None:
    """品質評価用の長い規則で対応付けの原文・訳文ペアを予算超過させない。"""
    rules = (
        Path(__file__).parents[2] / "translate/templates/review-rules.md"
    ).read_text(encoding="utf-8")
    calls = scripted(
        monkeypatch,
        [
            AlignmentResponse.model_validate(
                {
                    "groups": [
                        {
                            "source_ids": ["en"],
                            "translation_ids": ["ja"],
                            "kind": "matched",
                        }
                    ]
                }
            )
        ],
    )
    client = LLMClient(
        config.model_copy(
            update={"review_input_tokens": 11264, "review_output_tokens": output_tokens}
        )
    )
    try:
        units = agent_units(
            {
                "source": document(en="a" * unit_chars),
                "translation": document(ja="b" * unit_chars),
            }
        )
        _, result = (
            import_module("translate.tasks.41_review")
            .ReviewTask(client.config, tmp_path, rules, "")
            .match_documents(
                {role: list(values.values()) for role, values in units.items()},
                client,
                0,
            )
        )
        assert result.groups[0].kind == "matched"
        assert calls[0]["output_tokens"] == min(output_tokens, 8192)
        assert calls[0]["input_tokens"] == 11264 + output_tokens - min(
            output_tokens, 8192
        )
    finally:
        client.client.close()


@pytest.mark.parametrize("invalid_kind", ["matched", "missing_reason", "empty"])
def test_match_rejects_inconsistent_groups_before_saving(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch, invalid_kind: str
) -> None:
    """Schemaを簡素化しても、片側だけのmatched・理由なし・空groupを拒否する。"""
    groups = [
        {
            "source_ids": ["en"],
            "translation_ids": [],
            "kind": "source_only",
            "reason": "相手なし",
        },
        {
            "source_ids": [],
            "translation_ids": ["ja"],
            "kind": "translation_only",
            "reason": "相手なし",
        },
    ]
    if invalid_kind == "matched":
        groups[0]["kind"] = "matched"
    elif invalid_kind == "missing_reason":
        groups[0]["reason"] = ""
    else:
        groups.append(
            {
                "source_ids": [],
                "translation_ids": [],
                "kind": "source_only",
                "reason": "空",
            }
        )
    client = LLMClient(config)
    response = MagicMock()
    response.choices = [MagicMock(finish_reason="stop")]
    response.choices[0].message.content = json.dumps({"groups": groups})
    response.usage = None
    create = MagicMock(return_value=response)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        units = agent_units(
            {"source": document(en="Source"), "translation": document(ja="訳文")}
        )
        with pytest.raises(LLMInvalidResponseError):
            import_module("translate.tasks.41_review").ReviewTask(
                config, tmp_path, "Compare.", ""
            ).match_documents(
                {role: list(values.values()) for role, values in units.items()},
                client,
                0,
            )
        assert create.call_count == config.llm_retry_attempts
        assert not list(tmp_path.glob("calls/*/response.json"))
    finally:
        client.client.close()


def test_match_retry_identifies_duplicate_and_unknown_ids(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """対応付けの再試行で、訳文側の重複・範囲外IDを具体的に伝える。"""
    client = LLMClient(config)
    invalid = {
        "groups": [
            {"source_ids": ["en1"], "translation_ids": ["ja1"], "kind": "matched"},
            {
                "source_ids": ["en2"],
                "translation_ids": ["ja1", "unknown"],
                "kind": "matched",
            },
        ]
    }
    valid = {
        "groups": [
            {"source_ids": ["en1"], "translation_ids": ["ja1"], "kind": "matched"},
            {"source_ids": ["en2"], "translation_ids": ["ja2"], "kind": "matched"},
        ]
    }
    responses = []
    for payload in (invalid, valid):
        response = MagicMock()
        response.choices = [MagicMock(finish_reason="stop")]
        response.choices[0].message.content = json.dumps(payload)
        response.usage = None
        responses.append(response)
    create = MagicMock(side_effect=responses)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        units = agent_units(
            {
                "source": document(en1="First", en2="Second"),
                "translation": document(ja1="一つ目", ja2="二つ目"),
            }
        )
        _, result = (
            import_module("translate.tasks.41_review")
            .ReviewTask(config, tmp_path, "Compare meanings.", "")
            .match_documents(
                {role: list(values.values()) for role, values in units.items()},
                client,
                0,
            )
        )
        feedback = create.call_args.kwargs["messages"][-1]["content"]
        assert "translation: duplicate=['ja1']" in feedback
        assert "duplicate=['ja1']" in feedback
        assert "unknown=['unknown']" in feedback
        assert (
            result.model_dump() == AlignmentResponse.model_validate(valid).model_dump()
        )
        assert create.call_count == 2
    finally:
        client.client.close()


def test_match_prompt_assigns_partial_correspondence_for_later_evaluation(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """訳抜けを含む部分対応もmatchedに残し、品質評価へ渡す契約を維持する。"""
    calls = scripted(
        monkeypatch,
        [
            AlignmentResponse(
                groups=[
                    {
                        "source_ids": ["first", "continuation"],
                        "translation_ids": ["translated"],
                        "kind": "matched",
                        "reason": "The translation starts the same continuing passage.",
                    }
                ]
            )
        ],
    )
    client = LLMClient(config)
    units = {
        "source": list(
            document(
                first="Agreement should cover standard data",
                continuation="bases and formats that the translation omits.",
            )
            .unit_index()
            .values()
        ),
        "translation": list(
            document(translated="合意には標準データを含める。").unit_index().values()
        ),
    }
    try:
        _, response = (
            import_module("translate.tasks.41_review")
            .ReviewTask(config, tmp_path, "", "")
            .match_documents(units, client, 0)
        )
    finally:
        client.client.close()

    assert response.groups[0].source_ids == ["first", "continuation"]
    assert "include each ID whose" in calls[0]["contract"]
    assert "Do not require full text coverage" in calls[0]["contract"]
    assert "do not stop after the first matching sentence" in calls[0]["contract"]


def scripted(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[BaseModel | Callable[[dict[str, object]], BaseModel]],
) -> list[dict[str, object]]:
    """判断と操作のLLM応答を注入し、呼出し内容を検査できるようにする。"""
    calls: list[dict[str, object]] = []

    def structured(_self: LLMClient, **kwargs: object) -> StructuredResult:
        """予定した応答型と操作順が一致する要求にだけ応答する。"""
        calls.append(kwargs)
        assert responses, f"Unexpected LLM call: {kwargs['response_type']}"
        response = responses.pop(0)
        if callable(response):
            response = response(kwargs)
        assert isinstance(response, kwargs["response_type"])
        return StructuredResult(response, 1, 100, 100)

    monkeypatch.setattr(LLMClient, "structured", structured)
    return calls


def matched() -> AlignmentResponse:
    """一対多の対応付け応答を返す。"""
    return AlignmentResponse.model_validate(
        {
            "groups": [
                {
                    "source_ids": ["en"],
                    "translation_ids": ["ja1", "ja2"],
                    "kind": "matched",
                }
            ]
        }
    )


def evaluation(*texts: str) -> ReviewResponse:
    """同じSpanの競合候補、または確定候補を返す。"""
    return ReviewResponse.model_validate(
        {
            "assessments": [
                {
                    "target_id": "review/alignment-000001",
                    "reason": "数値を原文に合わせる",
                    "verdict": "issue",
                    "category": "accuracy",
                    "severity": "warning",
                    "edits": [{"span_id": "ja2/span", "text": text} for text in texts],
                }
            ]
        }
    )


def test_copied_front_page_detection_requires_long_english_near_duplicates() -> None:
    """短すぎるページと日本語混在ページを複製原文と判定しない。"""
    copied_text = "Repeated English source content. " * 30
    source = document(en=copied_text)
    short = document(ja="Short title")
    translated = document(ja=("日本語の本文です。 " * 40))
    noisy_source = document(
        title=(
            "Doctrine for Command, Control, Communications, and Computer (C4) "
            'Systems Support to Joint Operations \\ (& "5 "='
        ),
        publication="Joint Pub 6-0",
        date="30 May 1995",
    )
    noisy_translation = document(
        title=(
            'CA Tv gli TB (0) WV "5 Command, Control, ~~ Communications, and '
            "Computer (C4) Systems Support to Joint Operations"
        ),
        publication="Joint Pub 6-0",
        date="30 May 1995",
    )

    assert not _copied_translation_front_page_ids(source, short)
    assert not _copied_translation_front_page_ids(source, translated)
    assert _copied_translation_front_page_ids(noisy_source, noisy_translation) == {
        "title",
        "publication",
        "date",
    }


def test_diff_schema_limits_changes_to_selected_english_units(
    config: Config, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DIFFの変更項目数を選択英文ID数に制限し、過大出力を防ぐ。"""
    client = LLMClient(
        config.model_copy(update={"llm_structured_output_mode": "json_schema"})
    )
    response = MagicMock()
    response.choices = [MagicMock(finish_reason="stop")]
    response.choices[0].message.content = json.dumps(
        {
            "changes": [
                {
                    "kind": "deleted",
                    "source_v1_ids": ["old"],
                    "translation_v1_ids": ["ja"],
                    "summary": "見出しが削除された",
                }
            ],
            "reviewed_source_v1_ids": ["old"],
            "reviewed_source_v2_ids": [],
        }
    )
    response.usage = None
    create = MagicMock(return_value=response)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        module = import_module("translate.tasks.21_diff")
        module.DiffTask(client, tmp_path, "", "").run(
            {
                "source_v1": [document(old="Chapter Title").pages[0].blocks[0].content],
                "source_v2": [],
                "translation_v1": [
                    document(ja="11.1 章のタイトル").pages[0].blocks[0].content
                ],
            },
            "match",
            0,
        )
        schema = create.call_args.kwargs["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["changes"]["maxItems"] == 1
    finally:
        client.client.close()


@pytest.mark.parametrize(
    "empty_role", [None, "source_v1", "source_v2", "translation_v1"]
)
def test_diff_schema_limits_ids_to_each_selected_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    empty_role: str | None,
) -> None:
    """旧原文・新原文・旧訳のIDを混用せず、空の文書側には参照を生成させない。"""
    documents = {
        "source_v1": document(old="First"),
        "source_v2": document(new="First"),
        "translation_v1": document(ja="一つ目"),
    }
    units = {
        role: [] if role == empty_role else list(doc.unit_index().values())
        for role, doc in documents.items()
    }
    expected = {role: [unit.id for unit in values] for role, values in units.items()}

    def answer(kwargs: dict[str, object]) -> DiffResponse:
        """送信Schemaの候補制約を検査して、入力に整合する応答を返す。"""
        schema = kwargs["native_schema"]
        fields = schema["$defs"]["DiffChange"]["properties"]
        payload = json.loads(kwargs["user"])
        sent = {role: [item["id"] for item in payload[role]] for role in expected}
        for role, ids in expected.items():
            selected = fields[f"{role}_ids"]
            if ids:
                assert selected["items"]["enum"] == sent[role]
                assert not set(ids).intersection(sent[role])
            else:
                assert selected["maxItems"] == 0
            if role != "translation_v1":
                assert f"reviewed_{role}_ids" not in schema["properties"]
        return DiffResponse.model_validate(
            {
                "changes": [
                    {
                        "kind": {"source_v1": "added", "source_v2": "deleted"}.get(
                            empty_role, "unchanged"
                        ),
                        **{f"{role}_ids": ids for role, ids in sent.items()},
                        "summary": "選択範囲の比較",
                    }
                ],
            }
        )

    scripted(monkeypatch, [answer])
    client = LLMClient(config)
    try:
        task = import_module("translate.tasks.21_diff").DiffTask(
            client, tmp_path, "", ""
        )
        _, response = task.run(units, "match", 0)
        assert response.reviewed_source_v1_ids == expected["source_v1"]
        assert response.reviewed_source_v2_ids == expected["source_v2"]
    finally:
        client.client.close()


def test_upgrade_confirms_identical_units_without_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """全英文が同一順序で一致する場合はLLMを呼ばず変更なしで完了する。"""
    monkeypatch.setattr(UpgradeAgent, "_identical_changes", _identical_changes)
    calls = scripted(monkeypatch, [])
    result = UpgradeAgent(
        {
            "source_v1": document(a="One.", b="Two."),
            "source_v2": document(x="One.", y="Two."),
            "translation_v1": document(ja="一。"),
        },
        tmp_path,
        config,
    ).run()
    assert not calls
    assert result.changes == []
    assert result.reviewed_source_v2_ids == ["x", "y"]


def test_upgrade_sends_only_differing_units_to_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """一致した英文は確定済みとなり、差分のIDだけがAgentの未確認に残る。"""
    monkeypatch.setattr(UpgradeAgent, "_identical_changes", _identical_changes)
    agent = UpgradeAgent(
        {
            "source_v1": document(a="One.", b="Old."),
            "source_v2": document(x="One.", y="New."),
            "translation_v1": document(ja="一。"),
        },
        tmp_path,
        config,
    )
    agent.confirmed = []
    assert [
        (item.source_v1_ids, item.source_v2_ids)
        for _, item in agent._identical_changes()  # noqa: SLF001
    ] == [(["a"], ["x"])]


def raising(error: Exception) -> Callable[[dict[str, object]], BaseModel]:
    """LLM要求の失敗を注入する応答を返す。"""

    def respond(_kwargs: dict[str, object]) -> BaseModel:
        """要求を受けた時点で指定の例外を送出する。"""
        raise error

    return respond


def aligned(source: str, *translations: str) -> AlignmentResponse:
    """一つの原文と訳文群の対応を返す。"""
    return AlignmentResponse.model_validate(
        {
            "groups": [
                {
                    "source_ids": [source],
                    "translation_ids": list(translations),
                    "kind": "matched",
                    "reason": "同じ内容",
                }
            ]
        }
    )


def approve_all(kwargs: dict[str, object]) -> ReviewResponse:
    """分割された評価要求でも、送られた全対象を正常と判定する。"""
    targets = json.loads(str(kwargs["user"]))["targets"]
    return successful_review(*(str(target["id"]) for target in targets))


def match_payloads(calls: list[dict[str, object]]) -> list[dict[str, list[str]]]:
    """照合要求ごとに、送った本文を文書role別に返す。"""
    return [
        {
            role: [item["text"] for item in items]
            for role, items in json.loads(str(call["user"])).items()
            if role in {"source", "translation"}
        }
        for call in calls
        if call["response_type"] is AlignmentResponse
    ]


def test_narrowed_keeps_the_start_and_halves_candidates_in_order() -> None:
    """起点以外の起点側unitを先に外し、次に指定順で候補を上位半分へ絞る。"""
    scope = {"source": ["en1", "en2"], "translation": ["a", "b", "c", "d", "e"]}
    first = narrowed(scope, "source", ("translation",), 1)
    assert first == {"source": ["en1"], "translation": ["a", "b", "c", "d", "e"]}
    assert narrowed(first, "source", ("translation",), 1) == {
        "source": ["en1"],
        "translation": ["a", "b"],
    }
    assert (
        narrowed(
            {"source": ["en1"], "translation": ["a"]}, "source", ("translation",), 1
        )
        is None
    )
    upgrade = {"source_v1": ["old"], "source_v2": ["new"], "translation_v1": ["ja"]}
    step = narrowed(upgrade, "source_v1", ("translation_v1", "source_v2"), 0)
    assert step == {"source_v1": ["old"], "source_v2": ["new"], "translation_v1": []}
    step = narrowed(step, "source_v1", ("translation_v1", "source_v2"), 0)
    assert step == {"source_v1": ["old"], "source_v2": [], "translation_v1": []}
    assert narrowed(step, "source_v1", ("translation_v1", "source_v2"), 0) is None


def test_positional_candidates_pick_unused_units_near_the_relative_position() -> None:
    """Embeddingがない場合は、起点と相対位置が近い未使用unitを文書順で補う。"""
    units = agent_units(
        {
            "source": document(**{f"en{index}": "Text" for index in range(3)}),
            "translation": document(**{f"ja{index}": "訳" for index in range(20)}),
        }
    )
    available = {
        "source": set(units["source"]),
        "translation": set(units["translation"]) - {"ja19"},
    }
    result = positional_candidates(units, {"source": ["en2"]}, available, "source")
    assert result["source"] == ["en2"]
    assert result["translation"] == [f"ja{index}" for index in range(11, 19)]
    kept = positional_candidates(
        units, {"source": ["en0"], "translation": ["ja5"]}, available, "source"
    )
    assert kept["translation"] == ["ja5"]


def test_review_leaves_translator_columns_out_of_matching_and_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """英文に対応のない訳者のコラムは評価せず、指摘・修正の対象にもしない。"""
    documents = {
        "source": document(en1="Alpha is the first value.", en2="Beta is the second."),
        "translation": document(
            ja1="アルファは最初の値です。",
            column="コラム アルファとベータの補足説明。",
            ja2="ベータは二番目です。",
        ),
    }
    calls = scripted(
        monkeypatch,
        [
            aligned("en1", "ja1"),
            aligned("en2", "ja2"),
            successful_review("review/alignment-000001"),
            successful_review("review/alignment-000002"),
        ],
    )
    result = ReviewAgent(documents, tmp_path, tmp_path, config).run()

    assert match_payloads(calls)[0]["translation"] == [
        "アルファは最初の値です。",
        "コラム アルファとベータの補足説明。",
        "ベータは二番目です。",
    ]
    assert "コラム" in str(calls[0]["system"]) + str(calls[0]["contract"])
    evaluated = " ".join(
        str(call["user"]) for call in calls if call["response_type"] is ReviewResponse
    )
    assert "コラム" not in evaluated
    assert [
        (group.kind, group.source_ids, group.translation_ids) for group in result.groups
    ] == [
        ("matched", ["en1"], ["ja1"]),
        ("matched", ["en2"], ["ja2"]),
        ("translation_only", [], ["column"]),
    ]
    assert "補足" in (result.groups[-1].reason or "")
    assert result.reviewed_target_ids == [
        "review/alignment-000001",
        "review/alignment-000002",
    ]
    assert not result.findings
    assert not result.revisions


def test_review_and_upgrade_never_offer_a_titled_translator_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """本文の見出しに似たコラムの見出しも、照合・比較の候補に入れない。"""
    review_calls = scripted(
        monkeypatch,
        [aligned("en", "ja"), successful_review("review/alignment-000001")],
    )
    result = ReviewAgent(
        {
            "source": document(en="INFORMATION QUALITY CRITERIA"),
            "translation": document(
                column="コラム\uff1a情報の質の基準について", ja="情報の質の基準"
            ),
        },
        tmp_path / "review",
        tmp_path / "review",
        config,
    ).run()
    assert match_payloads(review_calls)[0]["translation"] == ["情報の質の基準"]
    assert ("translation_only", ["column"]) in [
        (group.kind, group.translation_ids) for group in result.groups
    ]

    upgrade_calls = scripted(
        monkeypatch,
        [
            DiffResponse.model_validate(
                {
                    "changes": [
                        {
                            "kind": "modified",
                            "source_v1_ids": ["old"],
                            "source_v2_ids": ["new"],
                            "translation_v1_ids": ["ja"],
                            "summary": "変更",
                            "suggested_translation": "新しい訳。",
                        }
                    ]
                }
            )
        ],
    )
    UpgradeAgent(
        {
            "source_v1": document(old="Old text."),
            "source_v2": document(new="New text."),
            "translation_v1": document(column="訳注\uff1a補足説明。", ja="旧訳。"),
        },
        tmp_path / "upgrade",
        config,
    ).run()
    assert "補足説明" not in str(upgrade_calls[0]["user"])


def test_review_narrows_a_failed_match_scope_until_it_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """入力上限超過や応答不正の照合は候補を絞って続け、Review全体を完了する。"""
    documents = {
        "source": document(en="Two"),
        "translation": document(t1="一", t2="二", t3="三", t4="四"),
    }
    calls = scripted(
        monkeypatch,
        [
            raising(LLMInputExceededError("too large")),
            raising(LLMInvalidResponseError("invalid")),
            aligned("en", "t1"),
            successful_review("review/alignment-000001"),
        ],
    )
    result = ReviewAgent(documents, tmp_path, tmp_path, config).run()

    assert [payload["translation"] for payload in match_payloads(calls)] == [
        ["一", "二", "三", "四"],
        ["一", "二"],
        ["一"],
    ]
    assert [
        (group.kind, group.source_ids, group.translation_ids) for group in result.groups
    ] == [
        ("matched", ["en"], ["t1"]),
        ("translation_only", [], ["t2"]),
        ("translation_only", [], ["t3"]),
        ("translation_only", [], ["t4"]),
    ]


def test_review_resamples_an_unsplittable_target_after_output_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """分割できない対象の出力上限到達は、生成し直してReviewを完了する。"""
    documents = {
        "source": document(en="Two"),
        "translation": document(ja="二"),
    }
    calls = scripted(
        monkeypatch,
        [
            aligned("en", "ja"),
            raising(LLMOutputTokenExceededError("looped")),
            successful_review("review/alignment-000001"),
        ],
    )
    result = ReviewAgent(documents, tmp_path, tmp_path, config).run()

    evaluated = [call for call in calls if call["response_type"] is ReviewResponse]
    assert len(evaluated) == 2
    assert evaluated[0]["user"] == evaluated[1]["user"]
    assert result.reviewed_target_ids == ["review/alignment-000001"]


def test_review_matches_a_formula_without_evaluating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """数式だけの原文は対応を記録し、翻訳対象外として評価しない。"""
    documents = {
        "source": document(en="Alpha", formula=r"a = \begin{pmatrix} 0 \end{pmatrix}"),
        "translation": document(ja="アルファ", math=r"$$a = \begin{pmatrix} 0"),
    }
    documents["source"].pages[0].blocks[1].content.spans[0].kind = "code"
    calls = scripted(
        monkeypatch,
        [
            aligned("en", "ja"),
            aligned("formula", "math"),
            successful_review("review/alignment-000001"),
        ],
    )
    result = ReviewAgent(documents, tmp_path, tmp_path, config).run()

    evaluated = [call for call in calls if call["response_type"] is ReviewResponse]
    assert len(evaluated) == 1
    assert "pmatrix" not in str(evaluated[0]["user"])
    assert [(group.kind, group.translation_ids) for group in result.groups] == [
        ("matched", ["ja"]),
        ("matched", ["math"]),
    ]
    assert "対象外" in (result.groups[1].reason or "")
    assert result.reviewed_target_ids == ["review/alignment-000001"]


def test_review_records_a_source_without_counterpart_and_reuses_saved_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """対応のない原文は訳抜け候補として残し、再実行では保存済みCallを再利用する。"""
    documents = {
        "source": document(en1="Alpha", en2="Missing sentence."),
        "translation": document(ja="アルファ"),
    }
    calls = scripted(
        monkeypatch,
        [
            aligned("en1", "ja"),
            successful_review("review/alignment-000001"),
        ],
    )
    first = ReviewAgent(documents, tmp_path, tmp_path, config).run()
    assert len(calls) == 2
    assert [(group.kind, group.source_ids) for group in first.groups] == [
        ("matched", ["en1"]),
        ("source_only", ["en2"]),
    ]
    assert "訳抜け" in (first.groups[1].reason or "")

    resumed_calls = scripted(monkeypatch, [])
    resumed = ReviewAgent(documents, tmp_path, tmp_path, config).run()
    assert not resumed_calls
    assert resumed == first


def test_review_uses_source_text_for_a_copied_front_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """訳文の先頭に複製された英語表紙は、原文を比較基準にして評価する。"""
    cover = "Joint Planning doctrine for command and control of joint operations. " * 3
    documents = {
        "source": document(en=cover),
        "translation": document(copy=cover.replace("command", "cornmand")),
    }
    calls = scripted(
        monkeypatch,
        [aligned("en", "copy"), successful_review("review/alignment-000001")],
    )
    result = ReviewAgent(documents, tmp_path, tmp_path, config).run()
    assert result.targets[0].translation == cover
    assert result.targets[0].spans == []
    assert "cornmand" not in str(calls[-1]["user"])


def test_review_rejects_two_edits_for_the_same_span(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じSpanへの複数の修正は応答不正として再要求し、一つの判定を採用する。"""
    duplicate = {
        "assessments": [
            {
                "target_id": "1",
                "reason": "数値を原文に合わせる。",
                "verdict": "issue",
                "edits": [
                    {"span_id": "s1", "text": "二つ。"},
                    {"span_id": "s1", "text": "2つ。"},
                ],
                "category": "accuracy",
                "severity": "error",
            }
        ],
    }
    responses = []
    for payload in [duplicate, successful_review("1").model_dump()]:
        response = MagicMock()
        response.choices = [MagicMock(finish_reason="stop")]
        response.choices[0].message.content = json.dumps(payload)
        response.usage = None
        responses.append(response)
    client = LLMClient(config)
    create = MagicMock(side_effect=responses)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    target = ReviewTarget(
        id="review/current",
        source="Two.",
        translation="三つ。",
        target_ids=["ja"],
        spans=[TextSpan(id="span", source="三つ。")],
    )
    task = import_module("translate.tasks.41_review").ReviewTask(
        config, tmp_path, "", ""
    )
    try:
        result = task.run([target], tmp_path, client=client)
    finally:
        client.client.close()
    assert create.call_count == 2
    assert not result.revisions


def test_match_clips_long_units_to_fit_the_input_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """長いunitは先頭と末尾を残して照合へ送り、入力上限を超えない。"""
    long_text = "Start. " + "Middle sentence. " * 2000 + "End."
    documents = {
        "source": document(en=long_text),
        "translation": document(ja="開始。中間の文。終わり。"),
    }
    calls = scripted(
        monkeypatch,
        [aligned("en", "ja"), *[approve_all] * 16],
    )
    ReviewAgent(documents, tmp_path, tmp_path, config).run()
    payload = match_payloads(calls)[0]
    assert payload["source"][0].startswith("Start.")
    assert payload["source"][0].endswith("End.")
    assert " … " in payload["source"][0]
    budget = config.input_bytes(config.review_input_tokens)
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < budget


def test_upgrade_narrows_candidates_and_then_compares_remaining_new_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """比較の失敗は旧訳、新版の順に候補を絞って続け、残った新版も比較する。"""
    documents = {
        "source_v1": document(old="Old text."),
        "source_v2": document(new="New text.", other="Other text."),
        "translation_v1": document(ja1="旧訳。", ja2="コラム 補足。"),
    }
    failure = raising(LLMInvalidResponseError("invalid"))
    calls = scripted(
        monkeypatch,
        [
            failure,
            failure,
            failure,
            DiffResponse.model_validate(
                {
                    "changes": [
                        {
                            "kind": "modified",
                            "source_v1_ids": ["old"],
                            "source_v2_ids": ["new"],
                            "summary": "文言を変更",
                            "suggested_translation": "新しい訳。",
                        }
                    ]
                }
            ),
            DiffResponse.model_validate(
                {
                    "changes": [
                        {
                            "kind": "added",
                            "source_v2_ids": ["other"],
                            "summary": "追加",
                            "suggested_translation": "その他。",
                        }
                    ]
                }
            ),
        ],
    )
    result = UpgradeAgent(documents, tmp_path, config).run()

    sizes = [
        {
            role: len(items)
            for role, items in json.loads(str(call["user"])).items()
            if role in documents
        }
        for call in calls
    ]
    assert sizes == [
        {"source_v1": 1, "source_v2": 2, "translation_v1": 2},
        {"source_v1": 1, "source_v2": 2, "translation_v1": 1},
        {"source_v1": 1, "source_v2": 2, "translation_v1": 0},
        {"source_v1": 1, "source_v2": 1, "translation_v1": 0},
        {"source_v1": 0, "source_v2": 1, "translation_v1": 2},
    ]
    assert "コラム" in str(calls[0]["system"]) + str(calls[0]["contract"])
    assert [(change.kind, change.source_v2_ids) for change in result.changes] == [
        ("modified", ["new"]),
        ("added", ["other"]),
    ]
    assert result.reviewed_source_v1_ids == ["old"]
    assert result.reviewed_source_v2_ids == ["new", "other"]

    # 失敗したCallは保存されないため、再開時は失敗した要求だけを再び送る。
    resumed_calls = scripted(monkeypatch, [failure, failure, failure])
    assert UpgradeAgent(documents, tmp_path, config).run() == result
    assert len(resumed_calls) == 3


def test_upgrade_raises_when_the_starting_unit_alone_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """候補をすべて外しても起点だけの比較が失敗する場合は、その失敗を伝える。"""
    documents = {
        "source_v1": document(old="Old text."),
        "source_v2": document(),
        "translation_v1": document(),
    }
    scripted(monkeypatch, [raising(LLMInputExceededError("too large"))])
    with pytest.raises(LLMInputExceededError):
        UpgradeAgent(documents, tmp_path, config).run()


def test_upgrade_resamples_the_starting_unit_after_output_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """起点だけの比較が出力上限へ達した場合は、同じ範囲を生成し直して完了する。"""
    documents = {
        "source_v1": document(old="Old text."),
        "source_v2": document(),
        "translation_v1": document(),
    }
    calls = scripted(
        monkeypatch,
        [
            raising(LLMOutputTokenExceededError("looped")),
            DiffResponse.model_validate(
                {
                    "changes": [
                        {
                            "kind": "deleted",
                            "source_v1_ids": ["old"],
                            "summary": "削除",
                        }
                    ]
                }
            ),
        ],
    )
    UpgradeAgent(documents, tmp_path, config).run()
    assert len(calls) == 2
    assert json.loads(str(calls[0]["user"])) == json.loads(str(calls[1]["user"]))


def test_agent_deadline_scales_with_english_units(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """期限は英文1,000要素ごとに設定値を加算し、小さい文書でも設定値を下回らない。"""
    monkeypatch.setattr("translate.pipeline.time.monotonic", lambda: 100.0)
    limit = config.llm_task_deadline_seconds
    assert agent_deadline(config, 0) == 100.0 + limit
    assert agent_deadline(config, 1000) == 100.0 + limit
    assert agent_deadline(config, 3526) == 100.0 + limit * 4
