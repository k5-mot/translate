"""pypdfium2によるPDF分割、text抽出、page画像化。"""

from __future__ import annotations

import json
from io import BytesIO
from typing import TYPE_CHECKING, Any

import pypdfium2 as pdfium
from PIL import Image

from translate_v1.common.workspace import (
    atomic_directory,
    atomic_write_bytes,
    atomic_write_json,
)

if TYPE_CHECKING:
    from pathlib import Path


def validate(source: Path) -> None:
    """入力PDFを出力作成前に開き、少なくとも1 pageあることを確認する。"""

    with source.open("rb") as stream:
        stream.read(1)
    with pdfium.PdfDocument(source) as document:
        if len(document) == 0:
            msg = "PDF has no pages"
            raise ValueError(msg)


def split(source: Path, output_dir: Path, pages_per_part: int = 10) -> dict[str, Any]:
    """PDFを指定ページ数ごとに分割しmanifestを返す。"""

    if pages_per_part < 1:
        msg = "pages_per_part must be positive"
        raise ValueError(msg)
    manifest: dict[str, Any] = {"source": str(source), "parts": []}
    with atomic_directory(output_dir, _validate_split) as temporary:
        with pdfium.PdfDocument(source) as pdf:
            if len(pdf) == 0:
                msg = "PDF has no pages"
                raise ValueError(msg)
            manifest["page_count"] = len(pdf)
            for number, first in enumerate(range(0, len(pdf), pages_per_part), 1):
                indexes = list(range(first, min(first + pages_per_part, len(pdf))))
                name = f"part-{number:04d}.pdf"
                target = temporary / name
                with pdfium.PdfDocument.new() as part:
                    part.import_pages(pdf, pages=indexes)
                    part.save(target)
                manifest["parts"].append(
                    {
                        "number": number,
                        "path": str(output_dir / name),
                        "first_page": indexes[0] + 1,
                        "last_page": indexes[-1] + 1,
                    }
                )
        atomic_write_json(temporary / "manifest.json", manifest)
    return manifest


def render_page(source: Path, page_number: int, output: Path, dpi: int = 120) -> Path:
    """1始まりの指定ページをPNGへ変換する。"""

    with pdfium.PdfDocument(source) as pdf:
        if not 1 <= page_number <= len(pdf):
            msg = f"PDF page is out of range: {page_number}"
            raise ValueError(msg)
        page = pdf[page_number - 1]
        try:
            bitmap = page.render(scale=dpi / 72)
            try:
                image = bitmap.to_pil()
                try:
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    atomic_write_bytes(output, buffer.getvalue(), _validate_png)
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    return output


def pages_text(path: Path) -> list[str]:
    """PDFの各ページからtext layerを抽出する。"""

    values: list[str] = []
    with pdfium.PdfDocument(path) as pdf:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                text_page = page.get_textpage()
                try:
                    values.append(text_page.get_text_range())
                finally:
                    text_page.close()
            finally:
                page.close()
    return values


def _validate_png(path: Path) -> None:
    """公開直前の画像をPillowで検証し、破損画像の置換保存を防ぐ。"""

    with Image.open(path) as image:
        image.verify()


def _validate_split(directory: Path) -> None:
    """分割成果物の公開前にmanifestとFile数の一致、各PDFにページがあることを確認する。"""

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    parts = sorted(directory.glob("part-*.pdf"))
    if not parts or len(parts) != len(manifest.get("parts", [])):
        msg = "split PDF manifest does not match artifacts"
        raise ValueError(msg)
    for part in parts:
        with pdfium.PdfDocument(part) as document:
            if len(document) < 1:
                msg = f"split PDF has no pages: {part.name}"
                raise ValueError(msg)
