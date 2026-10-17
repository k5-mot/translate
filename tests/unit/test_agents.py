"""実際のAgent制御・保存・再開を、外部LLM応答だけ差し替えて検証する。"""

import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from tests import successful_review
from translate.adapters.artifact_store import load_model
from translate.adapters.llm import (
    LLMClient,
    LLMConnectionError,
    LLMError,
    LLMInputExceededError,
    LLMInvalidResponseError,
    StructuredResult,
)
from translate.common.config import Config
from translate.models.artifacts import LLMCallArtifact
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.models.review import (
    AgentAction,
    AlignmentResponse,
    ReviewResponse,
    ReviewTarget,
)
from translate.models.upgrade import DiffResponse
from translate.pipeline import (
    InputError,
    agent_units,
    choose_action,
    completed_agent_calls,
    observe_documents,
)
from translate.pipeline.review import ReviewAgent
from translate.pipeline.upgrade import UpgradeAgent


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


@pytest.mark.parametrize("operation", ["overview", "read"])
@pytest.mark.parametrize("count", [1, 9])
def test_agent_fits_observation_without_cutting_units(
    config: Config, monkeypatch: pytest.MonkeyPatch, operation: str, count: int
) -> None:
    """状態とSchema込みの上限を守り、候補本文を切らず後続の閲覧位置を保持する。"""
    client = LLMClient(config.model_copy(update={"review_input_tokens": 11264}))
    units = agent_units(
        {
            "source": document(
                **{
                    f"unit-{i}": "文脈を保持する。" * (500 if count == 1 else 150)
                    for i in range(13)
                }
            )
        }
    )
    items = [
        {"role": "source", "id": key, "text": unit.text("source")}
        for key, unit in list(units["source"].items())[4 : 4 + count]
    ]
    observation = {
        "action": {"operation": operation, "offset": 4},
        "result": {"items": items, "total": 13, "next_offset": None},
    }
    original = json.dumps(observation, ensure_ascii=False)
    response = MagicMock()
    response.choices = [MagicMock(finish_reason="stop")]
    response.choices[0].message.content = AgentAction(
        operation="overview"
    ).model_dump_json()
    response.usage = None
    create = MagicMock(return_value=response)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        if count == 1:
            with pytest.raises(LLMInputExceededError):
                choose_action(
                    client,
                    "Compare documents.",
                    {"roles": ["source"], "pending_counts": {"source": 13}},
                    observation,
                    units,
                )
            create.assert_not_called()
            return
        action = choose_action(
            client,
            "Compare documents.",
            {"roles": ["source"], "pending_counts": {"source": 13}},
            observation,
            units,
        )
        assert action.operation == "overview"
        create.assert_called_once()
        sent = json.loads(create.call_args.kwargs["messages"][1]["content"])[
            "observation"
        ]["result"]
        assert 0 < len(sent["items"]) < len(items)
        assert sent["items"] == items[: len(sent["items"])]
        assert sent["next_offset"] == 4 + len(sent["items"])
        assert sent["total"] == 13
        assert json.dumps(observation, ensure_ascii=False) == original
    finally:
        client.client.close()


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
                    "target_id": key,
                    "reason": "適切な訳文",
                    "verdict": "correct",
                    "edits": [],
                    "category": None,
                    "severity": None,
                }
                for key in expected
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
        assert (
            schema["$defs"]["ReviewAssessment"]["properties"]["target_id"]["enum"]
            == expected
        )
        assert field["minItems"] == field["maxItems"] == len(expected)
        assert result.reviewed_target_ids == expected
    finally:
        client.client.close()


@pytest.mark.parametrize(
    ("invalid", "expected_operation", "attempts"),
    [
        (AgentAction(operation="evaluate", target_ids=["source-id"]), "match", 2),
        (AgentAction(operation="recheck"), "match", 2),
        (
            AgentAction(operation="read", references={"source": ["invented-id"]}),
            "match",
            2,
        ),
        (
            AgentAction(operation="overview", references={"ignored": ["unused-id"]}),
            "overview",
            1,
        ),
    ],
)
def test_agent_validates_only_used_action_arguments(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    invalid: AgentAction,
    expected_operation: str,
    attempts: int,
) -> None:
    """操作に必要な対象だけを検証・訂正し、閲覧に使わない引数は破棄する。"""
    client = LLMClient(
        config.model_copy(update={"llm_structured_output_mode": "json_schema"})
    )
    responses = []
    for action in (
        invalid,
        AgentAction(
            operation="match",
            references={"source": ["source-id"], "translation": ["translation-id"]},
        ),
    ):
        response = MagicMock()
        response.choices = [MagicMock(finish_reason="stop")]
        response.choices[0].message.content = action.model_dump_json()
        response.usage = None
        responses.append(response)
    create = MagicMock(side_effect=responses)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        action = choose_action(
            client,
            "Review English source against Japanese translation.",
            {
                "roles": ["source", "translation"],
                "pending_counts": {"source": 1, "translation": 1},
                "pending_ids": {
                    "source": ["source-id"],
                    "translation": ["translation-id"],
                },
                "unchecked_targets": [],
                "unchecked_count": 0,
                "conflicts": [],
            },
            {},
            agent_units(
                {
                    "source": document(
                        **{"source-id": "Original", "unseen-id": "Not displayed"}
                    ),
                    "translation": document(**{"translation-id": "訳文"}),
                }
            ),
        )
        assert action.operation == expected_operation
        assert create.call_count == attempts
        if attempts == 2:
            assert "Previous response validation failed" in str(
                create.call_args_list[1]
            )
        else:
            assert action.references == {}
        properties = create.call_args.kwargs["response_format"]["json_schema"][
            "schema"
        ]["properties"]
        assert properties["role"]["enum"] == ["", "source", "translation"]
        assert properties["references"]["properties"]["source"]["items"]["enum"] == [
            "source-id"
        ]
    finally:
        client.client.close()


