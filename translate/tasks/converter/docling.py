"""分割文書をDocling Serveへ送信するDOCLING Task。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from translate.adapters.docling import DoclingClient
from translate.artifact_store import (
    atomic_write_bytes,
    describe_staged_artifact,
    temporary_task_directory,
    write_json,
    write_model,
)
from translate.models.artifacts import (
    DoclingManifest,
    DoclingPart,
    DoclingProgress,
    SplitManifest,
)

if TYPE_CHECKING:
    from translate.common.config import Config


def convert(
    manifest: SplitManifest,
    task_directory: Path,
    processing_directory: Path,
    config: Config,
) -> DoclingManifest:
    """全partをDoclingへ送り、検証済みZIPとjob情報を原子的に公開する。

    Args:
        manifest (SplitManifest): 変換元Taskが生成したManifest。
        task_directory (Path): 対象Taskの成果物Directory。
        processing_directory (Path): 対象処理の成果物Directory。
        config (Config): 接続先、上限値および処理Optionを保持する設定。

    Returns:
        DoclingManifest: 変換済みZIP、Job IDおよびPolling回数のTuple。

    Raises:
        ValueError: `Docling returned a corrupt ZIP`と判定した場合。
    """

    client = DoclingClient(config)
    parts: list[DoclingPart] = []
    progress_path = task_directory.parent / "docling-progress.json"
    total = len(manifest.parts)
    write_model(progress_path, DoclingProgress(completed=0, total=total))
    with temporary_task_directory(task_directory) as temporary:
        for split_part in manifest.parts:
            source = processing_directory / Path(
                *Path(split_part.file.relative_path).parts
            )
            payload, job_id, polls = client.convert(source)
            name = f"part-{split_part.number:04d}"
            staged_archive = temporary / name / "result.zip"
            atomic_write_bytes(staged_archive, payload)
            with zipfile.ZipFile(staged_archive) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Docling returned a corrupt ZIP")
            write_json(
                temporary / name / "job.json",
                {"task_id": job_id, "status": "succeeded", "poll_attempts": polls},
            )
            parts.append(
                DoclingPart(
                    number=split_part.number,
                    job_id=job_id,
                    archive=describe_staged_artifact(
                        processing_directory,
                        task_directory / name / "result.zip",
                        staged_archive,
                    ),
                    poll_attempts=polls,
                )
            )
            write_model(
                progress_path, DoclingProgress(completed=len(parts), total=total)
            )
        result = DoclingManifest(parts=parts)
        write_model(temporary / "manifest.json", result)
    return result
