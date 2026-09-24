"""TRANSLATE-LITE: LibreTranslateによる翻訳。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.adapters.libretranslate import translate_texts
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.tasks.base import BaseTask
from translate.tasks.check import protected_fragments
from translate.tasks.translate import apply_translations, units

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings
    from translate.document import Document


def _protect(text: str) -> tuple[str, dict[str, str]]:
    """翻訳対象の保護断片をmarkerへ置換し、送信後に原文へ戻すための対応表を返す。"""

    values: dict[str, str] = {}
    for index, fragment in enumerate(protected_fragments(text)):
        marker = f"__PROTECTED_{index}__"
        text = text.replace(fragment, marker)
        values[marker] = fragment
    return text, values


class TranslateLiteTask(BaseTask):
    """Execute TRANSLATE-LITE while sharing elapsed-time measurement only."""

    name = "TRANSLATE-LITE"

    def run(self, document: Document, settings: Settings, output_dir: Path) -> Document:
        """本文ページをLibreTranslateで翻訳する。"""

        with self.measure():
            result = document.model_copy(deep=True)
            for page in result.pages:
                if page.number == 1:
                    continue
                page_units = units(page)
                protected = [_protect(text) for _, text in page_units]
                translated = translate_texts(
                    settings.libretranslate_url or "",
                    settings.libretranslate_api_key,
                    [text for text, _ in protected],
                    retry_attempts=settings.retry_attempts,
                    retry_base_seconds=settings.retry_base_seconds,
                    retry_max_seconds=settings.retry_max_seconds,
                    timeout_seconds=settings.request_timeout_seconds,
                    deadline_seconds=settings.task_deadline_seconds,
                )
                mapping: dict[str, str] = {}
                for (key, _), translated_text, (_, markers) in zip(
                    page_units, translated, protected, strict=True
                ):
                    restored = translated_text
                    for marker, original in markers.items():
                        if marker not in restored:
                            msg = f"protected placeholder missing: {key}"
                            raise ValueError(msg)
                        restored = restored.replace(marker, original)
                    mapping[key] = restored
                apply_translations(page, mapping)
            with atomic_directory(output_dir) as temporary:
                for page in result.pages:
                    atomic_write_json(
                        temporary / f"page-{page.number:04d}.json",
                        page.model_dump(mode="json"),
                    )
            return result


def run(document: Document, settings: Settings, output_dir: Path) -> Document:
    """Existing function delegates to the typed TranslateLiteTask operation."""

    return TranslateLiteTask().run(document, settings, output_dir)
