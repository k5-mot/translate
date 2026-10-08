"""新しいCLIとPipeline再開境界を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner
from uuid_utils import uuid7

from translate.adapters.llm import LLMOutputExceededError, LLMOutputTokenExceededError
from translate.artifact_store import (
    begin_llm_call,
    complete_llm_call,
    fail_llm_call,
    load_reusable_llm_response,
)
from translate.cli import app
from translate.pipeline import InputError, resolve_processing_id
from translate.pipeline.register import _chunks, _validate_source_id
from translate.tasks.translation.translate import TranslationItem, TranslationResponse

if TYPE_CHECKING:
    from pathlib import Path


def test_cli_help_lists_only_public_commands() -> None:
    """CLIがTranslate、Review、Register、Upgradeを公開することを確認する。"""

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "translate" in result.stdout
    assert "review" in result.stdout
    assert "register" in result.stdout
    assert "upgrade" in result.stdout
    assert "publish" not in result.stdout


def test_cli_invalid_backend_returns_input_error(tmp_path: Path) -> None:
    """不正backendが外部接続前に終了code 2となることを確認する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"not-read-before-backend-validation")

    result = CliRunner().invoke(
        app,
        ["translate", str(source), "--backend", "unsupported"],
    )

    assert result.exit_code == 2
    assert "backend must be" in result.stderr


def test_cli_shows_llm_output_limit_and_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """出力上限で失敗したとき原因と対策をCLIへ表示する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"test")

    def fail(*_args: object, **_kwargs: object) -> None:
        """LLM出力上限エラーをPipeline境界から再現する。"""

        message = "出力トークン上限に到達。対策: 出力予算を増やす。"
        raise LLMOutputExceededError(message)

    monkeypatch.setattr("translate.cli.translate_pdf", fail)
    result = CliRunner().invoke(app, ["translate", str(source)])

    assert result.exit_code == 1
    assert "LLMOutputExceededError" in result.stderr
    assert "対策: 出力予算を増やす" in result.stderr


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

    value = "A" * 1200

    chunks = _chunks(value)

    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert chunks[0][-100:] == chunks[1][:100]


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