def test_upgrade_action_reselects_within_reduced_reference_limit(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """入力予算から下げたUpgrade対象数を超える操作を同じ訂正枠で選び直す。"""
    client = LLMClient(
        config.model_copy(update={"llm_structured_output_mode": "json_schema"})
    )
    units = agent_units(
        {
            "source_v1": document(old1="Old one", old2="Old two"),
            "source_v2": document(new1="New one", new2="New two"),
            "translation_v1": document(),
        }
    )
    state = {
        "roles": list(units),
        "pending_counts": {role: len(values) for role, values in units.items()},
        "pending_ids": {role: list(values) for role, values in units.items()},
        "translation_candidates": [],
        "confirmed_count": 0,
        "max_reference_ids": 2,
    }
    responses = []
    for references in (
        {"source_v1": ["old1", "old2"], "source_v2": ["new1"]},
        {"source_v1": ["old1"], "source_v2": ["new1"]},
    ):
        response = MagicMock()
        response.choices = [MagicMock(finish_reason="stop")]
        response.choices[0].message.content = AgentAction(
            operation="match", references=references
        ).model_dump_json()
        response.usage = None
        responses.append(response)
    create = MagicMock(side_effect=responses)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        action = choose_action(
            client,
            "Compare English source_v1/source_v2 and Japanese translation_v1.",
            state,
            {},
            units,
        )
        assert sum(map(len, action.references.values())) == 2
        assert create.call_count == 2
        assert "Previous response validation failed" in str(create.call_args_list[1])
        role_limits = create.call_args.kwargs["response_format"]["json_schema"][
            "schema"
        ]["properties"]["references"]["properties"]
        assert {role: value["maxItems"] for role, value in role_limits.items()} == {
            "source_v1": 1,
            "source_v2": 1,
            "translation_v1": 0,
        }
    finally:
        client.client.close()


def test_agent_overview_includes_bounded_content() -> None:
    """IDだけの一覧でAgentが探索を繰り返さないよう、予算内で本文も提示する。"""
    units = agent_units(
        {
            "source": document(
                **{f"unit-{i}": "Heading and context. " * 8 for i in range(10)}
            ),
            "translation": document(**{"translated-unit": "Translated context. " * 8}),
        }
    )
    result = observe_documents(AgentAction(operation="overview"), units, 700)
    assert "Heading and context." in json.dumps(result)
    assert 0 < len(result["items"]) < 10
    assert result["next_offset"] == len(result["items"])
    assert len(json.dumps(result["items"]).encode()) <= 700
    assert [item["role"] for item in result["items"][:2]] == ["source", "translation"]


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
    response.choices[0].message.content = json.dumps({"groups": groups})
    response.usage = None
    create = MagicMock(return_value=response)
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        units = agent_units(
            {"source": document(en="Original."), "translation": document(ja="訳文。")}
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
        assert [key for group in result.groups for key in group.translation_ids] == [
            "ja"
        ]
        create.assert_called_once()
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
        assert create.call_count == 3
        assert not list(tmp_path.glob("calls/*/response.json"))
    finally:
        client.client.close()


def test_match_retry_identifies_missing_duplicate_and_unknown_ids(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """対応付けの再試行で、訳文側の不足・重複・範囲外IDを具体的に伝える。"""
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
        assert "translation: missing=['ja2']" in feedback
        assert "duplicate=['ja1']" in feedback
        assert "unknown=['unknown']" in feedback
        assert (
            result.model_dump() == AlignmentResponse.model_validate(valid).model_dump()
        )
        assert create.call_count == 2
    finally:
        client.client.close()


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


def test_review_recovers_unmatched_units_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """候補不足の未対応群を部分的に再対応付けし、IDと再開時の結果を保つ。"""
    documents = {
        "source": document(en1="Alpha", en2="Beta"),
        "translation": document(ja1="ベータ", ja2="アルファ"),
    }

    def recover_remaining(kwargs: dict[str, object]) -> AgentAction:
        """一部を対応付けた後も未対応の残りを観察し、次の候補へ組み直す。"""
        state = json.loads(kwargs["user"])["state"]
        assert state["unmatched_ids"] == {"source": [], "translation": ["ja1"]}
        assert state["unmatched_counts"] == {"source": 0, "translation": 1}
        assert state["unchecked_targets"] == ["review/alignment-000003"]
        items = json.loads(kwargs["user"])["observation"]["result"]["items"]
        assert {(item["role"], item["id"], item["text"]) for item in items} == {
            ("source", "en2", "Beta"),
            ("translation", "ja1", "ベータ"),
        }
        return AgentAction(
            operation="match", references={"source": ["en2"], "translation": ["ja1"]}
        )

    answers = [
        AgentAction(
            operation="match",
            references={"source": ["en1"], "translation": ["ja1", "ja2"]},
        ),
        AlignmentResponse.model_validate(
            {
                "groups": [
                    {
                        "source_ids": ["en1"],
                        "translation_ids": [],
                        "kind": "source_only",
                        "reason": "対応未確定",
                    },
                    {
                        "source_ids": [],
                        "translation_ids": ["ja1", "ja2"],
                        "kind": "translation_only",
                        "reason": "対応未確定",
                    },
                ]
            }
        ),
        AgentAction(
            operation="match", references={"source": ["en1"], "translation": ["ja2"]}
        ),
        AlignmentResponse.model_validate(
            {
                "groups": [
                    {
                        "source_ids": ["en1"],
                        "translation_ids": ["ja2"],
                        "kind": "matched",
                    }
                ]
            }
        ),
        AgentAction(operation="overview"),
        recover_remaining,
        AlignmentResponse.model_validate(
            {
                "groups": [
                    {
                        "source_ids": ["en2"],
                        "translation_ids": ["ja1"],
                        "kind": "matched",
                    }
                ]
            }
        ),
        AgentAction(
            operation="evaluate",
            target_ids=["review/alignment-000003", "review/alignment-000004"],
        ),
        successful_review(*["review/alignment-000003", "review/alignment-000004"]),
        AgentAction(operation="finish"),
    ]
    calls = scripted(monkeypatch, answers)
    directory = tmp_path / "review"
    result = ReviewAgent(documents, directory, tmp_path, config).run()
    assert not answers
    assert [
        (group.id, group.source_ids, group.translation_ids) for group in result.groups
    ] == [
        ("alignment-000003", ["en1"], ["ja2"]),
        ("alignment-000004", ["en2"], ["ja1"]),
    ]
    assert len(result.targets) == len(result.reviewed_target_ids) == 2
    before = len(calls)
    answers.append(AgentAction(operation="finish"))
    assert ReviewAgent(documents, directory, tmp_path, config).run() == result
    assert len(calls) == before + 1


def test_review_cannot_rematch_confirmed_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """未対応の再探索を許しても、確定した対応の再割当ては拒否する。"""
    action = AgentAction(
        operation="match", references={"source": ["en"], "translation": ["ja1", "ja2"]}
    )
    scripted(monkeypatch, [action, matched(), action])
    with pytest.raises(InputError, match="confirmed correspondence"):
        ReviewAgent(
            {
                "source": document(en="Text"),
                "translation": document(ja1="訳", ja2="文"),
            },
            tmp_path / "review",
            tmp_path,
            config,
        ).run()


def test_review_observes_only_current_matches_and_retains_all_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """概要を再取得しながら13群を完了し、直近の観察と全確認範囲を保持する。"""
    documents = {
        "source": document(**{f"en-{index}": "Text" for index in range(78)}),
        "translation": document(**{f"ja-{index}": "訳文" for index in range(78)}),
    }

    def evaluate_current(kwargs: dict[str, object]) -> AgentAction:
        """直前の8組だけを観察し、累積状態にある未評価IDを選ぶ。"""
        payload = json.loads(kwargs["user"])
        groups = payload["observation"]["result"]["groups"]
        targets = payload["state"]["unchecked_targets"]
        assert len(groups) == len(targets) == 6
        assert [f"review/{group['id']}" for group in groups] == targets
        return AgentAction(operation="evaluate", target_ids=targets)

    def review_current(kwargs: dict[str, object]) -> ReviewResponse:
        """各Review Callが実際に受け取った対象IDへ応答する。"""
        payload = json.loads(kwargs["user"])
        target_ids = [target["id"] for target in payload["targets"]]
        return successful_review(*target_ids)

    answers = []
    for start in range(0, 78, 6):
        answers.extend(
            [
                AgentAction(operation="overview"),
                AgentAction(
                    operation="match",
                    references={
                        "source": [f"en-{index}" for index in range(start, start + 6)],
                        "translation": [
                            f"ja-{index}" for index in range(start, start + 6)
                        ],
                    },
                ),
                AlignmentResponse.model_validate(
                    {
                        "groups": [
                            {
                                "source_ids": [f"en-{index}"],
                                "translation_ids": [f"ja-{index}"],
                                "kind": "matched",
                            }
                            for index in range(start, start + 6)
                        ]
                    }
                ),
                evaluate_current,
                review_current,
            ]
        )
    answers.append(AgentAction(operation="finish"))
    scripted(monkeypatch, answers)
    result = ReviewAgent(documents, tmp_path / "review", tmp_path, config).run()
    assert len(result.groups) == len(result.reviewed_target_ids) == 78
    assert not answers


@pytest.mark.parametrize("kind", ["review", "upgrade"])
def test_agent_recovers_invalid_action_without_losing_confirmed_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config, kind: str
) -> None:
    """不正な次操作を実行せず、成功済み対象を保って残りの対象を確認する。"""
    role = "source" if kind == "review" else "source_v1"
    roles = (
        [role, "translation"]
        if kind == "review"
        else [role, "source_v2", "translation_v1"]
    )
    documents = {name: document() for name in roles}
    documents[role] = document(first="First", second="Second")

    def result(key: str) -> BaseModel:
        """原文だけに存在する選択対象を確認済みとして返す。"""
        if kind == "review":
            return AlignmentResponse.model_validate(
                {
                    "groups": [
                        {
                            "source_ids": [key],
                            "translation_ids": [],
                            "kind": "source_only",
                            "reason": "対応訳なし",
                        }
                    ]
                }
            )
        return DiffResponse.model_validate(
            {
                "changes": [
                    {
                        "source_v1_ids": [key],
                        "kind": "deleted",
                        "summary": "新版から削除",
                        "suggested_translation": None,
                    }
                ],
                "reviewed_source_v1_ids": [key],
                "reviewed_source_v2_ids": [],
            }
        )

    def failed_action(kwargs: dict[str, object]) -> BaseModel:
        """操作選択の応答訂正を使い切った失敗を再現する。"""
        assert kwargs["response_type"] is AgentAction
        message = "Invalid action after validation retry"
        raise LLMInvalidResponseError(message)

    def reselect(kwargs: dict[str, object]) -> AgentAction:
        """失敗の通知と未確認数を確認し、残る対象だけを選ぶ。"""
        payload = json.loads(kwargs["user"])
        assert payload["state"]["pending_counts"][role] == 1
        assert "invalid" in payload["observation"]["error"].lower()
        return AgentAction(operation="match", references={role: ["second"]})

    answers = [
        AgentAction(operation="match", references={role: ["first"]}),
        result("first"),
        failed_action,
        reselect,
        result("second"),
        AgentAction(operation="finish"),
    ]
    scripted(monkeypatch, answers)
    agent = (
        ReviewAgent(documents, tmp_path, tmp_path, config)
        if kind == "review"
        else UpgradeAgent(documents, tmp_path, config)
    )
    output = agent.run()
    assert not answers
    assert len(output.groups if kind == "review" else output.changes) == 2
    artifacts = [
        load_model(path, LLMCallArtifact) for path in tmp_path.glob("calls/*/call.json")
    ]
    assert len(artifacts) == 2
    assert all(call.status == "succeeded" for call in artifacts)


@pytest.mark.parametrize("kind", ["review", "upgrade"])
@pytest.mark.parametrize(
    "case",
    [
        (LLMInvalidResponseError, TimeoutError, 12),
        (LLMConnectionError, LLMConnectionError, 1),
    ],
)
def test_agent_action_failure_keeps_stop_conditions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    kind: str,
    case: tuple[type[LLMError], type[Exception], int],
) -> None:
    """操作選択の契約不正は12回で止め、接続障害を選び直しで再送しない。"""
    error_type, expected, attempts = case

    def failure(kwargs: dict[str, object]) -> BaseModel:
        """実行操作へ進む前のAgent判断を指定された例外で失敗させる。"""
        assert kwargs["response_type"] is AgentAction
        message = "Action failed"
        raise error_type(message)

    attempt_limit = attempts * (
        3 if kind == "upgrade" and error_type is LLMInvalidResponseError else 1
    )
    answers = [failure] * attempt_limit
    scripted(monkeypatch, answers)
    roles = (
        ["source", "translation"]
        if kind == "review"
        else ["source_v1", "source_v2", "translation_v1"]
    )
    documents = {role: document(unit="Text") for role in roles}
    agent = (
        ReviewAgent(documents, tmp_path, tmp_path, config)
        if kind == "review"
        else UpgradeAgent(documents, tmp_path, config)
    )
    with pytest.raises(expected):
        agent.run()
    assert not answers
    assert not list(tmp_path.glob("calls/*/call.json"))
    assert not (tmp_path / "review.json").exists()
    assert not (tmp_path / "plan.json").exists()


def test_review_agent_reselects_after_invalid_operation_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """検証再試行を使い切ったmatchを失敗保存し、Agentが対象を絞って確認を完了する。"""
    documents = {
        "source": document(en="Use two units."),
        "translation": document(ja1="二つ使用する。", ja2="補足。"),
    }

    def failed_match(_kwargs: dict[str, object]) -> BaseModel:
        """LLM接続層が検証再試行後に返す失敗を再現する。"""
        message = "Invalid correspondence after retry"
        raise LLMInvalidResponseError(message)

    def reselect(kwargs: dict[str, object]) -> AgentAction:
        """失敗を観察して、未確認のまま保持された対象から小さな候補群を選ぶ。"""
        payload = json.loads(kwargs["user"])
        assert payload["state"]["pending_counts"] == {"source": 1, "translation": 2}
        assert payload["state"]["unchecked_count"] == 0
        assert "invalid" in payload["observation"]["result"]["error"]
        return AgentAction(
            operation="match", references={"source": ["en"], "translation": ["ja1"]}
        )

    answers = [
        AgentAction(
            operation="match",
            references={"source": ["en"], "translation": ["ja1", "ja2"]},
        ),
        failed_match,
        reselect,
        AlignmentResponse.model_validate(
            {
                "groups": [
                    {
                        "source_ids": ["en"],
                        "translation_ids": ["ja1"],
                        "kind": "matched",
                    }
                ]
            }
        ),
        AgentAction(operation="evaluate", target_ids=["review/alignment-000001"]),
        successful_review(*["review/alignment-000001"]),
        AgentAction(operation="match", references={"translation": ["ja2"]}),
        AlignmentResponse.model_validate(
            {
                "groups": [
                    {
                        "source_ids": [],
                        "translation_ids": ["ja2"],
                        "kind": "translation_only",
                        "reason": "原文にない補足",
                    }
                ]
            }
        ),
        AgentAction(operation="finish"),
    ]
    scripted(monkeypatch, answers)
    result = ReviewAgent(documents, tmp_path, tmp_path, config).run()
    assert not answers
    assert len(result.groups) == 2
    assert result.reviewed_target_ids == ["review/alignment-000001"]
    artifacts = [
        load_model(path, LLMCallArtifact) for path in tmp_path.glob("calls/*/call.json")
    ]
    assert sorted(item.status for item in artifacts) == [
        "failed",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    failed = next(item for item in artifacts if item.status == "failed")
    assert not (tmp_path / "calls" / failed.call_id / "response.json").exists()


@pytest.mark.parametrize(
    "case",
    [
        (LLMInvalidResponseError, TimeoutError, 12),
        (LLMConnectionError, LLMConnectionError, 1),
    ],
)
def test_review_operation_failure_retains_stop_conditions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    case: tuple[type[LLMError], type[Exception], int],
) -> None:
    """契約不正の反復は12stepで止まり、接続失敗は対象選び直しで再送しない。"""
    error_type, expected_error, attempts = case

    def failure(_kwargs: dict[str, object]) -> BaseModel:
        """操作のLLM要求だけを指定された失敗にする。"""
        message = "Operation failed"
        raise error_type(message)

    action = AgentAction(
        operation="match", references={"source": ["en"], "translation": ["ja"]}
    )
    answers = [item for _ in range(attempts) for item in (action, failure)]
    scripted(monkeypatch, answers)
    with pytest.raises(expected_error):
        ReviewAgent(
            {"source": document(en="Text"), "translation": document(ja="訳文")},
            tmp_path,
            tmp_path,
            config,
        ).run()
    assert not answers
    assert not (tmp_path / "review.json").exists()
    assert len(list(tmp_path.glob("calls/*/call.json"))) == attempts
    assert not list(tmp_path.glob("calls/*/response.json"))


def test_review_observes_conflict_and_rechecks_then_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """文脈取得・探索・一対多対応・競合再確認を実行し、再開時は成功操作を再送しない。"""
    documents = {
        "source": document(en="Use two units."),
        "translation": document(ja1="使用する。", ja2="三つ。"),
    }
    original = {role: value.model_dump() for role, value in documents.items()}
    refs = {"source": ["en"], "translation": ["ja1", "ja2"]}

    def after_conflict(kwargs: dict[str, object]) -> AgentAction:
        """競合の観察結果から再確認を選ぶ。"""
        payload = json.loads(kwargs["user"])
        observation = payload["observation"]
        assert payload["state"]["reviewed_targets"] == ["review/alignment-000001"]
        assert observation["action"]["operation"] == "evaluate"
        assert observation["result"]["conflicts"] == ["review/alignment-000001"]
        return AgentAction(
            operation="recheck", target_ids=observation["result"]["conflicts"]
        )

    def after_overview(kwargs: dict[str, object]) -> AgentAction:
        """対応済みの要素が概要へ再登場せず、未評価対象を選べることを確認する。"""
        payload = json.loads(kwargs["user"])
        assert payload["observation"]["result"]["items"] == []
        return AgentAction(
            operation="evaluate", target_ids=payload["state"]["unchecked_targets"]
        )

    answers = [
        AgentAction(operation="read", references={"source": ["en"]}),
        AgentAction(operation="search", role="translation", query="三つ"),
        AgentAction(operation="match", references=refs),
        matched(),
        AgentAction(operation="overview"),
        after_overview,
        evaluation("二つ。", "四つ。"),
        after_conflict,
        evaluation("二つ。"),
        AgentAction(operation="finish"),
    ]
    calls = scripted(monkeypatch, answers)
    directory = tmp_path / "review" / "review"
    result = ReviewAgent(documents, directory, tmp_path, config).run()
    assert not answers
    assert len(result.groups) == 1
    assert len(result.revisions) == 1
    assert result.revisions[0].edits[0].text == "二つ。"
    assert {role: value.model_dump() for role, value in documents.items()} == original
    assert len(completed_agent_calls(directory)) == 3
    assert (directory / "review.json").is_file()
    assert not list(tmp_path.rglob("*.docx"))
    before = len(calls)
    answers.append(AgentAction(operation="finish"))
    restored = ReviewAgent(
        documents,
        directory,
        tmp_path,
        config.model_copy(update={"openai_review_model": "changed"}),
    ).run()
    assert restored == result
    assert len(calls) == before + 1


@pytest.mark.parametrize("operation", ["review", "upgrade"])
def test_agent_rejects_premature_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config, operation: str
) -> None:
    """未確認対象がある終了宣言を拒否し、最終成果物を公開しない。"""
    scripted(monkeypatch, [AgentAction(operation="finish")])
    if operation == "review":
        operation_call = ReviewAgent(
            {"source": document(en="Text"), "translation": document(ja="訳")},
            tmp_path,
            tmp_path,
            config,
        )
    else:
        operation_call = UpgradeAgent(
            {
                "source_v1": document(old="Old"),
                "source_v2": document(new="New"),
                "translation_v1": document(ja="訳"),
            },
            tmp_path,
            config,
        )
    with pytest.raises(InputError, match="cannot finish"):
        operation_call.run()
    assert not (tmp_path / "review.json").exists()
    assert not (tmp_path / "plan.json").exists()


