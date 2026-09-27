"""TRANSLATE-LITE: LibreTranslateによる翻訳。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate_v1.adapters.libretranslate import translate_texts
from translate_v1.common.workspace import atomic_directory, atomic_write_json
from translate_v1.tasks.base import BaseTask
from translate_v1.tasks.translate import apply_translations, units

if TYPE_CHECKING:
    from pathlib import Path

    from translate_v1.common.settings import Settings
    from translate_v1.document import Document


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
                translated = translate_texts(
                    settings.libretranslate_url or "",
                    settings.libretranslate_api_key,
                    [text for _, text in page_units],
                    retry_attempts=settings.retry_attempts,
                    retry_base_seconds=settings.retry_base_seconds,
                    retry_max_seconds=settings.retry_max_seconds,
                    timeout_seconds=settings.request_timeout_seconds,
                    deadline_seconds=settings.task_deadline_seconds,
                )
                mapping = {
                    key: text
                    for (key, _), text in zip(page_units, translated, strict=True)
                }
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
