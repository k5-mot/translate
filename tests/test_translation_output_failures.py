from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from translate_v1.adapters.llm import LLMError, LLMOutputTruncatedError
from translate_v1.common.lifecycle import FailureRecord, _safe_diagnostics
from translate_v1.common.settings import load_settings, read_rules
from translate_v1.common.terminal_evidence import evidence_from_failure
from translate_v1.document import Block, Document, Inline, Page
from translate_v1.tasks import translate

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate_v1.common.settings import Settings


def _page(text: str = "Source") -> Page:
    """固定IDのInlineを持つページを作り、翻訳出力と失敗位置を照合可能にする。"""

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
    """指定個数のInlineを用意し、Chunk二分と処理順をIDごとに検証できるようにする。"""

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


@pytest.mark.parametrize(
    "instruction",
    [
        "targetだけ",
        "すべてのid",
        "空でない訳文",
    ],
)
def test_shipped_translation_rules_describe_target_contract(
    instruction: str,
) -> None:
    """実loaderが読む配布指示に、対象と応答IDの扱いが明記されているか確認する。"""

    rules = read_rules(load_settings("convert", env={}), "translation")
    assert instruction in rules
    assert "__PROTECTED_" not in rules


@pytest.mark.parametrize("mode", ["task-default", "off"])
@pytest.mark.parametrize("route", ["initial", "retry", "split"])
def test_shipped_rules_reach_all_plain_translation_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    mode: str,
    route: str,
) -> None:
    """配布指示と所属IDが通常・欠落retry・逐次分割で保たれることをTask境界で検査する。"""

    settings = settings_factory(
        templates_dir=load_settings("convert", env={}).templates_dir,
        reasoning_mode=mode,
        retry_attempts=2,
        retry_base_seconds=0,
    )
    rules = read_rules(settings, "translation")
    sources = [
        "U.S. provides guidance.",
        "Visit https://example.invalid/guide for details.",
        "https://example.invalid/only",
        "Compare first.ini and second.ini here.",
    ]
    page = _page_with_units(len(sources))
    for inline, source in zip(page.blocks[0].source, sources, strict=True):
        inline.text = source
    calls: list[list[str]] = []
    policies: list[tuple[object, object]] = []
    truncations = 1 if mode == "off" else 2

    def structured(*args: object, **kwargs: object) -> translate.TranslationResponse:
        """原文のままの要求を捕捉し、略語を訳した応答と指定経路の不正応答を返す。"""

        assert args[3] == rules
        payload = json.loads(str(args[4]))
        target = payload["target"]
        calls.append([item["id"] for item in target])
        policies.append((kwargs.get("reasoning"), kwargs.get("thinking")))
        assert "protected_placeholders" not in payload
        assert all(item["text"] in sources for item in target)
        assert payload["previous_context"] == "Context only"
        assert payload["following_context"] == "Following only"
        if route == "split" and len(calls) <= truncations:
            stage = "text-output"
            raise LLMError(
                stage,
                LLMOutputTruncatedError(),
                failure_kind="output-truncated",
                finish_reason="length",
            )
        response = translate.TranslationResponse(
            translations=[
                translate.TranslationItem(
                    id=item["id"], text="訳 " + item["text"].replace("U.S.", "米国")
                )
                for item in target
            ]
        )
        if route == "retry" and len(calls) == 1:
            response.translations[0].text = ""
        return response

    # No service request is made: only the actual translation Task is exercised.
    monkeypatch.setattr(translate, "structured", structured)
    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    translate._translate_page(  # noqa: SLF001
        page, "Context only", "Following only", rules, [], settings, tmp_path / "qdrant"
    )
    translated = page.blocks[0].translated
    assert translated is not None
    assert [(item.id, item.text) for item in translated] == [
        (f"inline-{index}", "訳 " + source.replace("U.S.", "米国"))
        for index, source in enumerate(sources)
    ]
    ids = [f"inline-{index}" for index in range(len(sources))]
    assert calls == (
        [ids] * truncations + [ids[:2], ids[2:]]
        if route == "split"
        else [ids] * (2 if route == "retry" else 1)
    )
    assert policies == (
        [("none", "disabled")] * len(calls)
        if mode == "off"
        else [("high", None)] + [("none", "disabled")] * (len(calls) - 1)
        if route == "split"
        else [("high", None)] * len(calls)
    )


def test_translation_output_mismatch_retries_same_chunk_then_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """単一InlineのID不一致後に再送し、二回目の正しいIDの訳を採用する。"""

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
        """不整合応答と成功応答を順に返し、同じ翻訳Chunkの再試行回数を記録する。"""

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
        """最初の出力だけを切断させ、thinkingを無効にした一回の回復送信を検証する。"""

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


@pytest.mark.parametrize(
    "case",
    [
        (1, True, 1),
        (8, True, 3),
        (8, False, 1),
    ],
)
def test_reasoning_off_recovery_stays_finite_and_preserves_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    case: tuple[int, bool, int],
) -> None:
    """OFFの単一要素・深さ上限・非切断Errorを、重複再送や成功扱いせず停止する。"""

    unit_count, truncated, expected_calls = case
    calls = 0

    def structured(*_args: object, **kwargs: object) -> translate.TranslationResponse:
        """全要求のOFFを確認して同じ分類の失敗を返し、有限性を測る。"""

        nonlocal calls
        calls += 1
        assert kwargs["reasoning"] == "none"
        assert kwargs["thinking"] == "disabled"
        if truncated:
            stage = "text-output"
            raise LLMError(
                stage,
                LLMOutputTruncatedError(),
                failure_kind="output-truncated",
                finish_reason="length",
            )
        stage = "text-invoke"
        raise LLMError(stage, TimeoutError())

    monkeypatch.setattr(translate, "structured", structured)
    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    page = _page_with_units(unit_count)
    with pytest.raises(LLMError):
        translate._translate_page(  # noqa: SLF001
            page,
            "",
            "",
            "rules",
            [],
            settings_factory(reasoning_mode="off", retry_attempts=3),
            tmp_path / "qdrant",
        )
    assert calls == expected_calls
    assert page.blocks[0].translated is None


