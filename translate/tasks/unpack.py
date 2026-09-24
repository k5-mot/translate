"""UNPACK: Docling response ZIPを安全に展開する。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from translate.common.workspace import (
    atomic_directory,
    atomic_write_bytes,
    atomic_write_json,
)
from translate.tasks.base import BaseTask


def _safe_target(root: Path, name: str) -> Path | None:
    normalized = name.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(normalized)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
    ):
        return None
    target = root.joinpath(*posix.parts)
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return target


class UnpackTask(BaseTask):
    """Execute UNPACK while sharing elapsed-time measurement only."""

    name = "UNPACK"

    def run(self, archives: list[Path]) -> list[Path]:
        """各ZIPのJSONとassetを同じpart directoryへ展開する。"""

        with self.measure():
            results: list[Path] = []
            for archive_path in archives:
                root = archive_path.parent / "unpacked"
                with (
                    atomic_directory(root) as temporary,
                    zipfile.ZipFile(archive_path) as archive,
                ):
                    json_names = [
                        name for name in archive.namelist() if name.endswith(".json")
                    ]
                    if len(json_names) != 1:
                        msg = "Docling result must contain exactly one JSON file"
                        raise ValueError(msg)
                    document = json.loads(archive.read(json_names[0]))
                    if not isinstance(document, dict):
                        msg = "Docling JSON must be an object"
                        raise ValueError(msg)
                    atomic_write_json(temporary / "document.json", document)
                    for name in archive.namelist():
                        if (
                            "artifacts"
                            not in PurePosixPath(name.replace("\\", "/")).parts
                        ):
                            continue
                        target = _safe_target(temporary, name)
                        if target is None or name.endswith("/"):
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        atomic_write_bytes(target, archive.read(name))
                results.append(root / "document.json")
            return results


def run(archives: list[Path]) -> list[Path]:
    """Existing function delegates to the typed UnpackTask operation."""

    return UnpackTask().run(archives)
