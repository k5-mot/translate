"""TRANSLATE: rules、用語集、RAGを使うLLM翻訳。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from translate.adapters.llm import structured
from translate.adapters.qdrant import search
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.document import Document, Inline, Page, page_text
from translate.tasks.check import GlossaryEntry, matching_glossary, protected_fragments

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings


class TranslationItem(BaseModel):
    """Inline IDと日本語訳。"""

    id: str
    text: str


class TranslationResponse(BaseModel):
    """一回のLLM応答。"""

    translations: list[TranslationItem] = Field(default_factory=list)


TranslationFailureCause = Literal["TranslationIdMismatch", "ProtectedFragmentMissing"]


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
        self.cause_type = cause_type
        self.page = page
        self.target_id = target_id
        # Keep raw response, prompt, source text, and protected values out of
        # the exception and every downstream failure artifact.
        super().__init__("translation output validation failed")


def units(page: Page) -> list[tuple[str, str]]:
    """翻訳対象InlineをIDと原文の組にする。"""

    values: list[tuple[str, str]] = []
    for block in page.blocks:
        values.extend((item.id, item.text) for item in block.source if item.text)
        values.extend((item.id, item.text) for item in block.caption if item.text)
        for cell in block.cells:
            values.extend((item.id, item.text) for item in cell.source if item.text)
    return values


def apply_translations(page: Page, mapping: dict[str, str]) -> None:
    """ID対応をPageのtranslated layerへ反映する。"""

    def translated(values: list[Inline]) -> list[Inline]:
        return [
            item.model_copy(update={"text": mapping.get(item.id, item.text)})
            for item in values
        ]

    for block in page.blocks:
        block.translated = translated(block.source) if block.source else None
        block.translated_caption = translated(block.caption) if block.caption else None
        for cell in block.cells:
            cell.translated = translated(cell.source) if cell.source else None


def _chunks(
    values: list[tuple[str, str]], settings: Settings
) -> list[list[tuple[str, str]]]:
    # Note 1: The shared budget includes output, image, and tokenizer safety reserves.
    max_chars = min(4_000, max(1_000, settings.available_input_tokens * 2))
    result: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for item in values:
        if current and (len(current) >= 20 or size + len(item[1]) > max_chars):
            result.append(current)
            current = []
            size = 0
        current.append(item)
        size += len(item[1])
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
    for key, original in chunk:
        if any(value not in received[key] for value in protected_fragments(original)):
            raise TranslationOutputError(
                "ProtectedFragmentMissing", page=page, target_id=target_id
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
    mapping: dict[str, str] = {}
    for chunk_number, chunk in enumerate(_chunks(units(page), settings), start=1):
        source = "\n".join(text for _, text in chunk)
        terms = [item.model_dump() for item in matching_glossary(source, glossary)]
        target_id = f"page-{page.number:04d}-chunk-{chunk_number:04d}"
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
        attempts = max(1, settings.retry_attempts)
        for attempt in range(attempts):
            response = structured(
                settings,
                settings.translation_model or "",
                TranslationResponse,
                rules,
                prompt,
                reasoning="high",
            )
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
                break
        mapping.update(received)
    apply_translations(page, mapping)


def run(
    document: Document,
    rules: str,
    glossary: list[GlossaryEntry],
    settings: Settings,
    output_dir: Path,
) -> Document:
    """本文ページを高推論modelで翻訳する。"""

    start = time.perf_counter()
    result = document.model_copy(deep=True)
    source_pages = {page.number: page for page in result.pages}
    with atomic_directory(output_dir) as temporary:
        for page in result.pages:
            if page.number == 1:
                continue
            _translate_page(
                page,
                page_text(
                    source_pages.get(page.number - 1, Page(number=0)), final=False
                ),
                page_text(
                    source_pages.get(page.number + 1, Page(number=0)), final=False
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
    end = time.perf_counter()
    print(f"[TIME] TRANSLATE page=- group=-: {end - start:.3f} s")  # noqa: T201
    return result
