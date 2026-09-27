"""pypdfium2を使うPDF分割、text抽出およびpage画像化。"""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import pypdfium2 as pdfium
from PIL import Image

from translate.artifact_store import atomic_write_bytes

if TYPE_CHECKING:
    from pathlib import Path


def page_count(source: Path) -> int:
    """有効なPDFのpage数を返し、空文書を拒否する。"""

    with pdfium.PdfDocument(source) as document:
        count = len(document)
    if count < 1:
        raise ValueError("PDF has no pages")
    return count


def split_pdf(source: Path, output_directory: Path, pages_per_part: int) -> list[Path]:
    """PDFを指定page数ずつ分割して順序付きpathを返す。"""

    if pages_per_part < 1:
        raise ValueError("pages_per_part must be positive")
    output_directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with pdfium.PdfDocument(source) as source_pdf:
        if len(source_pdf) < 1:
            raise ValueError("PDF has no pages")
        for number, first in enumerate(
            range(0, len(source_pdf), pages_per_part), start=1
        ):
            indexes = list(range(first, min(first + pages_per_part, len(source_pdf))))
            path = output_directory / f"part-{number:04d}.pdf"
            with pdfium.PdfDocument.new() as part:
                part.import_pages(source_pdf, pages=indexes)
                part.save(path)
            paths.append(path)
    return paths


def render_page(
    source: Path, page_number: int, output: Path, dpi: int
) -> tuple[int, int]:
    """1始まりのPDF pageをPNGへ変換し、pixel寸法を返す。"""

    with pdfium.PdfDocument(source) as pdf:
        if not 1 <= page_number <= len(pdf):
            raise ValueError(f"PDF page is out of range: {page_number}")
        page = pdf[page_number - 1]
        try:
            bitmap = page.render(scale=dpi / 72)
            try:
                image = bitmap.to_pil()
                try:
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    size = image.size
                    atomic_write_bytes(output, buffer.getvalue())
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    with Image.open(output) as verification:
        verification.verify()
    return size


def extract_pages_text(path: Path) -> list[str]:
    """PDFの各pageから埋込みtext layerを抽出する。"""

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
