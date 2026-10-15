"""Pandoc Markdownを中間DOCXへ変換するPANDOC Task。"""

from pathlib import Path

from translate.adapters.pandoc import Pandoc


def publish(markdown: Path, output: Path, template: Path, timeout: float) -> Path:
    """Pandoc Adapterへ中間DOCXの生成を委譲する。

    Args:
        markdown (Path): DOCX変換またはPreview対象のMarkdown Path。
        output (Path): 変換結果を書き込むFile Path。
        template (Path): DOCX Style用のReference DOCX Path。
        timeout (float): 外部処理のTimeout秒数。

    Returns:
        Path: Pandoc Adapterへ中間DOCXの生成を委譲する。
    """

    return Pandoc(timeout).publish(markdown, output, template)
