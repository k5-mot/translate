"""入力PDFをDocling送信用partへ分割するSPLIT Task。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.adapters.pdf import page_count, split_pdf
from translate.artifact_store import (
    describe_staged_artifact,
    sha256_file,
    temporary_task_directory,
    write_model,
)
from translate.models.artifacts import SplitManifest, SplitPart

if TYPE_CHECKING:
    from pathlib import Path


def split(
    source: Path,
    task_directory: Path,
    processing_directory: Path,
    pages_per_part: int,
) -> SplitManifest:
    """PDFを固定page数で分割し、原子的にManifestとpartを公開する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        task_directory (Path): 対象Taskの成果物Directory。
        processing_directory (Path): 対象処理の成果物Directory。
        pages_per_part (int): 一つの分割PDFへ含めるPage数。

    Returns:
        SplitManifest: PDFを固定page数で分割し、原子的にManifestとpartを公開する。
    """

    total_pages = page_count(source)
    with temporary_task_directory(task_directory) as temporary:
        staged_parts = split_pdf(source, temporary / "parts", pages_per_part)
        parts: list[SplitPart] = []
        for number, staged in enumerate(staged_parts, start=1):
            first = (number - 1) * pages_per_part + 1
            last = min(number * pages_per_part, total_pages)
            published = task_directory / "parts" / staged.name
            parts.append(
                SplitPart(
                    number=number,
                    page_start=first,
                    page_end=last,
                    file=describe_staged_artifact(
                        processing_directory, published, staged
                    ),
                )
            )
        manifest = SplitManifest(
            source_sha256=sha256_file(source),
            total_pages=total_pages,
            parts=parts,
        )
        write_model(temporary / "manifest.json", manifest)
    return manifest
