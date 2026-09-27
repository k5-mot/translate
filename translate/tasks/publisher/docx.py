"""Pandoc Markdownを最終DOCXとして公開するDOCX Task。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.adapters.pandoc import publish as publish_with_pandoc

if TYPE_CHECKING:
    from pathlib import Path


def publish(markdown: Path, output: Path, template: Path, timeout: float) -> Path:
    """Pandoc Adapterへ固定したDOCX公開契約を委譲する。"""

    return publish_with_pandoc(markdown, output, template, timeout)