def test_translation_output_truncation_fallback_is_bounded_and_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """単一Inlineのfallbackも枯渇した場合は二回で停止し、本文なしの診断を返す。"""

    calls: list[tuple[str, str | None]] = []

    def structured(*_args: object, **kwargs: object) -> translate.TranslationResponse:
        """常に出力切断を返し、thinking切替による回復回数が有限であることを調べる。"""

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


@pytest.mark.parametrize("mode", ["task-default", "off"])
def test_translation_output_truncation_splits_chunk_sequentially(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    mode: str,
) -> None:
    """同じchunkのfallbackも枯渇したときはsub-chunkを順番に処理する。"""

    calls: list[tuple[str, str | None]] = []

    def structured(*_args: object, **kwargs: object) -> translate.TranslationResponse:
        """
        二回切断させた後は要求されたIDだけ翻訳し、Chunk二分後の逐次送信を検証する。
        """

        calls.append((str(kwargs.get("reasoning")), kwargs.get("thinking")))
        if len(calls) <= (1 if mode == "off" else 2):
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
        settings_factory(
            translation_model="translation", retry_attempts=3, reasoning_mode=mode
        ),
        tmp_path / "qdrant",
    )

    expected = [] if mode == "off" else [("high", None)]
    assert calls == expected + [("none", "disabled")] * 3
    assert page.blocks[0].translated is not None
    assert [item.text for item in page.blocks[0].translated] == [
        "Translated 0",
        "Translated 1",
        "Translated 2",
        "Translated 3",
    ]


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("recover", [False, True])
def test_empty_translation_retries_and_publishes_only_valid_translation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    *,
    split: bool,
    recover: bool,
) -> None:
    """通常・分割Chunkの空訳を有限retryし、失敗時は既存Artifactを保持する。"""

    calls: list[list[str]] = []

    def structured(*args: object, **_kwargs: object) -> translate.TranslationResponse:
        """分割用切断と空訳を順に返し、対象Chunkだけの逐次再送を記録する。"""

        target = json.loads(str(args[-1]))["target"]
        ids = [item["id"] for item in target]
        calls.append(ids)
        if split and len(calls) <= 2:
            stage = "text-output"
            raise LLMError(
                stage,
                LLMOutputTruncatedError(),
                failure_kind="output-truncated",
                finish_reason="length",
            )
        invalid = "inline-1" in ids and (not recover or calls.count(ids) == 1)
        return translate.TranslationResponse(
            translations=[
                translate.TranslationItem(
                    id=key,
                    text="" if invalid else "翻訳済み",
                )
                for key in ids
            ]
        )

    monkeypatch.setattr(translate, "structured", structured)
    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    page = _page_with_units(2) if split else _page()
    for inline in page.blocks[0].source:
        inline.text = "Plain source"
    document = Document(pages=[page])
    settings = settings_factory(
        translation_model="translation", retry_attempts=2, retry_base_seconds=0
    )
    output = tmp_path / "translate"
    output.mkdir()
    previous = output / "previous.json"
    previous.write_text("previous artifact", encoding="utf-8")

    if recover:
        result = translate.run(document, "rules", [], settings, output)
        assert not previous.exists()
        translated = result.pages[0].blocks[0].translated
        assert translated is not None
        assert [item.text for item in translated] == ["翻訳済み"] * len(
            page.blocks[0].source
        )
        assert (output / "page-0008.json").is_file()
    else:
        with pytest.raises(translate.TranslationOutputError) as captured:
            translate.run(document, "rules", [], settings, output)
        error = captured.value
        assert error.cause_type == "TranslationIdMismatch"
        assert error.target_id == (
            "page-0008-chunk-0001.1" if split else "page-0008-chunk-0001"
        )
        assert "PRIVATE" not in str(error)
        assert previous.read_text(encoding="utf-8") == "previous artifact"
        assert list(output.iterdir()) == [previous]

    assert calls == (
        [["inline-0", "inline-1"]] * 2 + [["inline-0"], ["inline-1"], ["inline-1"]]
        if split
        else [["inline-1"], ["inline-1"]]
    )
    assert document.pages[0].blocks[0].translated is None
    assert not list(tmp_path.glob(".translate.*"))


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


def test_empty_translation_failure_has_safe_terminal_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """空訳によるID応答不整合を、原文なしの診断としてEvidenceへ伝播する。"""

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        translate,
        "structured",
        lambda *_args, **_kwargs: translate.TranslationResponse(
            translations=[translate.TranslationItem(id="inline-1", text=" ")]
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
    assert error.cause_type == "TranslationIdMismatch"
    stage, cause = _safe_diagnostics(None, None, error)
    assert (stage, cause) == ("text-parse", "TranslationIdMismatch")

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
    assert evidence.cause_type == "TranslationIdMismatch"
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