def test_invalid_review_edit_is_failed_before_cache_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """選択した比較対象に属さないSpanの修正を成功保存しない。"""
    bad = evaluation("二つ。")
    bad.assessments[0].edits[0].span_id = "unknown/span"
    answers = [
        AgentAction(
            operation="match",
            references={"source": ["en"], "translation": ["ja1", "ja2"]},
        ),
        matched(),
        AgentAction(operation="evaluate", target_ids=["review/alignment-000001"]),
        bad,
    ]
    scripted(monkeypatch, answers)
    documents = {
        "source": document(en="Two"),
        "translation": document(ja1="訳", ja2="三つ"),
    }
    with pytest.raises(ValueError, match="unowned span"):
        ReviewAgent(documents, tmp_path, tmp_path, config).run()
    artifacts = [
        load_model(path, LLMCallArtifact) for path in tmp_path.glob("calls/*/call.json")
    ]
    assert sorted(item.status for item in artifacts) == ["failed", "succeeded"]
    assert not (tmp_path / "review.json").exists()


def test_upgrade_covers_unchanged_but_only_lists_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """変更・削除・追加と旧訳対応を保持し、未変更は確認範囲だけに残す。"""
    documents = {
        "source_v1": document(old="One", same="Keep", deleted="Delete"),
        "source_v2": document(new="Two", same2="Keep", added="Add"),
        "translation_v1": document(ja="一つ", keep="維持", remove="削除"),
    }
    response = DiffResponse.model_validate(
        {
            "changes": [
                {
                    "kind": "modified",
                    "source_v1_ids": ["old"],
                    "source_v2_ids": ["new"],
                    "translation_v1_ids": ["ja"],
                    "summary": "数値変更",
                    "suggested_translation": "二つ",
                },
                {
                    "kind": "unchanged",
                    "source_v1_ids": ["same"],
                    "source_v2_ids": ["same2"],
                    "translation_v1_ids": ["keep"],
                    "summary": "変更なし",
                },
                {
                    "kind": "deleted",
                    "source_v1_ids": ["deleted"],
                    "summary": "旧訳の該当箇所を削除",
                    "translation_v1_ids": ["remove"],
                },
                {
                    "kind": "added",
                    "source_v2_ids": ["added"],
                    "summary": "追加",
                    "suggested_translation": "追加する",
                },
            ],
            "reviewed_source_v1_ids": ["old", "same", "deleted"],
            "reviewed_source_v2_ids": ["new", "same2", "added"],
        }
    )

    def after_overview(kwargs: dict[str, object]) -> AgentAction:
        """確認済み英文と対応済み旧訳を新しい比較の概要から除く。"""
        items = json.loads(kwargs["user"])["observation"]["result"]["items"]
        assert items == []
        return AgentAction(operation="finish")

    answers = [
        AgentAction(
            operation="evaluate",
            references={
                role: [block.content.id for block in doc.pages[0].blocks]
                for role, doc in documents.items()
            },
        ),
        response,
        AgentAction(operation="overview"),
        after_overview,
    ]
    calls = scripted(monkeypatch, answers)
    result = UpgradeAgent(documents, tmp_path, config).run()
    assert [item.kind for item in result.changes] == ["modified", "deleted", "added"]
    assert "same" in result.reviewed_source_v1_ids
    assert result.changes[0].suggested_translation == "二つ"
    assert (tmp_path / "plan.json").is_file()
    assert not list(tmp_path.rglob("*.docx"))
    before = len(calls)
    answers.append(AgentAction(operation="finish"))
    assert UpgradeAgent(documents, tmp_path, config).run() == result
    assert len(calls) == before + 1


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
    ("remaining_role", "change_kind"),
    [("source_v1", "deleted"), ("source_v2", "added")],
)
def test_upgrade_classifies_one_sided_units_after_repeated_diff_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    remaining_role: str,
    change_kind: str,
) -> None:
    """片側比較が3回失敗した残りを追加・削除として記録し、旧訳対応を推測しない。"""
    documents = {
        "source_v1": document(
            **({"old": "Removed"} if remaining_role == "source_v1" else {})
        ),
        "source_v2": document(
            **({"new": "Added"} if remaining_role == "source_v2" else {})
        ),
        "translation_v1": document(ja="旧訳"),
    }

    def failed_diff(_kwargs: dict[str, object]) -> BaseModel:
        """DIFFが構造化応答を3回続けて返せない状況を再現する。"""
        message = "Invalid diff response"
        raise LLMInvalidResponseError(message)

    answers = [
        item
        for _ in range(3)
        for item in (
            AgentAction(
                operation="match",
                references={
                    remaining_role: ["old" if remaining_role == "source_v1" else "new"]
                },
            ),
            failed_diff,
        )
    ]
    answers.append(AgentAction(operation="finish"))
    scripted(monkeypatch, answers)

    result = UpgradeAgent(documents, tmp_path, config).run()

    assert len(result.changes) == 1
    assert result.changes[0].kind == change_kind
    assert result.changes[0].translation_v1_ids == []
    assert "未確認" in result.changes[0].summary
    assert result.reviewed_source_v1_ids == list(
        agent_units({"source_v1": documents["source_v1"]})["source_v1"]
    )
    assert result.reviewed_source_v2_ids == list(
        agent_units({"source_v2": documents["source_v2"]})["source_v2"]
    )


