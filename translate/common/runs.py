"""CLIとStreamlitで共有する永続Run Repository。"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import RFC_4122, UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from translate.common.identifiers import uuid7
from translate.common.redaction import redact_text, redact_value
from translate.common.workspace import OutputLock, atomic_write_json

if TYPE_CHECKING:
    from collections.abc import Sequence

RunStatus = Literal["created", "running", "failed", "completed"]
Operation = Literal["translate", "review", "register", "convert"]


class InvalidRunIdError(ValueError):
    """公開操作で受理できないRun ID。"""


class RunInput(BaseModel):
    """Runへcopyされた一つの入力File。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    name: str
    relative_path: str
    sha256: str
    size: int
    logical_path: str | None = None
    source_key: str | None = None


class InputSource(BaseModel):
    """Run作成前に検証済みの一つの入力File。"""

    model_config = ConfigDict(frozen=True)

    role: str
    path: Path
    logical_path: str
    source_key: str | None = None


class RunRecord(BaseModel):
    """本文を含まないRun Lifecycle metadata。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 2
    run_id: str
    operation: Operation
    status: RunStatus = "created"
    inputs: list[RunInput] = Field(default_factory=list)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    settings_snapshot: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    last_task: str | None = None
    created_at: datetime
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)

    @field_validator("settings_snapshot", mode="before")
    @classmethod
    def redact_settings_snapshot(cls, value: object) -> object:
        """Credentialや本文をrun.jsonへ格納させない。"""

        return redact_value(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def redact_warnings(cls, value: object) -> object:
        """永続warning内の典型的なCredential表現を除去する。"""

        if isinstance(value, list):
            return [redact_text(item) for item in value]
        return value

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        """Run IDをcanonical UUIDv7だけに制限する。"""

        try:
            parsed = UUID(value)
        except ValueError as error:
            msg = "run_id must be a canonical UUIDv7"
            raise InvalidRunIdError(msg) from error
        if parsed.version != 7 or parsed.variant != RFC_4122 or str(parsed) != value:
            msg = "run_id must be a canonical UUIDv7"
            raise InvalidRunIdError(msg)
        return value


class RunPaths(BaseModel):
    """一つのRun内で共有するpath。"""

    model_config = ConfigDict(frozen=True)

    root: Path
    inputs: Path
    outputs: Path
    workspace: Path
    metadata: Path


@dataclass(frozen=True, slots=True)
class RunScan:
    """有効なRun一覧と隔離したmetadataの警告。"""

    records: tuple[RunRecord, ...]
    warnings: tuple[str, ...]


class RunRepository:
    """Directoryを正本にRunを作成・読込みする。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def paths(self, run_id: str) -> RunPaths:
        """検証済みrun IDの標準pathを返す。"""

        RunRecord.validate_run_id(run_id)
        root = self.root / run_id
        return RunPaths(
            root=root,
            inputs=root / "inputs",
            outputs=root / "outputs",
            workspace=root / ".workspace",
            metadata=root / "run.json",
        )

    def create(
        self,
        operation: Operation,
        inputs: dict[str, Path] | Sequence[InputSource],
        settings_snapshot: dict[str, Any],
        fingerprint: str,
    ) -> RunRecord:
        """UUIDv7 Runを作り、入力の正本copyとmetadataを保存する。"""

        run_id = str(uuid7())
        paths = self.paths(run_id)
        paths.root.mkdir(parents=True, exist_ok=False)
        try:
            paths.inputs.mkdir()
            paths.outputs.mkdir()
            paths.workspace.mkdir()
            copied: list[RunInput] = []
            sources = (
                collect_input_sources(inputs)
                if isinstance(inputs, dict)
                else tuple(inputs)
            )
            for item in sources:
                source = item.path.resolve(strict=True)
                role_dir = paths.inputs / _safe_role(item.role)
                logical = _safe_logical_path(item.logical_path)
                target = role_dir / logical
                target.parent.mkdir(parents=True, exist_ok=True)
                digest, size = _copy_verified(source, target)
                copied.append(
                    RunInput(
                        role=item.role,
                        name=source.name,
                        relative_path=target.relative_to(paths.root).as_posix(),
                        sha256=digest,
                        size=size,
                        logical_path=logical.as_posix(),
                        source_key=item.source_key,
                    )
                )
            now = datetime.now(UTC)
            record = RunRecord(
                run_id=run_id,
                operation=operation,
                inputs=copied,
                input_hashes={item.role: item.sha256 for item in copied},
                settings_snapshot=settings_snapshot,
                fingerprint=fingerprint,
                created_at=now,
                updated_at=now,
            )
            record = self.save(record)
        except BaseException:
            shutil.rmtree(paths.root, ignore_errors=True)
            raise
        return record

    def load(self, run_id: str) -> RunRecord:
        """run.jsonを検証して読み込む。"""

        paths = self.paths(run_id)
        record = RunRecord.model_validate_json(
            paths.metadata.read_text(encoding="utf-8")
        )
        if record.run_id != run_id:
            msg = f"run metadata ID mismatch: {run_id}"
            raise ValueError(msg)
        return record

    def save(self, record: RunRecord) -> RunRecord:
        """更新時刻を進め、run.jsonをatomic保存する。"""

        updated = record.model_copy(update={"updated_at": datetime.now(UTC)})
        atomic_write_json(
            self.paths(record.run_id).metadata,
            updated.model_dump(mode="json"),
        )
        return updated

    def list_runs(self) -> RunScan:
        """破損metadataを除外し、有効なRunを更新日時の降順で返す。"""

        if not self.root.exists():
            return RunScan((), ())
        records: list[RunRecord] = []
        warnings: list[str] = []
        for metadata in self.root.glob("*/run.json"):
            try:
                record = _read_scanned_record(metadata)
            except (OSError, ValueError) as error:
                reason = (
                    str(error)
                    if isinstance(error, InvalidRunIdError)
                    else type(error).__name__
                )
                warnings.append(
                    f"invalid run metadata excluded: {metadata.parent.name}: {reason}"
                )
                continue
            records.append(record)
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return RunScan(tuple(records), tuple(warnings))

    def find_by_input_hashes(self, input_hashes: dict[str, str]) -> RunScan:
        """全入力roleとSHA-256が一致するRunだけを返す。"""

        scanned = self.list_runs()
        return RunScan(
            tuple(
                record
                for record in scanned.records
                if record.input_hashes == input_hashes
            ),
            scanned.warnings,
        )

    def delete(self, run_id: str) -> None:
        """停止済みでroot直下にある実directoryだけを削除する。"""

        paths = self.paths(run_id)
        if not paths.root.exists():
            msg = f"run does not exist: {run_id}"
            raise FileNotFoundError(msg)
        if _is_link_or_junction(paths.root):
            msg = f"refusing to delete linked run path: {run_id}"
            raise ValueError(msg)
        resolved = paths.root.resolve(strict=True)
        if resolved.parent != self.root or resolved.name != run_id:
            msg = f"run path is outside repository root: {run_id}"
            raise ValueError(msg)
        record = self.load(run_id)
        if record.status == "running":
            msg = f"run is active: {run_id}"
            raise RuntimeError(msg)
        # Acquiring the same lock rejects deletion while another process is active.
        with OutputLock(paths.workspace):
            pass
        shutil.rmtree(resolved)


