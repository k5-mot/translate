"""実際のAgent制御・保存・再開を、外部LLM応答だけ差し替えて検証する。"""

import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from translate.adapters.artifact_store import load_model
from translate.adapters.llm import LLMClient, StructuredResult
from translate.common.config import Config
from translate.models.artifacts import LLMCallArtifact
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.models.review import AgentAction, AlignmentResponse, ReviewResponse
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


def test_match_schema_requests_only_correspondence(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
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
                {"source_ids": ["en"], "translation_ids": ["ja"], "kind": "matched"}
            ]
        }
    )
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
        assert result.groups[0].translation_ids == ["ja"]
        create.assert_called_once()
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
            "reviewed_target_ids": ["review/alignment-000001"],
            "findings": [
                {
                    "category": "accuracy",
                    "severity": "warning",
                    "target_ids": ["ja2"],
                    "message": "数値を原文に合わせる",
                }
            ],
            "revisions": [
                {"target_id": "ja2", "edits": [{"span_id": "ja2/span", "text": text}]}
                for text in texts
            ],
        }
    )


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
    """選択group内でも別TextUnitのSpanを編集する応答を成功保存しない。"""
    bad = evaluation("二つ。")
    bad.revisions[0].target_id = "ja1"
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
        """確認済み英文を概要から除き、旧訳の参照は維持する。"""
        items = json.loads(kwargs["user"])["observation"]["result"]["items"]
        assert {item["role"] for item in items} == {"translation_v1"}
        assert {item["id"] for item in items} == {"ja", "keep", "remove"}
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
