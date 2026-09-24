"""DOCX: Pandoc MarkdownをWord文書へ変換する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.adapters.pandoc import create_docx
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path


class DocxTask(BaseTask):
    """Execute DOCX while sharing elapsed-time measurement only."""

    name = "DOCX"

    def run(self, markdown: Path, output: Path, template: Path) -> Path:
        """PandocでDOCXをatomicに生成する。"""

        with self.measure():
            create_docx(markdown, output, template)
            return output


def run(markdown: Path, output: Path, template: Path) -> Path:
    """Existing function delegates to the typed DocxTask operation."""

    return DocxTask().run(markdown, output, template)
