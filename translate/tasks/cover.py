"""COVER: 原本PDFの第1ページを表紙画像へ変換する。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from PIL import Image

from translate.adapters.pdf import render_page
from translate.common.workspace import atomic_directory, atomic_write_json

if TYPE_CHECKING:
    from pathlib import Path


def run(source: Path, output: Path) -> Path:
    """第1ページを150 DPI相当のPNGへ変換して検証する。"""

    start = time.perf_counter()
    with atomic_directory(output.parent, _validate_cover) as temporary:
        result = render_page(source, 1, temporary / output.name, dpi=150)
        atomic_write_json(
            temporary / "manifest.json",
            {"image": output.name, "excluded_pages": [1]},
        )
        with Image.open(result) as image:
            image.verify()
    end = time.perf_counter()
    print(f"[TIME] COVER page=- group=-: {end - start:.3f} s")  # noqa: T201
    return output


def _validate_cover(directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("excluded_pages") != [1]:
        msg = "COVER manifest must exclude source page 1"
        raise ValueError(msg)
    with Image.open(directory / str(manifest["image"])) as image:
        image.verify()
