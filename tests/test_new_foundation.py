"""新しいtranslateパッケージの基盤契約を検証する。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from translate.adapters.llm import LLMClient
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
    """安全なcontextを超えるTask別token予算を拒否する。"""

    with pytest.raises(ValidationError):
        Config(
            llm_context_tokens=10000,
            structure_input_tokens=6144,
            structure_output_tokens=2048,
            llm_image_tokens=2048,
            llm_safety_tokens=1024,
        )


def test_partial_qdrant_settings_are_rejected() -> None:
    """任意RAGの部分設定を黙って無効化しないことを確認する。"""

    config = Config(qdrant_uri="http://qdrant")

    with pytest.raises(ConfigError):
        config.qdrant_enabled()


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


def test_llm_call_index_rejects_duplicate_ids() -> None:
    """集約進捗の正本となる採用Call一覧に重複を許可しない。"""

    with pytest.raises(ValidationError):
        LLMCallIndex(task="REVIEW", call_ids=["call-1", "call-1"])