def test_upgrade_classifies_one_sided_units_after_idle_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """相手版が確認済みの残りを無進捗が続いた後に対応未確認で記録する。"""
    documents = {
        "source_v1": document(old1="Kept", old2="Removed"),
        "source_v2": document(new="Kept"),
        "translation_v1": document(ja="旧訳"),
    }
    answers = [
        AgentAction(
            operation="match",
            references={"source_v1": ["old1"], "source_v2": ["new"]},
        ),
        DiffResponse.model_validate(
            {
                "changes": [
                    {
                        "kind": "unchanged",
                        "source_v1_ids": ["old1"],
                        "source_v2_ids": ["new"],
                        "summary": "同じ内容",
                    }
                ],
                "reviewed_source_v1_ids": ["old1"],
                "reviewed_source_v2_ids": ["new"],
            }
        ),
        *[AgentAction(operation="overview") for _ in range(12)],
        AgentAction(operation="finish"),
    ]
    scripted(monkeypatch, answers)

    result = UpgradeAgent(documents, tmp_path, config).run()

    assert len(result.changes) == 1
    assert result.changes[0].kind == "deleted"
    assert result.changes[0].source_v1_ids == ["old2"]
    assert result.changes[0].translation_v1_ids == []
    assert "未確認" in result.changes[0].summary
    assert result.reviewed_source_v1_ids == ["old1", "old2"]
    assert result.reviewed_source_v2_ids == ["new"]


