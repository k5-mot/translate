"""原本PDFの1ページ目を表紙画像にするCOVER Task。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.adapters.pdf import render_page
from translate.artifact_store import describe_artifact, write_model
from translate.models.artifacts import CoverResult

if TYPE_CHECKING:
    from pathlib import Path


def create_cover(
    source: Path, task_directory: Path, processing_directory: Path
) -> CoverResult:
    """150 DPIの表紙PNGとmanifestを生成する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        task_directory (Path): 対象Taskの成果物Directory。
        processing_directory (Path): 対象処理の成果物Directory。

    Returns:
        CoverResult: 150 DPIの表紙PNGとmanifestを生成する。
    """

    task_directory.mkdir(parents=True, exist_ok=True)
    image_path = task_directory / "cover.png"
    width, height = render_page(source, 1, image_path, 150)
    result = CoverResult(
        image=describe_artifact(processing_directory, image_path),
        width=width,
        height=height,
        excluded_page_numbers=[1],
    )
    write_model(task_directory / "manifest.json", result)
    return result
