"""新しいCLIとPipeline再開境界を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from translate.artifact_store import (
    begin_llm_call,
    complete_llm_call,
    load_reusable_llm_response,
)
from translate.cli import app
from translate.pipeline import InputError
from translate.pipeline.register import _chunks, _validate_source_id
from translate.tasks.translation.translate import TranslationItem, TranslationResponse

if TYPE_CHECKING:
    from pathlib import Path


def test_cli_help_lists_only_public_commands() -> None:
    """CLIがTranslate、Review、Registerだけを公開することを確認する。"""

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "translate" in result.stdout
    assert "review" in result.stdout
    assert "register" in result.stdout
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
