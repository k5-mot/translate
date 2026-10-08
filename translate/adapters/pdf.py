"""pypdfium2を使うPDF分割、text抽出およびpage画像化。"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import TYPE_CHECKING

import pypdfium2 as pdfium
from PIL import Image

from translate.artifact_store import atomic_write_bytes

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def page_count(source: Path) -> int:
    """有効なPDFのpage数を返し、空文書を拒否する。

    Args:
        source (Path): 変換または検証対象の入力Source。

    Returns:
        int: 有効なPDFのpage数を返し、空文書を拒否する。

    Raises:
        ValueError: `PDF has no pages`と判定した場合。
    """

    with pdfium.PdfDocument(source) as document:
        count = len(document)
    if count < 1:
        raise ValueError("PDF has no pages")
    logger.debug("PDFページ数 pages=%d", count)
    return count


def split_pdf(source: Path, output_directory: Path, pages_per_part: int) -> list[Path]:
    """PDFを指定page数ずつ分割して順序付きpathを返す。

    Args:
        source (Path): 変換または検証対象の入力Source。
        output_directory (Path): 分割PDFの出力Directory。
        pages_per_part (int): 一つの分割PDFへ含めるPage数。

    Returns:
        list[Path]: PDFを指定page数ずつ分割して順序付きpathを返す。

    Raises:
        ValueError: `pages_per_part must be positive`、`PDF has no pages`のいずれかと判定した場合。
    """

    if pages_per_part < 1:
        raise ValueError("pages_per_part must be positive")
    logger.info("PDF分割開始 pages_per_part=%d", pages_per_part)
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
    logger.info("PDF分割完了 parts=%d", len(paths))
    return paths


def render_page(
    source: Path, page_number: int, output: Path, dpi: int
) -> tuple[int, int]:
    """1始まりのPDF pageをPNGへ変換し、pixel寸法を返す。

    Args:
        source (Path): 変換または検証対象の入力Source。
        page_number (int): 1から始まる変換対象Page番号。
        output (Path): 変換結果を書き込むFile Path。
        dpi (int): PDF PageをRasterizeする解像度。

    Returns:
        tuple[int, int]: 生成したPNGの幅と高さをPixel単位で並べたTuple。

    Raises:
        ValueError: `f'PDF page is out of range: {page_number}'`と判定した場合。
    """

    logger.debug("PDF画像化開始 page=%d dpi=%d", page_number, dpi)
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
    logger.debug("PDF画像化完了 page=%d width=%d height=%d", page_number, *size)
    return size


def extract_pages_text(path: Path) -> list[str]:
    """PDFの各pageから埋込みtext layerを抽出する。

    Args:
        path (Path): Text Layerを抽出するPDF FileのPath。

    Returns:
        list[str]: PDFの各pageから埋込みtext layerを抽出する。
    """

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
    logger.debug("PDF text抽出完了 pages=%d", len(values))
    return values
