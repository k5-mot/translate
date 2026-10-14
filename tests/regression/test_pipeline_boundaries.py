"""Pipelineの入力・再開境界を検証する。"""

from __future__ import annotations

import io
import json
import zipfile
from importlib import import_module
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from uuid_utils import uuid7

from translate.adapters.artifact_store import (
    begin_llm_call,
    complete_llm_call,
    fail_llm_call,
    load_model,
    load_reusable_llm_response,
)
from translate.adapters.embedding import EmbeddingError
from translate.adapters.llm import LLMOutputTokenExceededError
from translate.common.config import Config
from translate.models.artifacts import RegistrationRecord
from translate.pipeline import InputError, resolve_processing_id
from translate.pipeline.register import (
    _chunks,
    _docling_text,
    _validate_source_id,
    register_paths,
)

TranslationItem = import_module("translate.tasks.30_translate").TranslationItem
TranslationResponse = import_module("translate.tasks.30_translate").TranslationResponse

if TYPE_CHECKING:
    from pathlib import Path


def test_registration_extracts_table_cells_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docling ZIPの表本文を登録対象へ含め、grid表現やメタデータを二重抽出しない。"""
    cells = [{"text": "Term"}, {"text": "Definition in a merged cell"}]
    document = {
        "texts": [{"text": "Reference heading"}],
        "tables": [{"data": {"table_cells": cells, "grid": [cells, cells]}}],
        "pictures": [{"text": "Figure description"}],
        "origin": {"text": "Not document content"},
    }
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("document.json", json.dumps(document))
    monkeypatch.setattr(
        "translate.pipeline.register.DoclingClient.convert",
        MagicMock(return_value=(archive_bytes.getvalue(), "job", 1)),
    )
    text = _docling_text(
        tmp_path / "reference.pdf", Config(docling_server_url="http://docling")
    )
    assert text.count("Definition in a merged cell") == 1
    assert "Term" in text
    assert "Reference heading" in text
    assert "Figure description" in text
    assert "Not document content" not in text


def test_register_resume_clears_stale_failure_and_records_embedding_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Register再開中はprocessingを示し、再失敗時は具体的な対策を残す。"""

    source = tmp_path / "reference.pdf"
    source.write_text("reference", encoding="utf-8")
    config = Config(
        docling_server_url="http://docling",
        openai_base_url="http://embedding/v1",
        openai_embedding_model="embedding",
        qdrant_uri="http://qdrant",
        qdrant_collection="translation",
    )
    outputs = tmp_path / "outputs"
    processing_id = str(uuid7())

    def first_failure(*_args: object) -> None:
        """最初の登録をEmbedding失敗として記録する。"""

        message = "最初の接続失敗。対策: 接続先を確認してください。"
        raise EmbeddingError(message)

    monkeypatch.setattr("translate.pipeline.register._register_sources", first_failure)
    with pytest.raises(EmbeddingError):
        register_paths([source], config, outputs=outputs, processing_id=processing_id)
    record_path = outputs / "reference" / processing_id / "registration.json"
    failed = load_model(record_path, RegistrationRecord)
    assert failed.status == "failed"

    def resumed_failure(*_args: object) -> None:
        """再開中の記録と失敗理由の置換を確認する。"""

        active = load_model(record_path, RegistrationRecord)
        assert active.status == "processing"
        assert active.error is None
        assert active.updated_at > failed.updated_at
        message = "要求が時間切れです。対策: 負荷を確認してください。"
        raise EmbeddingError(message)

    monkeypatch.setattr(
        "translate.pipeline.register._register_sources", resumed_failure
    )
    with pytest.raises(EmbeddingError):
        register_paths([source], config, outputs=outputs, resume_id=processing_id)
    retried = load_model(record_path, RegistrationRecord)
    assert retried.status == "failed"
    assert retried.error is not None
    assert retried.error.message == "要求が時間切れです。対策: 負荷を確認してください。"


