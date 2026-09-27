"""Docling ZIPを検査して安全に展開するUNPACK Task。"""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from translate.artifact_store import (
    atomic_write_bytes,
    describe_staged_artifact,
    temporary_task_directory,
    write_json,
    write_model,
)
from translate.models.artifacts import DoclingManifest, UnpackedPart, UnpackManifest


def unpack(
    manifest: DoclingManifest,
    task_directory: Path,
    processing_directory: Path,
) -> UnpackManifest:
    """全entryの安全性確認後にJSONとassetをpart別namespaceへ展開する。"""

    parts: list[UnpackedPart] = []
    with temporary_task_directory(task_directory) as temporary:
        for part in manifest.parts:
            archive_path = processing_directory / Path(part.archive.relative_path)
            name = f"part-{part.number:04d}"
            staged_part = temporary / name
            staged_part.mkdir(parents=True)
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                _validate_entries(infos, staged_part)
                json_infos = [
                    info for info in infos if info.filename.casefold().endswith(".json")
                ]
                if len(json_infos) != 1:
                    raise ValueError(
                        "Docling result must contain exactly one JSON file"
                    )
                document = json.loads(archive.read(json_infos[0]).decode("utf-8"))
                if not isinstance(document, dict):
                    raise ValueError("Docling JSON must be an object")
                staged_document = staged_part / "document.json"
                write_json(staged_document, document)
                assets = _extract_assets(archive, infos, staged_part)
            document_artifact = describe_staged_artifact(
                processing_directory,
                task_directory / name / "document.json",
                staged_document,
            )
            asset_artifacts = [
                describe_staged_artifact(
                    processing_directory,
                    task_directory / name / path.relative_to(staged_part),
                    path,
                )
                for path in assets
            ]
            parts.append(
                UnpackedPart(
                    number=part.number,
                    document=document_artifact,
                    assets=asset_artifacts,
                )
            )
        result = UnpackManifest(parts=parts)
        write_model(temporary / "manifest.json", result)
    return result


def _validate_entries(infos: list[zipfile.ZipInfo], root: Path) -> None:
    """ZIP全entryのpath、重複、symlinkおよび展開先境界を検査する。"""

    seen: set[str] = set()
    seen_casefold: set[str] = set()
    root_resolved = root.resolve()
    for info in infos:
        normalized = info.filename.replace("\\", "/")
        posix = PurePosixPath(normalized)
        windows = PureWindowsPath(normalized)
        mode = info.external_attr >> 16
        if (
            not normalized
            or posix.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or ".." in posix.parts
            or stat.S_ISLNK(mode)
        ):
            raise ValueError(f"unsafe ZIP entry: {info.filename}")
        if normalized in seen or normalized.casefold() in seen_casefold:
            raise ValueError(f"duplicate ZIP entry: {info.filename}")
        seen.add(normalized)
        seen_casefold.add(normalized.casefold())
        target = root.joinpath(*posix.parts).resolve()
        if not target.is_relative_to(root_resolved):
            raise ValueError(f"ZIP entry escapes output directory: {info.filename}")


def _extract_assets(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    root: Path,
) -> list[Path]:
    """artifacts配下のfileだけを検査済み相対pathへ展開する。"""

    results: list[Path] = []
    for info in infos:
        relative = PurePosixPath(info.filename.replace("\\", "/"))
        if info.is_dir() or "artifacts" not in relative.parts:
            continue
        artifact_index = relative.parts.index("artifacts")
        suffix = relative.parts[artifact_index + 1 :]
        if not suffix:
            continue
        target = root.joinpath("artifacts", *suffix)
        atomic_write_bytes(target, archive.read(info))
        results.append(target)
    return results
