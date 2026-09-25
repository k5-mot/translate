from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from translate.adapters.llm import LLMError, LLMOutputTruncatedError
from translate.common.lifecycle import FailureRecord, _safe_diagnostics
from translate.common.settings import load_settings, read_rules
from translate.common.terminal_evidence import evidence_from_failure
from translate.document import Block, Document, Inline, Page
from translate.tasks import translate

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


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
        "同じid",
        "__PROTECTED_<unit>_<fragment>__",
        "各1回",
        "一字も変更せず",
        "省略・重複・別idへの移動",
        "実値を推測",
        "本文の途中",
    ],
)
def test_shipped_translation_rules_describe_placeholder_contract(
    instruction: str,
) -> None:
    """実loaderが読む配布指示に、対象と保護記号の扱いが明記されているか確認する。"""

    rules = read_rules(load_settings("convert", env={}), "translation")
    assert instruction in rules


@pytest.mark.parametrize("mode", ["task-default", "off"])
@pytest.mark.parametrize("route", ["initial", "retry", "split"])
def test_shipped_rules_reach_all_protected_translation_requests(
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
        "Use config.yaml here.",
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
        """要求を捕捉し、指定経路だけ失敗させた後に記号を保持した合成訳を返す。"""

        assert args[3] == rules
        assert "同じid" in str(args[3])
        payload = json.loads(str(args[4]))
        target = payload["target"]
        calls.append([item["id"] for item in target])
        policies.append((kwargs.get("reasoning"), kwargs.get("thinking")))
        markers = re.findall(
            r"__PROTECTED_\d+_\d+__", " ".join(item["text"] for item in target)
        )
        assert sorted(markers) == payload["protected_placeholders"]
        assert len(markers) == len(set(markers))
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
                translate.TranslationItem(id=item["id"], text="訳 " + item["text"])
                for item in target
            ]
        )
        if route == "retry" and len(calls) == 1:
            response.translations[0].text = "欠落した訳"
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
        (f"inline-{index}", "訳 " + source) for index, source in enumerate(sources)
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


def test_protected_markers_moved_to_another_id_are_rejected() -> None:
    """全記号の個数が正しくても、別IDへ移した応答を最終対応検査で拒否する。"""

    chunk = [("first", "Use first.ini here."), ("second", "Use second.ini here.")]
    protected_chunk, protected = translate._protect_chunk_for_prompt(chunk)  # noqa: SLF001
    response = translate.TranslationResponse(
        translations=[
            translate.TranslationItem(id="first", text=protected_chunk[1][1]),
            translate.TranslationItem(id="second", text=protected_chunk[0][1]),
        ]
    )
    restored = translate._restore_chunk_placeholders(  # noqa: SLF001
        response, protected, page=2, target_id="synthetic-chunk"
    )
    with pytest.raises(translate.TranslationOutputError) as captured:
        translate._validated_mapping(  # noqa: SLF001
            restored, chunk, page=2, target_id="synthetic-chunk"
        )
    assert captured.value.cause_type == "ProtectedFragmentMissing"


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