def test_upgrade_finishes_after_covered_sources_make_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """全英文が確認済みなら、12回無進捗の後にAgentの終了宣言を待たず確定する。"""
    documents = {
        "source_v1": document(old="Original"),
        "source_v2": document(new="Original"),
        "translation_v1": document(ja="原文"),
    }
    answers = [
        AgentAction(
            operation="match",
            references={"source_v1": ["old"], "source_v2": ["new"]},
        ),
        DiffResponse.model_validate(
            {
                "changes": [
                    {
                        "kind": "unchanged",
                        "source_v1_ids": ["old"],
                        "source_v2_ids": ["new"],
                        "summary": "変更なし",
                    }
                ],
                "reviewed_source_v1_ids": ["old"],
                "reviewed_source_v2_ids": ["new"],
            }
        ),
        *[AgentAction(operation="overview") for _ in range(12)],
    ]
    scripted(monkeypatch, answers)

    result = UpgradeAgent(documents, tmp_path, config).run()

    assert not answers
    assert result.changes == []
    assert result.reviewed_source_v1_ids == ["old"]
    assert result.reviewed_source_v2_ids == ["new"]
    assert (tmp_path / "plan.json").is_file()


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
        for role, ids in expected.items():
            selected = fields[f"{role}_ids"]
            if ids:
                assert selected["items"]["enum"] == ids
            else:
                assert selected["maxItems"] == 0
            if role != "translation_v1":
                reviewed = schema["properties"][f"reviewed_{role}_ids"]
                assert reviewed["minItems"] == reviewed["maxItems"] == len(ids)
                if ids:
                    assert reviewed["items"]["enum"] == ids
        return DiffResponse.model_validate(
            {
                "changes": [
                    {
                        "kind": {"source_v1": "added", "source_v2": "deleted"}.get(
                            empty_role, "unchanged"
                        ),
                        **{f"{role}_ids": ids for role, ids in expected.items()},
                        "summary": "選択範囲の比較",
                    }
                ],
                "reviewed_source_v1_ids": expected["source_v1"],
                "reviewed_source_v2_ids": expected["source_v2"],
            }
        )

    scripted(monkeypatch, [answer])
    client = LLMClient(config)
    try:
        task = import_module("translate.tasks.21_diff").DiffTask(
            client, tmp_path, "", ""
        )
        task.run(units, "match", 0)
    finally:
        client.client.close()


