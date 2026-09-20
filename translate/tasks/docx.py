"""DOCX: Pandoc MarkdownをWord文書へ変換する。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from translate.adapters.pandoc import create_docx

if TYPE_CHECKING:
    from pathlib import Path


def run(markdown: Path, output: Path, template: Path) -> Path:
    """PandocでDOCXをatomicに生成する。"""

    start = time.perf_counter()
    create_docx(markdown, output, template)
    end = time.perf_counter()
    print(f"[TIME] DOCX page=- group=-: {end - start:.3f} s")  # noqa: T201
    return output