def test_llm_call_response_is_reused_only_with_matching_fingerprint(
    tmp_path: Path,
) -> None:
    """検証済み応答のhashとfingerprint一致時だけCallを再利用する。"""

    artifact = begin_llm_call(
        tmp_path,
        call_id="call-1",
        task="TRANSLATE",
        fingerprint="fingerprint",
        target_ids=["span-1"],
    )
    response = TranslationResponse(
        translations=[TranslationItem(span_id="span-1", text="訳")]
    )
    complete_llm_call(
        tmp_path,
        artifact,
        response,
        attempts=1,
        input_tokens=10,
        output_tokens=5,
    )

    reused = load_reusable_llm_response(
        tmp_path,
        call_id="call-1",
        fingerprint="fingerprint",
        response_type=TranslationResponse,
    )
    rejected = load_reusable_llm_response(
        tmp_path,
        call_id="call-1",
        fingerprint="changed",
        response_type=TranslationResponse,
    )

    assert reused is not None
    assert reused[1] == response
    assert rejected is None

    complete_llm_call(
        tmp_path,
        artifact,
        response,
        attempts=1,
        input_tokens=10,
        output_tokens=5,
        status="partial",
    )
    assert (
        load_reusable_llm_response(
            tmp_path,
            call_id="call-1",
            fingerprint="fingerprint",
            response_type=TranslationResponse,
        )
        is None
    )


def test_llm_call_artifact_keeps_safe_remedy(tmp_path: Path) -> None:
    """失敗ArtifactへLLM例外の分類と対策を保存する。"""

    artifact = begin_llm_call(
        tmp_path,
        call_id="call-1",
        task="TRANSLATE",
        fingerprint="fingerprint",
        target_ids=["span-1"],
    )
    error = LLMOutputTokenExceededError(
        "出力トークン上限です。対策: TRANSLATE_OUTPUT_TOKENSを増やしてください。"
    )

    failed = fail_llm_call(tmp_path, artifact, error, attempts=1)

    assert failed.error is not None
    assert failed.error.cause_type == "LLMOutputTokenExceededError"
    assert "対策: TRANSLATE_OUTPUT_TOKENS" in failed.error.message


def test_registration_chunk_limit_and_overlap() -> None:
    """登録chunkが1000文字以内で隣接部分を最大100文字重複させる。"""

    value = "A sentence. " * 120

    chunks = _chunks(value)

    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert len(chunks) > 1
    assert all(chunk.endswith(".") for chunk in chunks)
    assert chunks[0].endswith(chunks[1][:95].strip())
    with pytest.raises(InputError, match="sentence exceeds"):
        _chunks("A" * 1200)


@pytest.mark.parametrize("value", ["CON", "com1.txt", "..", "nested/path", "tail."])
def test_registration_source_id_rejects_unsafe_components(value: str) -> None:
    """Windows予約名を含む危険なsource-idを拒否する。"""

    with pytest.raises(InputError, match="safe single path"):
        _validate_source_id(value)


def test_processing_id_accepts_one_uuidv7_source() -> None:
    """UI新規IDとResume IDのいずれか一方だけを受け付ける。"""

    processing_id = str(uuid7())
    resume_id = str(uuid7())

    assert resolve_processing_id(processing_id, None) == processing_id
    assert resolve_processing_id(None, resume_id) == resume_id

    with pytest.raises(InputError, match="cannot be used together"):
        resolve_processing_id(processing_id, resume_id)


@pytest.mark.parametrize(
    "value",
    ["not-a-uuid", "00000000-0000-4000-8000-000000000000"],
)
def test_processing_id_rejects_non_uuidv7(value: str) -> None:
    """UIとResumeの処理IDを正規のUUIDv7に限定する。"""

    with pytest.raises(InputError, match="canonical UUIDv7"):
        resolve_processing_id(value, None)