@pytest.mark.parametrize("rejected", [None, "match", "evaluate", "used_translation"])
def test_upgrade_advances_translation_candidates_after_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    rejected: str | None,
) -> None:
    """確定済み対象の再選択を訂正し、旧訳の重複対応を防いで比較・再開を完了する。"""
    documents = {
        "source_v1": document(old1="First", old2="Second"),
        "source_v2": document(new1="First", new2="Second"),
        "translation_v1": document(ja1="一つ目", ja2="二つ目"),
    }

    def select_candidates(kwargs: dict[str, object]) -> AgentAction:
        """Agentへ渡された未確認英文と先頭の旧訳候補を選ぶ。"""
        state = json.loads(kwargs["user"])["state"]
        if not any(state["pending_counts"].values()):
            assert state["translation_candidates"] == []
            return AgentAction(operation="finish")
        return AgentAction(
            operation="match",
            references={
                **{role: ids[:1] for role, ids in state["pending_ids"].items()},
                "translation_v1": state["translation_candidates"][:1],
            },
        )

    answers = []
    for index in (1, 2):
        answers.extend(
            [
                select_candidates,
                DiffResponse.model_validate(
                    {
                        "changes": [
                            {
                                "kind": "unchanged",
                                "source_v1_ids": [f"old{index}"],
                                "source_v2_ids": [f"new{index}"],
                                "translation_v1_ids": [f"ja{index}"],
                                "summary": "変更なし",
                            }
                        ],
                        "reviewed_source_v1_ids": [f"old{index}"],
                        "reviewed_source_v2_ids": [f"new{index}"],
                    }
                ),
            ]
        )
    if rejected is None:

        def after_overview(kwargs: dict[str, object]) -> AgentAction:
            """未確認の各文書候補だけを表示し、使用済み旧訳は本文取得できる。"""
            items = json.loads(kwargs["user"])["observation"]["result"]["items"]
            assert {(item["role"], item["id"]) for item in items} == {
                ("source_v1", "old2"),
                ("source_v2", "new2"),
                ("translation_v1", "ja2"),
            }
            return AgentAction(operation="read", references={"translation_v1": ["ja1"]})

        def after_read(kwargs: dict[str, object]) -> AgentAction:
            """候補から除いた旧訳も再確認用に読めることを確認して比較を進める。"""
            items = json.loads(kwargs["user"])["observation"]["result"]["items"]
            assert [item["text"] for item in items] == ["一つ目"]
            return select_candidates(kwargs)

        answers[2:3] = [AgentAction(operation="overview"), after_overview, after_read]
    else:
        references = {
            "source_v1": ["old2" if rejected == "used_translation" else "old1"],
            "source_v2": ["new2" if rejected == "used_translation" else "new1"],
            "translation_v1": ["ja1"],
        }

        def after_rejection(kwargs: dict[str, object]) -> AgentAction:
            """拒否理由を受け取り、確定済み対応を維持したまま次の組へ進める。"""
            value = json.loads(kwargs["user"])
            assert "recheck" in value["observation"]["result"]["error"].lower()
            assert value["state"]["pending_ids"] == {
                "source_v1": ["old2"],
                "source_v2": ["new2"],
            }
            assert value["state"]["translation_candidates"] == ["ja2"]
            return select_candidates(kwargs)

        answers[2:3] = [
            AgentAction(
                operation="match" if rejected == "used_translation" else rejected,
                references=references,
            ),
            after_rejection,
        ]
    answers.append(select_candidates)
    calls = scripted(monkeypatch, answers)
    result = UpgradeAgent(documents, tmp_path, config).run()
    assert not result.changes
    assert result.reviewed_source_v1_ids == ["old1", "old2"]
    assert result.reviewed_source_v2_ids == ["new1", "new2"]
    assert len(completed_agent_calls(tmp_path)) == 2
    assert not answers
    before = len(calls)
    answers.append(select_candidates)
    assert UpgradeAgent(documents, tmp_path, config).run() == result
    assert len(calls) == before + 1


