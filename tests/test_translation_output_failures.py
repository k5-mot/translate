from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from translate.adapters.llm import LLMError, LLMOutputTruncatedError
from translate.common.lifecycle import FailureRecord, _safe_diagnostics
from translate.common.terminal_evidence import evidence_from_failure
from translate.document import Block, Inline, Page
from translate.tasks import translate

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def _page(text: str = "Source") -> Page:
    return Page(
        number=8,
        blocks=[
            Block(
                id="body",
                order=0,
                kind="paragraph",
                source=[Inline(id="inline-1", text=text)],
            )
        ],
    )


def _page_with_units(count: int) -> Page:
    return Page(
        number=8,
        blocks=[
            Block(
                id="body",
                order=0,
                kind="paragraph",
                source=[
                    Inline(id=f"inline-{index}", text=f"Source {index}")
                    for index in range(count)
                ],
            )
        ],
    )


def test_translation_output_mismatch_retries_same_chunk_then_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """一時的なID不一致だけを同じchunkで再試行する。"""

    responses = iter(
        [
            translate.TranslationResponse(
                translations=[translate.TranslationItem(id="wrong", text="x")]
            ),
            translate.TranslationResponse(
                translations=[
                    translate.TranslationItem(id="inline-1", text="Translated")
                ]
            ),
        ]
    )
    calls: list[str] = []
    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])

    def structured(*_args: object, **_kwargs: object) -> translate.TranslationResponse:
        calls.append("llm")
        return next(responses)

    monkeypatch.setattr(translate, "structured", structured)
    page = _page()
    settings = settings_factory(
        translation_model="translation", retry_attempts=2, retry_base_seconds=0
    )
    translate._translate_page(  # noqa: SLF001
        page, "", "", "rules", [], settings, tmp_path / "qdrant"
    )

    assert calls == ["llm", "llm"]
    assert page.blocks[0].translated is not None
    assert page.blocks[0].translated[0].text == "Translated"


def test_translation_output_truncation_retries_once_with_thinking_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """出力枯渇時は同じchunkを推論無効化で一回だけ逐次再送する。"""

    calls: list[tuple[str, str | None]] = []

    def structured(*_args: object, **kwargs: object) -> translate.TranslationResponse:
        calls.append((str(kwargs.get("reasoning")), kwargs.get("thinking")))
        if len(calls) == 1:
            stage = "text-output"
            raise LLMError(
                stage,
                LLMOutputTruncatedError(),
                failure_kind="output-truncated",
                finish_reason="length",
                input_tokens=2_144,
                output_tokens=16_384,
                total_tokens=18_528,
            )
        return translate.TranslationResponse(
            translations=[translate.TranslationItem(id="inline-1", text="Translated")]
        )

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(translate, "structured", structured)
    page = _page()
    translate._translate_page(  # noqa: SLF001
        page,
        "",
        "",
        "rules",
        [],
        settings_factory(translation_model="translation", retry_attempts=3),
        tmp_path / "qdrant",
    )

    assert calls == [("high", None), ("none", "disabled")]
    assert page.blocks[0].translated is not None
    assert page.blocks[0].translated[0].text == "Translated"


def test_translation_output_truncation_fallback_is_bounded_and_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """fallbackの再枯渇は追加要求せず、本文なしの診断へ伝播する。"""

    calls: list[tuple[str, str | None]] = []

    def structured(*_args: object, **kwargs: object) -> translate.TranslationResponse:
        calls.append((str(kwargs.get("reasoning")), kwargs.get("thinking")))
        stage = "text-output"
        raise LLMError(
            stage,
            LLMOutputTruncatedError(),
            failure_kind="output-truncated",
            finish_reason="length",
            input_tokens=2_144,
            output_tokens=16_384,
            total_tokens=18_528,
        )

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(translate, "structured", structured)
    with pytest.raises(LLMError) as captured:
        translate._translate_page(  # noqa: SLF001
            _page("PRIVATE source"),
            "",
            "",
            "rules",
            [],
            settings_factory(translation_model="translation", retry_attempts=3),
            tmp_path / "qdrant",
        )

    assert calls == [("high", None), ("none", "disabled")]
    assert captured.value.stage == "text-output"
    assert captured.value.failure_kind == "output-truncated"
    assert captured.value.finish_reason == "length"
    assert captured.value.output_tokens == 16_384
    assert "PRIVATE" not in str(captured.value)


