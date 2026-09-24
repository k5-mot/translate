"""出力先の排他制御と、安全な小規模ファイル保存を提供する。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from uuid import uuid4

import portalocker

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import TracebackType

    ArtifactValidator = Callable[[Path], None]
    DirectoryBuilder = Callable[[Path], None]


def sha256_file(path: Path) -> str:
    """入力変更の検出に使うSHA-256をstreaming計算する。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        # Note 1: Fixed-size reads avoid loading a large PDF into memory.
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(
    path: Path,
    value: str,
    validator: ArtifactValidator | None = None,
) -> None:
    """途中書込みを成果物として見せないよう、同一volume内で置換保存する。"""

    atomic_write_bytes(path, value.encode(), validator)


def atomic_write_bytes(
    path: Path,
    value: bytes,
    validator: ArtifactValidator | None = None,
) -> None:
    """Binary Artifactをflush・検証してからatomic保存する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    # Note 2: A sibling temporary file keeps the final rename atomic on one volume.
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            _phase("write", temporary)
            stream.flush()
            # Note 3: fsync prevents a checkpoint from preceding its artifact on disk.
            os.fsync(stream.fileno())
            _phase("flush", temporary)
        if validator is not None:
            validator(temporary)
        _phase("validate", temporary)
        _phase("replace", temporary)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    """JSONをUTF-8、非ASCII保持、末尾改行付きでatomic保存する。"""

    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        _validate_json,
    )


def atomic_publish_directory(
    path: Path,
    builder: DirectoryBuilder,
    validator: ArtifactValidator | None = None,
) -> None:
    """Directory Artifactを完成・検証し、complete manifestと共に公開する。"""

    with atomic_directory(path, validator) as temporary:
        builder(temporary)


@contextmanager
def atomic_directory(
    path: Path,
    validator: ArtifactValidator | None = None,
) -> Iterator[Path]:
    """TaskがDirectory Artifactを段階作成するためのcontextを返す。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    )
    backup: Path | None = None
    try:
        yield temporary
        _phase("write", temporary)
        _write_manifest(temporary)
        _flush_tree(temporary)
        _phase("flush", temporary)
        if validator is not None:
            validator(temporary)
        _phase("validate", temporary)
        _phase("replace", temporary)
        if path.exists():
            backup = _backup_path(path)
            path.replace(backup)
        try:
            temporary.replace(path)
        except BaseException:
            if backup is not None and backup.exists() and not path.exists():
                backup.replace(path)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def load_json(path: Path, default: Any = None) -> Any:
    """JSONを読み、未作成時だけ呼出側のdefaultを返す。"""

    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_json(path: Path) -> None:
    """置換前の一時FileがUTF-8 JSONとして読めることを確認し、破損時は公開を中止させる。"""

    json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(directory: Path) -> None:
    """directory公開直前に既存形式の印を作り、flushとfsyncでFile内容を同期する。"""

    manifest = directory / ".complete.json"
    with manifest.open("wb") as stream:
        stream.write(b'{"complete":true}\n')
        stream.flush()
        os.fsync(stream.fileno())


def _flush_tree(directory: Path) -> None:
    """directory置換前に配下のFileをfsyncし、同期失敗は公開処理へ伝える。"""

    for path in directory.rglob("*"):
        if path.is_file():
            with path.open("r+b") as stream:
                os.fsync(stream.fileno())


def _phase(name: str, path: Path) -> None:
    """障害注入Test用の副作用なしphase境界。"""


def _backup_path(path: Path) -> Path:
    """置換失敗時の復元用退避pathを選び、symbolic linkの置換は拒否する。"""

    if path.is_symlink():
        msg = f"refusing to replace linked directory: {path}"
        raise ValueError(msg)
    return path.with_name(f".{path.name}.{uuid4().hex}.backup")


class OutputInUseError(RuntimeError):
    """別の呼出が出力の排他を所有しており、今回の操作を開始できない。"""


class OutputLock:
    """同じRunの`.workspace`を二つのprocessが更新することを防ぐ。"""

    def __init__(self, path: Path) -> None:
        """対象directoryを保持し、実際の排他取得はenterまで行わない。"""

        self.path = path
        self._lock: portalocker.Lock | None = None

    def __enter__(self) -> Self:
        """導入済みportalockerで即時取得し、競合は専用例外で通知する。"""

        self.path.mkdir(parents=True, exist_ok=True)
        # Note 4: A non-blocking lock fails fast instead of hiding duplicate runs.
        lock = portalocker.Lock(self.path / "run.lock", mode="a+b", timeout=0)
        try:
            lock.acquire()
        except portalocker.AlreadyLocked as error:
            message = f"output is already in use: {self.path}"
            raise OutputInUseError(message) from error
        self._lock = lock
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """保持している排他だけを解放し、保存内容は変更しない。"""

        if self._lock is not None:
            self._lock.release()
            self._lock = None