def test_upgrade_reselects_after_diff_response_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    """不正Diff応答の対象を保持し、Agentの再選択後に比較を完了する。"""
    documents = {
        "source_v1": document(old1="First", old2="Second"),
        "source_v2": document(new1="First", new2="Second"),
        "translation_v1": document(ja1="一つ目", ja2="二つ目"),
    }
    diff_task = import_module("translate.pipeline.upgrade").DiffTask
    calls = 0

    def diff_run(
        _task: object,
        units: dict[str, list[TextUnit]],
        _operation: str,
        round_number: int,
    ) -> tuple[str, DiffResponse]:
        """最初のDiffを失敗させ、その後は指定範囲を変更なしと確認する。"""
        nonlocal calls
        calls += 1
        if calls == 1:
            message = "Invalid structured response"
            raise LLMInvalidResponseError(message)
        references = {
            role: [unit.id for unit in selected] for role, selected in units.items()
        }
        return (
            f"call-{round_number}",
            DiffResponse.model_validate(
                {
                    "changes": [
                        {
                            "kind": "unchanged",
                            **{f"{role}_ids": ids for role, ids in references.items()},
                            "summary": "変更なし",
                        }
                    ],
                    "reviewed_source_v1_ids": references["source_v1"],
                    "reviewed_source_v2_ids": references["source_v2"],
                }
            ),
        )

    monkeypatch.setattr(diff_task, "run", diff_run)

    def choose_first(_kwargs: dict[str, object]) -> AgentAction:
        """失敗する最初の比較対象を指定する。"""
        return AgentAction(
            operation="match",
            references={
                "source_v1": ["old1"],
                "source_v2": ["new1"],
                "translation_v1": ["ja1"],
            },
        )

    def retry_failed(kwargs: dict[str, object]) -> AgentAction:
        """失敗を採用せず、確定済み結果と未確認対象を保つ。"""
        value = json.loads(kwargs["user"])
        assert "invalid response" in value["observation"]["result"]["error"].lower()
        assert value["state"]["pending_ids"] == {
            "source_v1": ["old1", "old2"],
            "source_v2": ["new1", "new2"],
        }
        assert value["state"]["confirmed_count"] == 0
        return choose_first(kwargs)

    def choose_second(kwargs: dict[str, object]) -> AgentAction:
        """初回範囲の成功後、未確認範囲へ進む。"""
        value = json.loads(kwargs["user"])
        assert value["state"]["pending_ids"] == {
            "source_v1": ["old2"],
            "source_v2": ["new2"],
        }
        return AgentAction(
            operation="match",
            references={
                "source_v1": ["old2"],
                "source_v2": ["new2"],
                "translation_v1": ["ja2"],
            },
        )

    scripted(
        monkeypatch,
        [
            choose_first,
            retry_failed,
            choose_first,
            choose_second,
            AgentAction(operation="finish"),
        ],
    )
    result = UpgradeAgent(documents, tmp_path, config).run()

    assert calls == 3
    assert result.reviewed_source_v1_ids == ["old1", "old2"]
    assert result.reviewed_source_v2_ids == ["new1", "new2"]


