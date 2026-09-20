"""SPLIT: PDFをDocling送信用partへ分割する。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from translate.adapters import pdf

if TYPE_CHECKING:
    from pathlib import Path


class PdfInputError(ValueError):
    """本文やpathを含めず、無効なPDF入力roleを示す。"""

    def __init__(self, role: str, cause: BaseException) -> None:
        self.target_id = role
        self.role = role
        self.error_type = type(cause).__name__
        super().__init__(f"invalid PDF input role={role} cause={self.error_type}")


def run(
    source: Path,
    output_dir: Path,
    pages_per_part: int = 10,
    *,
    role: str = "source",
) -> dict[str, Any]:
    """PDFを分割してmanifestを返す。"""

    start = time.perf_counter()
    try:
        pdf.validate(source)
    except Exception as error:  # noqa: BLE001
        raise PdfInputError(role, error) from None
    result = pdf.split(source, output_dir, pages_per_part)
    end = time.perf_counter()
    print(f"[TIME] SPLIT page=- group=-: {end - start:.3f} s")  # noqa: T201
    return result