def test_translation_output_truncation_splits_chunk_sequentially(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """同じchunkのfallbackも枯渇したときはsub-chunkを順番に処理する。"""

    calls: list[tuple[str, str | None]] = []

    def structured(*_args: object, **kwargs: object) -> translate.TranslationResponse:
        calls.append((str(kwargs.get("reasoning")), kwargs.get("thinking")))
        if len(calls) <= 2:
            stage = "text-output"
            raise LLMError(
                stage,
                LLMOutputTruncatedError(),
                failure_kind="output-truncated",
                finish_reason="length",
                input_tokens=2_144,
                output_tokens=16_384,
                total_tokens=18_528,
            )
        prompt = str(_args[-1])
        ids = [f'"id": "inline-{index}"' for index in range(4)]
        translations = [
            translate.TranslationItem(id=f"inline-{index}", text=f"Translated {index}")
            for index in range(4)
            if f'"id": "inline-{index}"' in prompt
        ]
        assert ids
        return translate.TranslationResponse(translations=translations)

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(translate, "structured", structured)
    page = _page_with_units(4)
    translate._translate_page(  # noqa: SLF001
        page,
        "",
        "",
        "rules",
        [],
        settings_factory(translation_model="translation", retry_attempts=3),
        tmp_path / "qdrant",
    )

    assert calls == [
        ("high", None),
        ("none", "disabled"),
        ("none", "disabled"),
        ("none", "disabled"),
    ]
    assert page.blocks[0].translated is not None
    assert [item.text for item in page.blocks[0].translated] == [
        "Translated 0",
        "Translated 1",
        "Translated 2",
        "Translated 3",
    ]


def test_split_fallback_restores_protected_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """split sub-chunkのplaceholderは応答後に元fragmentへ復元する。"""

    calls = 0

    def structured(*_args: object, **_kwargs: object) -> translate.TranslationResponse:
        nonlocal calls
        calls += 1
        if calls <= 2:
            stage = "text-output"
            raise LLMError(
                stage,
                LLMOutputTruncatedError(),
                failure_kind="output-truncated",
                finish_reason="length",
                input_tokens=2_144,
                output_tokens=16_384,
                total_tokens=18_528,
            )
        prompt = str(_args[-1])
        match = re.search(r'"id": "(inline-[01])"', prompt)
        assert match is not None
        expected_placeholder = "__PROTECTED_0_0__"
        return translate.TranslationResponse(
            translations=[
                translate.TranslationItem(
                    id=match.group(1), text=f"Translated {expected_placeholder}"
                )
            ]
        )

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(translate, "structured", structured)
    page = _page_with_units(2)
    page.blocks[0].source[0].text = "See https://example.com/path"
    translate._translate_page(  # noqa: SLF001
        page,
        "",
        "",
        "rules",
        [],
        settings_factory(translation_model="translation", retry_attempts=2),
        tmp_path / "qdrant",
    )

    assert page.blocks[0].translated is not None
    assert page.blocks[0].translated[0].text == "Translated https://example.com/path"


def test_translation_output_mismatch_exhaustion_is_safe_and_classified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """ID不一致の上限到達時は本文なしの固定診断になる。"""

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        translate,
        "structured",
        lambda *_args, **_kwargs: translate.TranslationResponse(
            translations=[translate.TranslationItem(id="wrong", text="SECRET")]
        ),
    )
    settings = settings_factory(
        translation_model="translation", retry_attempts=2, retry_base_seconds=0
    )

    with pytest.raises(translate.TranslationOutputError) as captured:
        translate._translate_page(  # noqa: SLF001
            _page("PRIVATE source"),
            "",
            "",
            "rules",
            [],
            settings,
            tmp_path / "qdrant",
        )

    error = captured.value
    assert error.stage == "text-parse"
    assert error.cause_type == "TranslationIdMismatch"
    assert (error.page, error.target_id) == (8, "page-0008-chunk-0001")
    assert "SECRET" not in str(error)
    assert "PRIVATE" not in str(error)


def test_protected_fragment_failure_is_distinct_and_terminal_evidence_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """protected fragment欠落は別causeでEvidenceへ安全に伝播する。"""

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        translate,
        "structured",
        lambda *_args, **_kwargs: translate.TranslationResponse(
            translations=[translate.TranslationItem(id="inline-1", text="参照")]
        ),
    )
    settings = settings_factory(
        translation_model="translation", retry_attempts=1, retry_base_seconds=0
    )

    with pytest.raises(translate.TranslationOutputError) as captured:
        translate._translate_page(  # noqa: SLF001
            _page("See https://example.com"),
            "",
            "",
            "rules",
            [],
            settings,
            tmp_path / "qdrant",
        )

    error = captured.value
    assert error.cause_type == "ProtectedFragmentMissing"
    stage, cause = _safe_diagnostics(None, None, error)
    assert (stage, cause) == ("text-parse", "ProtectedFragmentMissing")

    failure = FailureRecord(
        run_id="01a0c97c-f5cf-7031-b808-4ad545133925",
        task="TRANSLATE",
        page=error.page,
        target_id=error.target_id,
        error_type=type(error).__name__,
        reason="TranslationOutputError",
        stage=stage,
        cause_type=cause,
        failed_at=datetime.now(UTC),
    )
    evidence = evidence_from_failure(failure, started_at=datetime.now(UTC))
    assert evidence.stage == "text-parse"
    assert evidence.cause_type == "ProtectedFragmentMissing"
    assert "example.com" not in evidence.model_dump_json()


def test_llm_invoke_stage_is_preserved_in_terminal_evidence() -> None:
    """LLM timeoutなどのinvoke段階もEvidenceから欠落させない。"""

    failure = FailureRecord(
        run_id="01a0c97c-f5cf-7031-b808-4ad545133925",
        task="TRANSLATE",
        error_type="LLMError",
        reason="LLMError",
        stage="text-invoke",
        cause_type="OpenAITimeoutError",
        failed_at=datetime.now(UTC),
    )
    evidence = evidence_from_failure(failure, started_at=datetime.now(UTC))
    assert evidence.stage == "text-invoke"
    assert evidence.cause_type == "OpenAITimeoutError"
