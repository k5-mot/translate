"""分割文書をDocling Serveへ送信するDOCLING Task。"""

import json
import shutil
import zipfile
from pathlib import Path

from translate.adapters.artifact_store import (
    atomic_write_bytes,
    describe_staged_artifact,
    sha256_file,
    temporary_task_directory,
    write_json,
    write_model,
)
from translate.adapters.docling import DoclingClient
from translate.common.config import Config
from translate.models.artifacts import (
    DoclingManifest,
    DoclingPart,
    DoclingProgress,
    SplitManifest,
)


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
    progress_path = task_directory / "docling-progress.json"
    total = len(manifest.parts)
    # 失敗で一時directoryが消えても、完了済みpartをResume時に再送信しない。
    cache = task_directory.with_name(f"{task_directory.name}.parts")
    write_model(progress_path, DoclingProgress(completed=0, total=total))
    with temporary_task_directory(task_directory) as temporary:
        for split_part in manifest.parts:
            source = processing_directory / Path(
                *Path(split_part.file.relative_path).parts
            )
            payload, job_id, polls = _converted_part(client, source, cache)
            name = f"part-{split_part.number:04d}"
            staged_archive = temporary / name / "result.zip"
            staged_archive.parent.mkdir(parents=True, exist_ok=True)
            staged_archive.write_bytes(payload)
            with zipfile.ZipFile(staged_archive) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Docling returned a corrupt ZIP")
            write_json(
                temporary / name / "job.json",
                {"task_id": job_id, "status": "succeeded", "poll_attempts": polls},
                atomic=False,
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
        write_model(temporary / "manifest.json", result, atomic=False)
    write_model(progress_path, DoclingProgress(completed=len(parts), total=total))
    shutil.rmtree(cache, ignore_errors=True)
    return result


def _converted_part(
    client: DoclingClient, source: Path, cache: Path
) -> tuple[bytes, str, int]:
    """同じ内容のpartが変換済みなら再利用し、なければ変換して保存する。

    Args:
        client: Docling Serveへの接続。
        source: 変換する分割PDF。
        cache: 完了済みpartを内容hash名で保持するdirectory。

    Returns:
        変換済みZIP、Job IDおよびPolling回数。
    """
    key = sha256_file(source)
    archive, job = cache / f"{key}.zip", cache / f"{key}.json"
    if archive.is_file() and job.is_file():
        saved = json.loads(job.read_text(encoding="utf-8"))
        return archive.read_bytes(), saved["task_id"], saved["poll_attempts"]
    payload, job_id, polls = client.convert(source)
    atomic_write_bytes(archive, payload)
    write_json(job, {"task_id": job_id, "poll_attempts": polls})
    return payload, job_id, polls