@pytest.mark.parametrize("failure", [LLMInputExceededError, LLMInvalidResponseError])
def test_upgrade_halves_scope_after_diff_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    failure: type[Exception],
) -> None:
    """DIFF失敗後は許容対象数を半減し、残りの英文を確認する。"""
    documents = {
        "source_v1": document(old1="First", old2="Second"),
        "source_v2": document(new1="First", new2="Second"),
        "translation_v1": document(),
    }
    diff_task = import_module("translate.pipeline.upgrade").DiffTask
    calls = 0

    def diff_run(
        _task: object,
        units: dict[str, list[TextUnit]],
        _operation: str,
        round_number: int,
    ) -> tuple[str, DiffResponse]:
        """初回の対象群を入力超過にし、縮小後は選択範囲を変更なしとする。"""
        nonlocal calls
        calls += 1
        if calls == 1:
            message = "Selected document scope failed"
            raise failure(message)
        references = {
            role: [unit.id for unit in values] for role, values in units.items()
        }
        return (
            f"call-{round_number}",
            DiffResponse.model_validate(
                {
                    "changes": [
                        {
                            "kind": "unchanged",
                            "source_v1_ids": references["source_v1"],
                            "source_v2_ids": references["source_v2"],
                            "summary": "変更なし",
                        }
                    ],
                    "reviewed_source_v1_ids": references["source_v1"],
                    "reviewed_source_v2_ids": references["source_v2"],
                }
            ),
        )

    monkeypatch.setattr(diff_task, "run", diff_run)

    def first_action(_kwargs: dict[str, object]) -> AgentAction:
        """最初に予算を超える4件を選ぶ。"""
        return AgentAction(
            operation="match",
            references={
                "source_v1": ["old1", "old2"],
                "source_v2": ["new1", "new2"],
            },
        )

    def reduced_action(kwargs: dict[str, object]) -> AgentAction:
        """縮小後の上限と、次の判断へ渡す予算エラーを確認する。"""
        value = json.loads(kwargs["user"])
        assert value["state"]["max_reference_ids"] == 2
        assert "at most 2" in value["observation"]["result"]["error"]
        return AgentAction(
            operation="match",
            references={"source_v1": ["old1"], "source_v2": ["new1"]},
        )

    def remaining_action(kwargs: dict[str, object]) -> AgentAction:
        """縮小後も残りの英文がAgentの次の判断に含まれる。"""
        value = json.loads(kwargs["user"])
        assert value["state"]["max_reference_ids"] == 2
        assert value["state"]["pending_ids"]["source_v1"] == ["old2"]
        assert value["state"]["pending_ids"]["source_v2"] == ["new2"]
        return AgentAction(
            operation="match",
            references={"source_v1": ["old2"], "source_v2": ["new2"]},
        )

    scripted(
        monkeypatch,
        [
            first_action,
            reduced_action,
            remaining_action,
            AgentAction(operation="finish"),
        ],
    )
    result = UpgradeAgent(documents, tmp_path, config).run()

    assert calls == 3
    assert result.reviewed_source_v1_ids == ["old1", "old2"]
    assert result.reviewed_source_v2_ids == ["new1", "new2"]


def test_upgrade_stops_when_minimum_scope_exceeds_input_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """最小の一対も予算に収まらない場合は同じ比較を再実行しない。"""
    diff_task = import_module("translate.pipeline.upgrade").DiffTask

    def fail_diff(
        _task: object,
        _units: dict[str, list[TextUnit]],
        _operation: str,
        _round_number: int,
    ) -> tuple[str, DiffResponse]:
        """最小の比較範囲を入力超過として返す。"""
        message = "Selected document scope exceeds budget"
        raise LLMInputExceededError(message)

    monkeypatch.setattr(diff_task, "run", fail_diff)
    scripted(
        monkeypatch,
        [
            AgentAction(
                operation="match",
                references={"source_v1": ["old"], "source_v2": ["new"]},
            )
        ],
    )

    with pytest.raises(InputError, match="minimum two-unit DIFF scope"):
        UpgradeAgent(
            {
                "source_v1": document(old="First"),
                "source_v2": document(new="First"),
                "translation_v1": document(),
            },
            tmp_path,
            config,
        ).run()


def test_upgrade_can_refresh_overview_between_thirteen_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """未確認範囲が減る概要取得を反復しても、13群以上の比較を完了できる。"""
    documents = {
        role: document(**{f"unit-{index}": "Text" for index in range(13)})
        for role in ("source_v1", "source_v2", "translation_v1")
    }
    answers = []
    for index in range(13):
        references = {role: [f"unit-{index}"] for role in documents}
        answers.extend(
            [
                AgentAction(operation="overview"),
                AgentAction(operation="evaluate", references=references),
                DiffResponse.model_validate(
                    {
                        "changes": [
                            {
                                "kind": "unchanged",
                                **{
                                    f"{role}_ids": ids
                                    for role, ids in references.items()
                                },
                                "summary": "変更なし",
                            }
                        ],
                        "reviewed_source_v1_ids": references["source_v1"],
                        "reviewed_source_v2_ids": references["source_v2"],
                    }
                ),
            ]
        )
    answers.append(AgentAction(operation="finish"))
    scripted(monkeypatch, answers)
    result = UpgradeAgent(documents, tmp_path, config).run()
    assert len(result.reviewed_source_v1_ids) == 13
    assert len(result.reviewed_source_v2_ids) == 13
    assert not result.changes
    assert not answers


@pytest.mark.parametrize(("operation", "limit"), [("review", 12), ("upgrade", 36)])
def test_agent_stops_repeated_overview_without_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    operation: str,
    limit: int,
) -> None:
    """情報取得や対象指定を繰り返す進展のないAgentを上限回数で停止する。"""
    answers = [
        AgentAction(
            operation="overview",
        )
        for _ in range(limit)
    ]
    calls = scripted(monkeypatch, answers)
    if operation == "review":
        agent = ReviewAgent(
            {"source": document(en="Text"), "translation": document(ja="訳文")},
            tmp_path,
            tmp_path,
            config,
        )
    else:
        agent = UpgradeAgent(
            {
                "source_v1": document(old="Text"),
                "source_v2": document(new="Text"),
                "translation_v1": document(ja="訳文"),
            },
            tmp_path,
            config,
        )
    with pytest.raises(TimeoutError, match="step or time limit"):
        agent.run()
    assert len(calls) == limit
    assert not answers


@pytest.mark.parametrize("operation", ["review", "upgrade"])
def test_agent_retries_action_from_state_when_observation_exceeds_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    operation: str,
) -> None:
    """大きすぎる前回結果を捨てても保持済み状態からAgentを完了できる。"""
    module = import_module(f"translate.pipeline.{operation}")
    observations = []

    def choose_action(
        _client: LLMClient,
        _purpose: str,
        _state: dict[str, object],
        observation: object,
        _units: dict[str, dict[str, TextUnit]],
    ) -> AgentAction:
        """一回目は前回結果を大きくし、二回目で保持状態から終了する。"""
        observations.append(observation)
        if len(observations) == 1:
            error = "action context exceeds input limit"
            raise LLMInputExceededError(error)
        assert observation == {
            "error": (
                "Previous result exceeded the action input budget. "
                "No action was executed; choose from the current state."
            )
        }
        return AgentAction(operation="finish")

    monkeypatch.setattr(module, "choose_action", choose_action)
    documents = (
        {"source": document(), "translation": document()}
        if operation == "review"
        else {
            "source_v1": document(),
            "source_v2": document(),
            "translation_v1": document(),
        }
    )
    agent = (
        ReviewAgent(documents, tmp_path, tmp_path, config)
        if operation == "review"
        else UpgradeAgent(documents, tmp_path, config)
    )

    agent.run()

    assert len(observations) == 2
