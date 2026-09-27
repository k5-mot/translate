"""TRANSLATE: rules、用語集、RAGを使うLLM翻訳。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from translate_v1.adapters.llm import LLMError, structured
from translate_v1.adapters.qdrant import search
from translate_v1.common.workspace import atomic_directory, atomic_write_json
from translate_v1.document import Document, Inline, Page, page_text
from translate_v1.tasks.base import BaseTask
from translate_v1.tasks.check import GlossaryEntry, matching_glossary

if TYPE_CHECKING:
    from pathlib import Path

    from translate_v1.common.settings import Settings


class TranslationItem(BaseModel):
    """Inline IDと日本語訳。"""

    id: str
    text: str


class TranslationResponse(BaseModel):
    """一回のLLM応答。"""

    translations: list[TranslationItem] = Field(default_factory=list)


TranslationFailureCause = Literal["TranslationIdMismatch"]

_MAX_TRUNCATION_SPLIT_DEPTH = 2


def _is_text_output_truncated(error: LLMError) -> bool:
    """翻訳の代替経路へ切り替えられる出力枯渇だけを判定する。"""

    return (
        error.stage == "text-output"
        and error.failure_kind == "output-truncated"
        and error.finish_reason == "length"
    )


class TranslationOutputError(ValueError):
    """翻訳応答の形状だけを安全に分類する失敗。"""

    stage: Literal["text-parse"] = "text-parse"
    cause_type: TranslationFailureCause
    page: int
    target_id: str

    def __init__(
        self,
        cause_type: TranslationFailureCause,
        *,
        page: int,
        target_id: str,
    ) -> None:
        """翻訳出力検証の原因分類と対象だけを保持し、原文・応答の公開を防ぐ。"""

        self.cause_type = cause_type
        self.page = page
        self.target_id = target_id
        # Keep raw response, prompt, and source text out of
        # the exception and every downstream failure artifact.
        super().__init__("translation output validation failed")


def units(page: Page) -> list[tuple[str, str]]:
    """翻訳対象InlineをIDと原文の組にする。"""

    values: list[tuple[str, str]] = []
    for block in page.blocks:
        values.extend(
            (item.id, item.text)
            for item in block.source
            if item.text and item.kind != "code"
        )
        values.extend(
            (item.id, item.text)
            for item in block.caption
            if item.text and item.kind != "code"
        )
        for cell in block.cells:
            values.extend(
                (item.id, item.text)
                for item in cell.source
                if item.text and item.kind != "code"
            )
            values.extend(
                (item.id, item.text)
                for image in cell.images
                for item in image.caption
                if item.text and item.kind != "code"
            )
    return values


def apply_translations(page: Page, mapping: dict[str, str]) -> None:
    """ID対応をPageのtranslated layerへ反映する。"""

    def translated(values: list[Inline]) -> list[Inline]:
        """原文Inlineを複製してID対応の訳文を設定し、対応のない要素は元のtextを保持する。"""

        return [
            item.model_copy(
                update={
                    "text": item.text
                    if item.kind == "code"
                    else mapping.get(item.id, item.text)
                }
            )
            for item in values
        ]

    for block in page.blocks:
        block.translated = translated(block.source) if block.source else None
        block.translated_caption = translated(block.caption) if block.caption else None
        for cell in block.cells:
            cell.translated = translated(cell.source) if cell.source else None
            for image in cell.images:
                image.translated_caption = (
                    translated(image.caption) if image.caption else None
                )


def _chunks(
    values: list[tuple[str, str]], settings: Settings
) -> list[list[tuple[str, str]]]:
    # Note 1: The shared budget includes output, image, and tokenizer safety reserves.
    """原文の文字量と件数の上限でInline列を分割し、単一Inlineの分断は避ける。"""

    max_chars = min(4_000, max(1_000, settings.available_input_tokens * 2))
    result: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for item in values:
        item_size = len(item[1])
        if current and (len(current) >= 20 or size + item_size > max_chars):
            result.append(current)
            current = []
            size = 0
        current.append(item)
        size += item_size
    if current:
        result.append(current)
    return result


def _validated_mapping(
    response: TranslationResponse,
    chunk: list[tuple[str, str]],
    *,
    page: int,
    target_id: str,
) -> dict[str, str]:
    """応答を検証し、成功した場合だけ翻訳mappingを返す。"""

    received = {item.id: item.text.strip() for item in response.translations}
    expected = {key for key, _ in chunk}
    if set(received) != expected or any(not value for value in received.values()):
        raise TranslationOutputError(
            "TranslationIdMismatch", page=page, target_id=target_id
        )
    return received


def _translate_page(
    page: Page,
    previous: str,
    following: str,
    rules: str,
    glossary: list[GlossaryEntry],
    settings: Settings,
    qdrant_artifact_dir: Path,
) -> None:
    """ページ内のChunkを逐次翻訳し、全Chunk成功後にID対応の訳文を文書へ反映する。"""

    mapping: dict[str, str] = {}

    def translate_chunk(
        chunk: list[tuple[str, str]],
        chunk_label: str,
        *,
        split_depth: int = 0,
        force_no_reasoning: bool = False,
    ) -> dict[str, str]:
        """参照検索と翻訳を行い、出力検証・切断時の有限回復を経たID対応の訳文を返す。"""

        source = "\n".join(text for _, text in chunk)
        terms = [item.model_dump() for item in matching_glossary(source, glossary)]
        target_id = f"page-{page.number:04d}-chunk-{chunk_label}"
        evidence = search(
            settings,
            source[:2_000],
            artifact_path=(qdrant_artifact_dir / f"{target_id}.json"),
        )
        prompt = json.dumps(
            {
                "previous_context": previous[-2_000:],
                "target": [{"id": key, "text": text} for key, text in chunk],
                "following_context": following[:2_000],
                "glossary": terms,
                "references": evidence,
            },
            ensure_ascii=False,
        )

        def split_after_truncation(error: LLMError) -> dict[str, str]:
            """生成切断のときだけChunkを二分して逐次再送し、分割上限または単一要素なら失敗を伝える。"""

            if (
                not _is_text_output_truncated(error)
                or split_depth >= _MAX_TRUNCATION_SPLIT_DEPTH
                or len(chunk) <= 1
            ):
                raise error
            midpoint = len(chunk) // 2
            left = translate_chunk(
                chunk[:midpoint],
                f"{chunk_label}.0",
                split_depth=split_depth + 1,
                force_no_reasoning=True,
            )
            right = translate_chunk(
                chunk[midpoint:],
                f"{chunk_label}.1",
                split_depth=split_depth + 1,
                force_no_reasoning=True,
            )
            return left | right

        # Already-disabled requests go directly to finite splitting on truncation.
        force_no_reasoning = force_no_reasoning or settings.reasoning_mode == "off"
        attempts = max(1, settings.retry_attempts)
        truncation_fallback_used = False
        for attempt in range(attempts):
            try:
                if force_no_reasoning:
                    response = structured(
                        settings,
                        settings.translation_model or "",
                        TranslationResponse,
                        rules,
                        prompt,
                        reasoning="none",
                        thinking="disabled",
                    )
                else:
                    response = structured(
                        settings,
                        settings.translation_model or "",
                        TranslationResponse,
                        rules,
                        prompt,
                        reasoning="high",
                    )
            except LLMError as error:
                if force_no_reasoning or truncation_fallback_used:
                    return split_after_truncation(error)
                if not _is_text_output_truncated(error):
                    raise
                truncation_fallback_used = True
                # A local reasoning model may consume the whole generation budget
                # before emitting the translation JSON. Retry this chunk once with
                # both reasoning and provider thinking disabled; never parallelize
                # or retain the partial response.
                try:
                    response = structured(
                        settings,
                        settings.translation_model or "",
                        TranslationResponse,
                        rules,
                        prompt,
                        reasoning="none",
                        thinking="disabled",
                    )
                except LLMError as fallback_error:
                    return split_after_truncation(fallback_error)
            try:
                # Note 2: Stable Inline IDs prevent a fluent response from shifting translations.
                received = _validated_mapping(
                    response, chunk, page=page.number, target_id=target_id
                )
            except TranslationOutputError:
                if attempt + 1 >= attempts:
                    raise
                delay = min(
                    settings.retry_max_seconds,
                    settings.retry_base_seconds * (2**attempt),
                )
                if delay > 0:
                    time.sleep(delay)
            else:
                return received
        raise AssertionError("translation retry loop exhausted without a result")

    for chunk_number, chunk in enumerate(_chunks(units(page), settings), start=1):
        mapping.update(translate_chunk(chunk, f"{chunk_number:04d}"))
    apply_translations(page, mapping)


class TranslateTask(BaseTask):
    """Execute TRANSLATE while sharing elapsed-time measurement only."""

    name = "TRANSLATE"

    def run(
        self,
        document: Document,
        rules: str,
        glossary: list[GlossaryEntry],
        settings: Settings,
        output_dir: Path,
    ) -> Document:
        """第1ページ以外を逐次翻訳し、全ページ成功後に訳文と参照検索結果を公開する。"""

        with self.measure():
            result = document.model_copy(deep=True)
            source_pages = {page.number: page for page in result.pages}
            with atomic_directory(output_dir) as temporary:
                for page in result.pages:
                    if page.number == 1:
                        continue
                    _translate_page(
                        page,
                        page_text(
                            source_pages.get(page.number - 1, Page(number=0)),
                            final=False,
                        ),
                        page_text(
                            source_pages.get(page.number + 1, Page(number=0)),
                            final=False,
                        ),
                        rules,
                        glossary,
                        settings,
                        temporary / "qdrant",
                    )
                for page in result.pages:
                    atomic_write_json(
                        temporary / f"page-{page.number:04d}.json",
                        page.model_dump(mode="json"),
                    )
            return result


def run(
    document: Document,
    rules: str,
    glossary: list[GlossaryEntry],
    settings: Settings,
    output_dir: Path,
) -> Document:
    """Existing function delegates to the typed TranslateTask operation."""

    return TranslateTask().run(document, rules, glossary, settings, output_dir)
