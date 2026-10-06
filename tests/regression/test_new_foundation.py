"""新しいtranslateパッケージの基盤契約を検証する。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError
from qdrant_client.http import models as qdrant_models

from translate.adapters import qdrant
from translate.adapters.llm import LLMClient, LLMInputExceededError
from translate.artifact_store import canonical_hash, load_model, write_model
from translate.common.config import Config, ConfigError, load_config
from translate.models.artifacts import ArtifactFile, LLMCallIndex, LLMTaskDiagnostics
from translate.models.document import Document, Page, TextSpan, TextUnit

if TYPE_CHECKING:
    from pathlib import Path


def test_models_ignore_unknown_fields_and_preserve_empty_translation() -> None:
    """未知fieldを捨て、空訳と未設定を区別することを確認する。"""

    span = TextSpan.model_validate(
        {"id": "span-1", "source": "source", "translated": "", "future": 1}
    )

    assert span.translated == ""
    assert span.text() == ""
    assert "future" not in span.model_dump()


def test_artifact_path_rejects_parent_traversal() -> None:
    """永続化する相対pathから親参照を排除する。"""

    with pytest.raises(ValidationError):
        ArtifactFile(relative_path="../secret", sha256="0" * 64, size_bytes=1)


def test_model_storage_round_trip(tmp_path: Path) -> None:
    """Pydantic成果物を原子的に保存して再検証できることを確認する。"""

    path = tmp_path / "task-structure.json"
    value = LLMTaskDiagnostics(
        task="STRUCTURE",
        diagnostics=[],
        updated_at=datetime.now(UTC),
    )

    write_model(path, value)
    loaded = load_model(path, LLMTaskDiagnostics)

    assert loaded == value
    assert path.read_bytes().endswith(b"\n")


def test_canonical_hash_is_independent_of_json_key_order() -> None:
    """構造化値のfingerprintがkey順へ依存しないことを確認する。"""

    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_config_environment_overrides_dotenv(tmp_path: Path) -> None:
    """process環境変数が.envより優先されることを確認する。"""

    (tmp_path / ".env").write_text("PDF_SPLIT_PAGES=5\n", encoding="utf-8")

    config = load_config(tmp_path, {"PDF_SPLIT_PAGES": "7"})

    assert config.pdf_split_pages == 7


def test_config_rejects_context_budget_overflow() -> None:
    """Task別token予算の超過を設定名と合計付きで拒否する。"""

    with pytest.raises(
        ValidationError,
        match=r"STRUCTURE token budget: .* = 11264 > LLM_CONTEXT_TOKENS=10000",
    ):
        Config(
            llm_context_tokens=10000,
            structure_input_tokens=6144,
            structure_output_tokens=2048,
            llm_image_tokens=2048,
            llm_safety_tokens=1024,
        )


def test_config_allows_output_above_previous_individual_limit() -> None:
    """各token設定が旧個別上限を超えてもcontext予算内なら許可する。"""

    assert Config(review_output_tokens=8192).review_output_tokens == 8192
    config = Config(
        llm_context_tokens=65536,
        llm_image_tokens=4096,
        llm_safety_tokens=5000,
        structure_input_tokens=10000,
        structure_output_tokens=8192,
        translate_input_tokens=10000,
        translate_output_tokens=8192,
        review_input_tokens=10000,
        review_output_tokens=16384,
    )
    assert config.review_output_tokens == 16384


def test_config_rejects_review_budget_over_context() -> None:
    """REVIEWの予算超過を個別上限ではなく合計で拒否する。"""

    with pytest.raises(
        ValidationError,
        match=r"REVIEW token budget: .* = 33216 > LLM_CONTEXT_TOKENS=30208",
    ):
        Config(review_output_tokens=24000)


def test_partial_qdrant_settings_are_rejected() -> None:
    """任意RAGの部分設定を黙って無効化しないことを確認する。"""

    config = Config(qdrant_uri="http://qdrant")

    with pytest.raises(ConfigError):
        config.qdrant_enabled()


def test_qdrant_registration_uses_bounded_upload_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """大量PointをQdrant clientの有限batch uploadへ委譲する。"""

    points = [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "vector": [0.0, 1.0],
            "payload": {"chunk_index": index},
        }
        for index in range(65)
    ]
    client = MagicMock()
    client.collection_exists.return_value = False
    client.retrieve.side_effect = [
        [],
        [MagicMock(id=point["id"]) for point in points],
    ]
    monkeypatch.setattr(
        qdrant,
        "_client",
        MagicMock(return_value=(client, qdrant_models)),
    )

    written = qdrant.upsert_revision(
        config=Config(
            qdrant_uri="http://qdrant",
            qdrant_collection="translation",
        ),
        source_key="source/sample.pdf",
        revision="revision",
        points=points,
        vector_size=2,
    )

    assert written is True
    client.upload_points.assert_called_once()
    assert client.upload_points.call_args.kwargs["batch_size"] == 64
    assert client.upload_points.call_args.kwargs["wait"] is True
    assert len(client.upload_points.call_args.kwargs["points"]) == 65
    client.upsert.assert_not_called()


def test_document_json_uses_schema_version_one() -> None:
    """Documentの永続化Schema versionとJSON互換性を確認する。"""

    document = Document(
        pages=[Page(number=1)],
        metadata={"unit": json.loads('{"kind":"sample"}')},
    )

    assert document.schema_version == 1
    assert TextUnit(id="unit", spans=[]).text() == ""


def test_llm_payload_disables_hidden_reasoning() -> None:
    """ローカルLLMのhidden reasoningを全structured要求で無効化する。"""

    client = LLMClient(Config(openai_base_url="http://llm"))

    payload = client._payload(  # noqa: SLF001
        model="model",
        system="system",
        user="user",
        contract="contract",
        native_schema={"type": "object"},
        output_tokens=128,
        image=None,
    )

    assert payload["reasoning_effort"] == "none"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["thinking_budget_tokens"] == 0
    assert payload["repetition_penalty"] == 1.01


def test_llm_rejects_oversized_complete_prompt_before_http() -> None:
    """本文以外のsystemと契約を含む実入力を送信前に制限する。"""

    client = LLMClient(Config(openai_base_url="http://llm"))

    with pytest.raises(LLMInputExceededError, match="task limit"):
        client.structured(
            model="model",
            response_type=LLMTaskDiagnostics,
            system="s" * 100,
            user="user",
            contract="contract",
            native_schema=LLMTaskDiagnostics.model_json_schema(),
            input_tokens=64,
            output_tokens=128,
        )


def test_llm_classifies_provider_context_error_for_task_splitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """endpointのcontext超過HTTP 400を通常のLLM失敗と区別する。"""

    response = httpx.Response(
        400,
        json={"error": {"message": "maximum context length exceeded"}},
        request=httpx.Request("POST", "http://llm/chat/completions"),
    )
    monkeypatch.setattr(httpx, "post", MagicMock(return_value=response))
    client = LLMClient(Config(openai_base_url="http://llm"))

    with pytest.raises(LLMInputExceededError, match="provider context"):
        client.structured(
            model="model",
            response_type=LLMTaskDiagnostics,
            system="system",
            user="user",
            contract="contract",
            native_schema=LLMTaskDiagnostics.model_json_schema(),
            input_tokens=8192,
            output_tokens=128,
        )


def test_llm_call_index_rejects_duplicate_ids() -> None:
    """集約進捗の正本となる採用Call一覧に重複を許可しない。"""

    with pytest.raises(ValidationError):
        LLMCallIndex(task="REVIEW", call_ids=["call-1", "call-1"])
