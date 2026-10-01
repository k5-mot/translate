"""Pandoc Markdownを最終DOCXとして公開するDOCX Task。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.adapters.pandoc import publish as publish_with_pandoc

if TYPE_CHECKING:
    from pathlib import Path


def publish(markdown: Path, output: Path, template: Path, timeout: float) -> Path:
    """Pandoc Adapterへ固定したDOCX公開契約を委譲する。

    Args:
        markdown (Path): DOCX変換またはPreview対象のMarkdown Path。
        output (Path): 変換結果を書き込むFile Path。
        template (Path): DOCX Style用のReference DOCX Path。
        timeout (float): 外部処理のTimeout秒数。

    Returns:
        Path: Pandoc Adapterへ固定したDOCX公開契約を委譲する。
    """

    return publish_with_pandoc(markdown, output, template, timeout)