def test_split_fallback_restores_protected_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """split sub-chunkのplaceholderは応答後に元fragmentへ復元する。"""

    calls = 0

    def structured(*_args: object, **_kwargs: object) -> translate.TranslationResponse:
        """二回切断後の分割要求へ保護markerを返し、分割ごとの保護断片復元を検証する。"""

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
        text = (
            "Translated __PROTECTED_0_0__"
            if match.group(1) == "inline-0"
            else "Translated"
        )
        return translate.TranslationResponse(
            translations=[translate.TranslationItem(id=match.group(1), text=text)]
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
    assert page.blocks[0].translated[1].text == "Translated"
    assert calls == 4


def test_normal_chunk_protects_and_restores_protected_fragments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """通常Chunkでも送信前にURLを保護し、応答後に元のURLが正確に戻ることを検証する。"""

    prompts: list[str] = []

    def structured(*_args: object, **_kwargs: object) -> translate.TranslationResponse:
        """
        URLがpromptの対象本文からmarkerへ置換されたことを確認し、復元対象のmarkerを返す
        。
        """

        prompt = str(_args[-1])
        prompts.append(prompt)
        assert "https://example.com/path" not in prompt
        assert "__PROTECTED_0_0__" in prompt
        return translate.TranslationResponse(
            translations=[
                translate.TranslationItem(
                    id="inline-1", text="Translated __PROTECTED_0_0__"
                )
            ]
        )

    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(translate, "structured", structured)
    page = _page("See https://example.com/path")
    translate._translate_page(  # noqa: SLF001
        page,
        "",
        "",
        "rules",
        [],
        settings_factory(translation_model="translation", retry_attempts=1),
        tmp_path / "qdrant",
    )

    assert len(prompts) == 1
    assert page.blocks[0].translated is not None
    assert page.blocks[0].translated[0].text == "Translated https://example.com/path"


def test_placeholder_variants_are_canonicalized_before_restoration() -> None:
    """
    空白・大小文字・区切りの揺れを含む保護markerが正規化され、原文へ戻ることを検証する。
    """

    response = translate.TranslationResponse(
        translations=[
            translate.TranslationItem(
                id="inline-1",
                text="Translated __ protected - 0 - 0 __",
            )
        ]
    )

    restored = translate._restore_chunk_placeholders(  # noqa: SLF001
        response,
        {"__PROTECTED_0_0__": "https://example.com/path"},
        page=8,
        target_id="page-0008-chunk-0001.0",
    )

    assert restored.translations[0].text == "Translated https://example.com/path"


@pytest.mark.parametrize(
    "text",
    [
        "Translated __PROTECTED_0_0__ __PROTECTED_0_0__",
        "Translated __PROTECTED_9_9__",
        "Translated without a protected value",
    ],
)
def test_placeholder_cardinality_and_unknown_tokens_fail_safely(
    text: str,
) -> None:
    """
    保護markerの個数不整合や未知tokenを拒否し、例外に保護対象の原文を含めないことを調べ
    る。
    """

    response = translate.TranslationResponse(
        translations=[translate.TranslationItem(id="inline-1", text=text)]
    )

    with pytest.raises(translate.TranslationOutputError) as captured:
        translate._restore_chunk_placeholders(  # noqa: SLF001
            response,
            {"__PROTECTED_0_0__": "https://example.com/path"},
            page=8,
            target_id="page-0008-chunk-0001.0",
        )

    assert captured.value.cause_type == "ProtectedFragmentMissing"
    assert "example.com" not in str(captured.value)


@pytest.mark.parametrize(
    "marker",
    [
        "__PROTECTED_9_9__",
        "__ protected - 9 - 9 __",
        # NFKCでcanonical markerになる全角英数字と下線を検査する。
        (
            "\uff3f\uff3f\uff30\uff32\uff2f\uff34\uff25\uff23\uff34\uff25\uff24"
            "\uff3f\uff19\uff3f\uff19\uff3f\uff3f"
        ),
    ],
)
def test_empty_protection_map_rejects_unknown_marker(marker: str) -> None:
    """保護対象のない応答でも、許容表記の未知markerを固定診断で拒否する。"""

    response = translate.TranslationResponse(
        translations=[
            translate.TranslationItem(id="inline-1", text=f"PRIVATE {marker}")
        ]
    )
    with pytest.raises(translate.TranslationOutputError) as captured:
        translate._restore_chunk_placeholders(  # noqa: SLF001
            response, {}, page=8, target_id="page-0008-chunk-0001"
        )

    error = captured.value
    assert (error.stage, error.cause_type) == ("text-parse", "ProtectedFragmentMissing")
    assert (error.page, error.target_id) == (8, "page-0008-chunk-0001")
    assert "PRIVATE" not in str(error)
    assert marker not in str(error)


def test_empty_protection_map_preserves_valid_response_without_normalization() -> None:
    """markerのない正常応答は全角文字・結合文字を含め変更せず返す。"""

    response = translate.TranslationResponse(
        translations=[
            translate.TranslationItem(
                id="inline-1", text="\uff21\uff22\uff23 \u2460 e\u0301"
            )
        ]
    )
    result = translate._restore_chunk_placeholders(  # noqa: SLF001
        response, {}, page=8, target_id="page-0008-chunk-0001"
    )
    assert result is response
    assert result.translations[0].text == "\uff21\uff22\uff23 \u2460 e\u0301"


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("recover", [False, True])
def test_unknown_marker_retries_and_publishes_only_valid_translation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    *,
    split: bool,
    recover: bool,
) -> None:
    """通常・分割Chunkの未知markerを有限retryし、失敗時は既存Artifactを保持する。"""

    calls: list[list[str]] = []

    def structured(*args: object, **_kwargs: object) -> translate.TranslationResponse:
        """分割用切断と未知markerを順に返し、対象Chunkだけの逐次再送を記録する。"""

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
                    text="PRIVATE __PROTECTED_9_9__" if invalid else "翻訳済み",
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
        assert error.cause_type == "ProtectedFragmentMissing"
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


def test_missing_placeholder_retries_before_failing_the_split_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """
    分割後の保護marker欠落を再試行で回復し、元のURLを保持して翻訳を完了するか検証する。
    """

    calls = 0

    def structured(*_args: object, **_kwargs: object) -> translate.TranslationResponse:
        """
        切断・分割後のmarker欠落・正常応答を順に返し、同じ分割単位の再試行と次単位への遷
        移を調べる。
        """

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
        if calls == 3:
            return translate.TranslationResponse(
                translations=[translate.TranslationItem(id="inline-0", text="欠落")]
            )
        if calls == 4:
            return translate.TranslationResponse(
                translations=[
                    translate.TranslationItem(
                        id="inline-0",
                        text="Translated __PROTECTED_0_0__",
                    )
                ]
            )
        assert '"id": "inline-1"' in prompt
        return translate.TranslationResponse(
            translations=[translate.TranslationItem(id="inline-1", text="Translated")]
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

    assert calls == 5
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
