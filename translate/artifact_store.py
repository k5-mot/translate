"""成果物path、fingerprint、原子的保存および排他制御。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from uuid import uuid4

import portalocker
from pydantic import BaseModel

from translate.models.artifacts import (
    ArtifactFile,
    LLMCallArtifact,
    LLMTaskName,
    ProcessingError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType


class ArtifactError(RuntimeError):
    """成果物が欠落、破損または処理契約と不一致であることを表す。"""


class ProcessingInUseError(RuntimeError):
    """同じ処理IDを別processが操作中であることを表す。"""


def sha256_file(path: Path) -> str:
    """fileのraw byte列に対するSHA-256をstreaming計算する。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: BaseModel | Any) -> str:
    """Pydantic JSON modeまたはJSON互換値のcanonical SHA-256を返す。"""

    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_bytes(path: Path, value: bytes) -> None:
    """同一directoryの一時fileを同期してから置換保存する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, value: str) -> None:
    """UTF-8 textを途中状態を公開せず保存する。"""

    atomic_write_bytes(path, value.encode("utf-8"))


def write_model(path: Path, value: BaseModel) -> None:
    """Pydantic modelをUTF-8、LF、末尾改行付きJSONで原子的に保存する。"""

    text = json.dumps(value.model_dump(mode="json"), ensure_ascii=False, indent=2)
    atomic_write_text(path, f"{text}\n")


def write_json(path: Path, value: Any) -> None:
    """JSON互換値をUTF-8、LF、末尾改行付きで原子的に保存する。"""

    text = json.dumps(value, ensure_ascii=False, indent=2)
    atomic_write_text(path, f"{text}\n")


def load_model[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> ModelT:
    """JSON成果物を読み、指定Pydantic modelで検証する。"""

    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        message = f"invalid artifact: {path}"
        raise ArtifactError(message) from error


def llm_call_id(task: str, target_ids: list[str], lineage: list[str]) -> str:
    """Task、順序付き対象IDおよび分割系譜から決定的なCall IDを作る。"""

    value = canonical_hash({"task": task, "target_ids": target_ids, "lineage": lineage})
    return f"call-{value}"


def begin_llm_call(
    directory: Path,
    *,
    call_id: str,
    task: LLMTaskName,
    fingerprint: str,
    target_ids: list[str],
    previous_attempts: int = 0,
) -> LLMCallArtifact:
    """送信前のCall状態を原子的に保存する。"""

    now = datetime.now(UTC)
    artifact = LLMCallArtifact(
        call_id=call_id,
        task=task,
        status="processing",
        fingerprint=fingerprint,
        target_ids=target_ids,
        attempts=previous_attempts,
        started_at=now,
        updated_at=now,
    )
    write_model(directory / "call.json", artifact)
    return artifact


def complete_llm_call(
    directory: Path,
    artifact: LLMCallArtifact,
    response: BaseModel,
    *,
    attempts: int,
    input_tokens: int | None,
    output_tokens: int | None,
    status: str = "succeeded",
    child_call_ids: list[str] | None = None,
) -> LLMCallArtifact:
    """検証済み応答を先に保存し、そのhash付きCall状態を公開する。"""

    response_path = directory / "response.json"
    write_model(response_path, response)
    updated = artifact.model_copy(
        update={
            "status": status,
            "attempts": artifact.attempts + attempts,
            "child_call_ids": child_call_ids or [],
            "response_sha256": sha256_file(response_path),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "updated_at": datetime.now(UTC),
            "error": None,
        }
    )
    write_model(directory / "call.json", updated)
    return updated


def fail_llm_call(
    directory: Path,
    artifact: LLMCallArtifact,
    error: BaseException,
    *,
    attempts: int,
) -> LLMCallArtifact:
    """LLM Call失敗を本文なしのProcessingErrorとして保存する。"""

    updated = artifact.model_copy(
        update={
            "status": "failed",
            "attempts": artifact.attempts + attempts,
            "updated_at": datetime.now(UTC),
            "error": ProcessingError(
                code="llm_call_failed",
                message="LLM call did not produce a valid response.",
                cause_type=type(error).__name__,
                retryable=True,
            ),
        }
    )
    write_model(directory / "call.json", updated)
    return updated


def mark_split_llm_call(
    directory: Path,
    artifact: LLMCallArtifact,
    child_call_ids: list[str],
) -> LLMCallArtifact:
    """親Callを再送しないよう子Call IDとsplit状態を先に保存する。"""

    updated = artifact.model_copy(
        update={
            "status": "split",
            "child_call_ids": child_call_ids,
            "updated_at": datetime.now(UTC),
        }
    )
    write_model(directory / "call.json", updated)
    return updated


def load_reusable_llm_response[ResponseT: BaseModel](
    directory: Path,
    *,
    call_id: str,
    fingerprint: str,
    response_type: type[ResponseT],
) -> tuple[LLMCallArtifact, ResponseT] | None:
    """ID、fingerprint、hash、Schemaが一致する成功Callだけを再利用する。"""

    call_path = directory / "call.json"
    response_path = directory / "response.json"
    if not call_path.is_file() or not response_path.is_file():
        return None
    try:
        artifact = load_model(call_path, LLMCallArtifact)
        if (
            artifact.call_id != call_id
            or artifact.fingerprint != fingerprint
            or artifact.status not in {"succeeded", "partial"}
            or artifact.response_sha256 != sha256_file(response_path)
        ):
            return None
        return artifact, load_model(response_path, response_type)
    except ArtifactError:
        return None


def describe_artifact(processing_directory: Path, path: Path) -> ArtifactFile:
    """処理ディレクトリ配下のfileをArtifactFileへ変換する。"""

    resolved_root = processing_directory.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root) or not resolved_path.is_file():
        raise ArtifactError("artifact must be a file inside the processing directory")
    return ArtifactFile(
        relative_path=resolved_path.relative_to(resolved_root).as_posix(),
        sha256=sha256_file(resolved_path),
        size_bytes=resolved_path.stat().st_size,
    )


def describe_staged_artifact(
    processing_directory: Path,
    published_path: Path,
    staged_path: Path,
) -> ArtifactFile:
    """一時fileの内容を、公開後の相対pathでArtifactFileへ変換する。"""

    resolved_root = processing_directory.resolve()
    resolved_published = published_path.resolve()
    if (
        not resolved_published.is_relative_to(resolved_root)
        or not staged_path.is_file()
    ):
        raise ArtifactError("staged artifact must publish inside processing directory")
    return ArtifactFile(
        relative_path=resolved_published.relative_to(resolved_root).as_posix(),
        sha256=sha256_file(staged_path),
        size_bytes=staged_path.stat().st_size,
    )


def processing_directory(outputs: Path, source: Path, processing_id: str) -> Path:
    """入力basenameと処理IDから成果物rootを決定する。"""

    basename = source.stem if source.is_file() else source.name
    return outputs / basename / processing_id


@contextmanager
def temporary_task_directory(path: Path) -> Iterator[Path]:
    """Task成果を隣接一時directoryで構築し、成功時だけ公開する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    )
    try:
        yield temporary
        backup = _replace_directory(temporary, path)
        if backup is not None:
            shutil.rmtree(backup)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _replace_directory(temporary: Path, path: Path) -> Path | None:
    """既存Taskを退避し、一時directoryを同一volume内で公開する。"""

    if path.is_symlink():
        raise ArtifactError(f"refusing to replace linked task directory: {path}")
    backup = (
        path.with_name(f".{path.name}.{uuid4().hex}.backup") if path.exists() else None
    )
    if backup is not None:
        path.replace(backup)
    try:
        temporary.replace(path)
    except BaseException:
        if backup is not None and backup.exists() and not path.exists():
            backup.replace(path)
        raise
    return backup


class ProcessingLock:
    """同じ処理IDへの同時操作を即時拒否する排他lock。"""

    def __init__(self, directory: Path) -> None:
        """排他対象directoryを保持し、取得はcontext開始まで遅延する。"""

        self.directory = directory
        self._lock: portalocker.Lock | None = None

    def __enter__(self) -> Self:
        """非待機でlockを取得し、競合時は専用例外を送出する。"""

        self.directory.mkdir(parents=True, exist_ok=True)
        lock = portalocker.Lock(self.directory / ".lock", mode="a+b", timeout=0)
        try:
            lock.acquire()
        except portalocker.AlreadyLocked as error:
            raise ProcessingInUseError(
                f"processing ID is already in use: {self.directory.name}"
            ) from error
        self._lock = lock
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """このinstanceが保持するlockだけを解放する。"""

        if self._lock is not None:
            self._lock.release()
            self._lock = None
