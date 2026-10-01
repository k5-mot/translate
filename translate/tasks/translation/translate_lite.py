"""LibreTranslateでTextSpanを翻訳するTRANSLATE-LITE Task。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.adapters.libretranslate import translate_texts
from translate.artifact_store import write_model
from translate.models.document import Document, iter_text_units

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.config import Config


def translate_lite(
    document: Document,
    task_directory: Path,
    config: Config,
) -> Document:
    """LLM Call成果を作らず、最大64件ずつ英語Spanを日本語へ翻訳する。

    Args:
        document (Document): 変換または検証対象のDocument。
        task_directory (Path): 対象Taskの成果物Directory。
        config (Config): 接続先、上限値および処理Optionを保持する設定。

    Returns:
        Document: LLM Call成果を作らず、最大64件ずつ英語Spanを日本語へ翻訳する。
    """

    updated = document.model_copy(deep=True)
    spans = [
        span
        for _, unit in iter_text_units(updated)
        for span in unit.spans
        if span.kind not in {"code", "line_break"}
        and span.translated is None
        and span.revised is None
    ]
    for first in range(0, len(spans), 64):
        batch = spans[first : first + 64]
        translated = translate_texts([span.source for span in batch], config)
        for span, text in zip(batch, translated, strict=True):
            span.translated = text
    task_directory.mkdir(parents=True, exist_ok=True)
    write_model(task_directory / "document.json", updated)
    return updated
