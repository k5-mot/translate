"""DOCLING: PDF partをDocling Serveへ送信する。"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

from translate.adapters.docling import DoclingClient
from translate.common.workspace import (
    atomic_directory,
    atomic_write_bytes,
    atomic_write_json,
)
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings


class DoclingTask(BaseTask):
    """Execute DOCLING while sharing elapsed-time measurement only."""

    name = "DOCLING"

    def run(
        self, parts: list[Path], output_dir: Path, settings: Settings
    ) -> list[Path]:
        """全partをDoclingへ送り、response ZIPを保存する。"""

        with self.measure():
            client = DoclingClient(
                settings.docling_url or "",
                settings.docling_api_key,
                ocr_preset=settings.docling_ocr_preset,
                ocr_lang=settings.docling_ocr_lang,
                force_ocr=settings.docling_force_ocr,
                retry_attempts=settings.retry_attempts,
                retry_base_seconds=settings.retry_base_seconds,
                retry_max_seconds=settings.retry_max_seconds,
                timeout_seconds=settings.request_timeout_seconds,
                deadline_seconds=settings.task_deadline_seconds,
            )
            results: list[Path] = []
            with atomic_directory(output_dir, _validate_output) as temporary:
                for number, part in enumerate(parts, 1):
                    name = f"part-{number:04d}"
                    target = temporary / name
                    target.mkdir(parents=True, exist_ok=True)
                    payload, job = client.convert(part)
                    atomic_write_bytes(target / "result.zip", payload)
                    atomic_write_json(target / "job.json", job)
                    results.append(output_dir / name / "result.zip")
            return results


def run(parts: list[Path], output_dir: Path, settings: Settings) -> list[Path]:
    """Existing function delegates to the typed DoclingTask operation."""

    return DoclingTask().run(parts, output_dir, settings)


def _validate_output(directory: Path) -> None:
    """公開前に応答ZIPが存在することと各ZIPのCRCを確認し、空または破損した結果を拒否する。"""

    archives = list(directory.glob("part-*/result.zip"))
    if not archives:
        msg = "Docling produced no ZIP artifacts"
        raise ValueError(msg)
    for archive_path in archives:
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                msg = f"Docling returned corrupt ZIP: {archive_path.name}"
                raise ValueError(msg)