def _safe_role(role: str) -> str:
    value = "".join(character if character.isalnum() else "-" for character in role)
    value = value.strip("-")
    if not value:
        msg = "input role must contain an alphanumeric character"
        raise ValueError(msg)
    return value


def collect_input_sources(
    inputs: dict[str, Path],
    *,
    supported_extensions: set[str] | None = None,
    source_namespace: str | None = None,
) -> tuple[InputSource, ...]:
    """File/Directory入力を決定的なFile manifestへ展開する。"""

    sources: list[InputSource] = []
    logical_seen: set[str] = set()
    for role, supplied in sorted(inputs.items()):
        if _is_link_or_junction(supplied):
            msg = f"linked input is not allowed: {supplied}"
            raise ValueError(msg)
        root = supplied.resolve(strict=True)
        namespace = source_namespace or os.path.normcase(str(root))
        if root.is_file():
            candidates = [(root.name, root)]
        elif root.is_dir():
            candidates = []
            for child in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if _is_link_or_junction(child):
                    msg = f"linked input child is not allowed: {child}"
                    raise ValueError(msg)
                if not child.is_file():
                    continue
                resolved = child.resolve(strict=True)
                try:
                    relative = resolved.relative_to(root)
                except ValueError as error:
                    msg = f"input child is outside source root: {child}"
                    raise ValueError(msg) from error
                candidates.append((f"{root.name}/{relative.as_posix()}", resolved))
        else:
            msg = f"input must be a regular file or directory: {supplied}"
            raise ValueError(msg)

        accepted = 0
        for logical_path, source in candidates:
            if (
                supported_extensions is not None
                and source.suffix.casefold() not in supported_extensions
            ):
                continue
            normalized = logical_path.replace("\\", "/").strip("/")
            duplicate_key = normalized.casefold()
            if duplicate_key in logical_seen:
                msg = f"duplicate logical input path: {normalized}"
                raise ValueError(msg)
            logical_seen.add(duplicate_key)
            expanded_role = role if root.is_file() else f"{role}:{normalized}"
            key = None
            if supported_extensions is not None:
                key = hashlib.sha256(f"{namespace}\0{normalized}".encode()).hexdigest()
            sources.append(
                InputSource(
                    role=expanded_role,
                    path=source,
                    logical_path=normalized,
                    source_key=key,
                )
            )
            accepted += 1
        if accepted == 0:
            msg = f"no supported input files found: {supplied}"
            raise ValueError(msg)
    return tuple(sorted(sources, key=lambda item: (item.logical_path, item.role)))


def _safe_logical_path(value: str) -> Path:
    logical = Path(value.replace("\\", "/"))
    if logical.is_absolute() or not logical.parts or ".." in logical.parts:
        msg = f"unsafe logical input path: {value}"
        raise ValueError(msg)
    return logical


def _copy_verified(source: Path, target: Path) -> tuple[str, int]:
    """入力を固定sizeでcopyし、copy中にSHA-256を計算する。"""

    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copystat(source, target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), size


def _read_scanned_record(metadata: Path) -> RunRecord:
    RunRecord.validate_run_id(metadata.parent.name)
    record = RunRecord.model_validate_json(metadata.read_text(encoding="utf-8"))
    if metadata.parent.name != record.run_id:
        msg = "directory and metadata IDs differ"
        raise ValueError(msg)
    return record


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())
