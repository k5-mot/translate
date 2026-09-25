"""Detached Run検証用の安全な終端Evidenceとwatchdog。"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, cast, get_args
from uuid import RFC_4122, UUID

import portalocker
from pydantic import BaseModel, ConfigDict, Field, field_validator

from translate.common.workspace import atomic_write_json, load_json

if TYPE_CHECKING:
    from translate.common.lifecycle import FailureRecord


@contextmanager
def _evidence_lock(path: Path) -> Iterator[None]:
    """Evidenceの読取りhandleとatomic replaceを同時に開かない。"""

    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # 小さいJSON I/O専用。従来Windows lockの約10秒の上限を維持し、
    # 短い競合は10ms間隔で待つ。モデル要求のtimeoutとは独立している。
    with portalocker.Lock(lock_path, mode="a+b", timeout=10, check_interval=0.01):
        yield


TerminalStatus = Literal[
    "running", "completed", "failed", "unexpected-exit", "timeout", "unknown"
]
TerminalPhase = Literal[
    "DOCILING",
    "SPLIT",
    "STRUCTURE",
    "TRANSLATE",
    "REVIEW",
    "DOCX",
    "REGISTER",
    "CONVERT",
    "WATCHDOG",
]
TerminalStage = Literal[
    "collect",
    "hash",
    "split",
    "extract",
    "write",
    "verify",
    "replace",
    "structure-input",
    "structure-output",
    "text-input",
    "text-invoke",
    "text-output",
    "text-parse",
    "vision-input",
    "vision-invoke",
    "vision-output",
    "vision-parse",
    "watchdog",
]
FailureKind = Literal["output-truncated"]
FinishReason = Literal["length"]
_TEMP_MARKER = ".detached-temp-root"
_CALL_COUNTS: ContextVar[dict[str, int] | None] = ContextVar(
    "translate_terminal_call_counts", default=None
)


@contextmanager
def bind_call_counts() -> Iterator[Mapping[str, int]]:
    """一回のchildだけの逐次外部call数を束縛する。"""

    counts = {"llm_calls": 0, "embedding_calls": 0, "qdrant_calls": 0}
    token = _CALL_COUNTS.set(counts)
    try:
        yield counts
    finally:
        _CALL_COUNTS.reset(token)


def count_external_call(kind: Literal["llm", "embedding", "qdrant"]) -> None:
    """外部adapterから本文なしの数値counterだけを進める。"""

    counts = _CALL_COUNTS.get()
    if counts is not None:
        counts[f"{kind}_calls"] += 1


def _canonical_run_id(value: str) -> str:
    """Evidenceの対象を取り違えないよう、IDを標準表記のRFC variant UUIDv7に限定する。"""

    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError("run_id must be a canonical UUIDv7") from error
    if parsed.version != 7 or parsed.variant != RFC_4122 or str(parsed) != value:
        raise ValueError("run_id must be a canonical UUIDv7")
    return value


def _safe_name(value: str | None) -> str | None:
    """80文字以内で英数字と限定記号からなる名前を受理する。値の機密性は判別しない。"""

    if value is None or not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > 80:
        return None
    if not all(character.isalnum() or character in "._:-" for character in stripped):
        return None
    return stripped


class TerminalEvidence(BaseModel):
    """本文を含まない、外部sinkへ保存可能な終端Evidence。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    run_id: str
    operation: Literal["translate", "review", "register", "convert"]
    status: TerminalStatus
    phase: TerminalPhase | None = None
    task: str | None = Field(default=None, max_length=80)
    current: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    stage: TerminalStage | None = None
    cause_type: str | None = Field(default=None, max_length=80)
    error_type: str | None = Field(default=None, max_length=80)
    failure_kind: FailureKind | None = None
    finish_reason: FinishReason | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    checkpoint_count: int = Field(default=0, ge=0)
    artifact_count: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    embedding_calls: int = Field(default=0, ge=0)
    qdrant_calls: int = Field(default=0, ge=0)
    started_at: datetime
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    child_pid: int | None = Field(default=None, ge=1)
    exit_code: int | None = None

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        """Evidence読込み時にもUUIDv7の表記制約を適用し、不正な対象IDを受理しない。"""

        return _canonical_run_id(value)

    @field_validator("task", "cause_type", "error_type")
    @classmethod
    def validate_safe_names(cls, value: str | None) -> str | None:
        """Task名と原因型を短い識別子へ制限し、本文や自由形式の例外messageの混入を抑止する。"""

        safe = _safe_name(value)
        if value is not None and safe is None:
            raise ValueError("Evidence names must be short safe identifiers")
        return safe

    def with_update(self, **updates: object) -> Self:
        """終端statusから別statusへの変更を拒否し、全fieldを再検証した新しい値を返す。"""

        next_status = updates.get("status", self.status)
        terminal: tuple[TerminalStatus, ...] = (
            "completed",
            "failed",
            "unexpected-exit",
            "timeout",
            "unknown",
        )
        if self.status in terminal and next_status != self.status:
            raise ValueError("terminal Evidence status cannot transition again")
        values = {**self.model_dump(mode="python"), **updates}
        return self.__class__.model_validate(values)


class EvidenceStore:
    """temp root外へTerminalEvidenceをatomic保存する。"""

    def __init__(self, path: Path, *, temp_root: Path | None = None) -> None:
        """Evidenceの保存先を絶対pathへ固定し、一時領域削除で検証結果まで失われる配置を拒否する。"""

        # Windowsのresolveもhandleを開くため、JSONのread/writeと排他する。
        with _evidence_lock(path):
            self.path = path.resolve()
        self.temp_root = temp_root.resolve() if temp_root is not None else None
        if self.temp_root is not None and self.path.is_relative_to(self.temp_root):
            raise ValueError("terminal Evidence must be outside the temp Run root")

    def write(self, evidence: TerminalEvidence) -> TerminalEvidence:
        """検証済みEvidenceをatomic writeする。"""

        with _evidence_lock(self.path):
            existing = self._read_locked()
            if (
                existing is not None
                and existing.status not in {"running", "unknown"}
                and evidence.status == "running"
            ):
                # A stale parent heartbeat must never overwrite a terminal
                # child result when both processes race on the evidence file.
                return existing
            atomic_write_json(self.path, evidence.model_dump(mode="json"))
        return evidence

    def read(self) -> TerminalEvidence | None:
        """壊れたまたは未作成Evidenceを成功扱いせずNoneで返す。"""

        with _evidence_lock(self.path):
            if not self.path.exists():
                return None
            return self._read_locked()

    def _read_locked(self) -> TerminalEvidence | None:
        """取得済みlock内でのみ読む。writeからの二重lockを避ける。"""

        try:
            value = load_json(self.path)
            if not isinstance(value, Mapping):
                return None
            return TerminalEvidence.model_validate(value)
        except (TypeError, ValueError):
            return None

    def contains_valid_terminal(self) -> bool:
        """terminal statusを持つ安全なEvidenceか確認する。"""

        value = self.read()
        return value is not None and value.status not in {"running", "unknown"}

    def allows_public_resume(self) -> bool:
        """completed・exit 0・終了時刻ありの保存値をGate通過とする。flush自体は検証しない。"""

        value = self.read()
        return bool(
            value is not None
            and value.status == "completed"
            and value.exit_code == 0
            and value.finished_at is not None
        )


def evidence_from_progress(
    event: object,
    *,
    run_id: str,
    operation: Literal["translate", "review", "register", "convert"],
    started_at: datetime,
    previous: TerminalEvidence | None = None,
    child_pid: int | None = None,
) -> TerminalEvidence:
    """ProgressEventからsafeなrunning Evidenceを作る。"""

    task = _safe_name(getattr(event, "task", None))
    phase = _safe_phase(task)
    now = datetime.now(UTC)
    return TerminalEvidence(
        run_id=run_id,
        operation=operation,
        status="running",
        phase=phase,
        task=task,
        current=_nonnegative_int(getattr(event, "current", 0)),
        total=_nonnegative_int(getattr(event, "total", 0)),
        started_at=started_at,
        heartbeat_at=now,
        child_pid=child_pid
        if child_pid is not None
        else getattr(previous, "child_pid", None),
        checkpoint_count=getattr(previous, "checkpoint_count", 0),
        artifact_count=getattr(previous, "artifact_count", 0),
        llm_calls=getattr(previous, "llm_calls", 0),
        embedding_calls=getattr(previous, "embedding_calls", 0),
        qdrant_calls=getattr(previous, "qdrant_calls", 0),
    )


def evidence_from_failure(
    failure: FailureRecord,
    *,
    started_at: datetime,
    previous: TerminalEvidence | None = None,
    child_pid: int | None = None,
    exit_code: int | None = None,
) -> TerminalEvidence:
    """PublicRunErrorのFailureRecordから本文なしEvidenceを作る。"""

    run_id = _canonical_run_id(str(failure.run_id))
    operation = _operation_from_previous(previous)
    return TerminalEvidence(
        run_id=run_id,
        operation=operation,
        status="failed",
        phase=_safe_phase(getattr(failure, "task", None)),
        task=_safe_name(getattr(failure, "task", None)),
        stage=_safe_stage(getattr(failure, "stage", None)),
        cause_type=_safe_name(getattr(failure, "cause_type", None)),
        error_type=_safe_name(getattr(failure, "error_type", None)),
        failure_kind=getattr(failure, "failure_kind", None),
        finish_reason=getattr(failure, "finish_reason", None),
        input_tokens=_optional_nonnegative_int(getattr(failure, "input_tokens", None)),
        output_tokens=_optional_nonnegative_int(
            getattr(failure, "output_tokens", None)
        ),
        total_tokens=_optional_nonnegative_int(getattr(failure, "total_tokens", None)),
        started_at=started_at,
        heartbeat_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        child_pid=child_pid,
        exit_code=exit_code,
        current=getattr(previous, "current", 0),
        total=getattr(previous, "total", 0),
        checkpoint_count=getattr(previous, "checkpoint_count", 0),
        artifact_count=getattr(previous, "artifact_count", 0),
        llm_calls=getattr(previous, "llm_calls", 0),
        embedding_calls=getattr(previous, "embedding_calls", 0),
        qdrant_calls=getattr(previous, "qdrant_calls", 0),
    )


def workspace_counts(root: Path) -> dict[str, int]:
    """root内の.workspaceとoutputsのFile数を返す。checkpoint_countはGraph履歴件数ではない。"""

    resolved = root.resolve()
    if not resolved.exists() or not resolved.is_dir():
        return {"checkpoint_count": 0, "artifact_count": 0}
    workspace = resolved / ".workspace"
    outputs = resolved / "outputs"
    checkpoint_count = (
        sum(
            1
            for path in workspace.rglob("*")
            if path.is_file() and path.resolve().is_relative_to(resolved)
        )
        if workspace.exists()
        else 0
    )
    artifact_count = (
        sum(
            1
            for path in outputs.rglob("*")
            if path.is_file() and path.resolve().is_relative_to(resolved)
        )
        if outputs.exists()
        else 0
    )
    return {
        "checkpoint_count": checkpoint_count,
        "artifact_count": artifact_count,
    }


class DetachedResult(BaseModel):
    """watchdogが回収した終端結果。"""

    model_config = ConfigDict(frozen=True)

    evidence: TerminalEvidence
    exit_code: int | None


def run_public_run_detached(
    repository_root: Path,
    run_id: str,
    operation: Literal["translate", "review", "register", "convert"],
    backend: Literal["llm", "libretranslate"],
    *,
    evidence_path: Path,
    temp_root: Path,
    timeout_seconds: float = 900.0,
    poll_seconds: float = 0.25,
    cwd: Path | None = None,
) -> DetachedResult:
    """既存public lifecycleへ委譲するdetached childを一度だけ実行する。"""

    _canonical_run_id(run_id)
    temp_root = temp_root.resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        temp_root / _TEMP_MARKER,
        {"version": 1, "run_id": run_id, "purpose": "detached-run"},
    )
    heartbeat_path = temp_root / "detached-heartbeat.json"
    request_path = temp_root / "detached-request.json"
    atomic_write_json(
        request_path,
        {
            "repository_root": str(repository_root.resolve()),
            "run_id": run_id,
            "operation": operation,
            "backend": backend,
            "evidence_path": str(evidence_path.resolve()),
            "heartbeat_path": str(heartbeat_path),
        },
    )
    try:
        return run_detached(
            [
                sys.executable,
                "-m",
                "translate.common.terminal_evidence",
                "--child",
                str(request_path),
            ],
            run_id=run_id,
            operation=operation,
            evidence_path=evidence_path,
            temp_root=temp_root,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            heartbeat_path=heartbeat_path,
            cwd=cwd,
        )
    finally:
        request_path.unlink(missing_ok=True)
        heartbeat_path.unlink(missing_ok=True)
        cleanup_detached_temp(temp_root)


def cleanup_detached_temp(temp_root: Path) -> bool:
    """解決済みrootに既知形式のmarkerがあることを確認して削除する。

    解決前のpathがリンクか、markerのIDが今回の実行と一致するかは検査しない。
    """

    root = temp_root.resolve()
    marker = root / _TEMP_MARKER
    if not root.exists():
        return False
    if root.is_symlink() or marker.is_symlink() or not marker.is_file():
        raise ValueError("refusing to delete an unmarked or linked temp root")
    value = load_json(marker)
    if (
        not isinstance(value, Mapping)
        or value.get("version") != 1
        or value.get("purpose") != "detached-run"
        or not isinstance(value.get("run_id"), str)
    ):
        raise ValueError("invalid detached temp marker")
    shutil.rmtree(root)
    return True


def run_detached(
    command: Sequence[str],
    *,
    run_id: str,
    operation: Literal["translate", "review", "register", "convert"],
    evidence_path: Path,
    temp_root: Path,
    timeout_seconds: float = 900.0,
    poll_seconds: float = 0.25,
    heartbeat_path: Path | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> DetachedResult:
    """childを一度だけ起動し、stdoutを保存せず終端Evidenceを回収する。"""

    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("watchdog timeouts must be positive")
    store = EvidenceStore(evidence_path, temp_root=temp_root)
    started_at = datetime.now(UTC)
    _canonical_run_id(run_id)
    base = TerminalEvidence(
        run_id=run_id,
        operation=operation,
        status="running",
        started_at=started_at,
        heartbeat_at=started_at,
    )
    store.write(base)
    # Publish the running marker before spawning the child.  Otherwise a very
    # short child can write terminal evidence which the parent then overwrites.
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
    )
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    while process.poll() is None:
        heartbeat = _read_heartbeat(heartbeat_path, store)
        current = store.read()
        if heartbeat is not None and (current is None or current.status == "running"):
            if (
                current is None
                or current.heartbeat_at is None
                or heartbeat.heartbeat_at is None
                or heartbeat.heartbeat_at > current.heartbeat_at
            ):
                store.write(heartbeat.with_update(child_pid=process.pid))
            elif current is not None:
                store.write(
                    current.with_update(
                        heartbeat_at=datetime.now(UTC), child_pid=process.pid
                    )
                )
        elif current is not None and current.status == "running":
            store.write(
                current.with_update(
                    heartbeat_at=datetime.now(UTC), child_pid=process.pid
                )
            )
        if time.monotonic() >= deadline:
            timed_out = True
            process.terminate()
            break
        time.sleep(poll_seconds)
    if timed_out:
        try:
            process.wait(timeout=min(10.0, timeout_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        current = store.read() or base
        result = current.with_update(
            status="timeout",
            stage="watchdog",
            cause_type="watchdog-timeout",
            finished_at=datetime.now(UTC),
            child_pid=process.pid,
            exit_code=process.returncode,
        )
        store.write(result)
        return DetachedResult(evidence=result, exit_code=process.returncode)

    exit_code = process.returncode
    current = store.read()
    if current is None:
        # No child status is an unexpected exit, never a successful completion.
        current = base
    if current.status == "completed" and exit_code == 0:
        status: TerminalStatus = "completed"
    elif current.status == "failed" or (exit_code is not None and exit_code != 0):
        status = "failed"
    else:
        status = "unexpected-exit"
    result = current.with_update(
        status=status,
        finished_at=datetime.now(UTC),
        child_pid=process.pid,
        exit_code=exit_code,
        cause_type=(
            current.cause_type if status != "unexpected-exit" else "child-exit"
        ),
    )
    store.write(result)
    return DetachedResult(evidence=result, exit_code=exit_code)


def _read_heartbeat(
    heartbeat_path: Path | None, store: EvidenceStore
) -> TerminalEvidence | None:
    """有効なheartbeatを読込み、保存EvidenceがあればそのID・操作へ上書きして返す。"""

    if heartbeat_path is None:
        return None
    value = EvidenceStore(heartbeat_path).read()
    if value is None:
        return None
    try:
        previous = store.read()
        return value.with_update(
            status="running",
            run_id=previous.run_id if previous is not None else value.run_id,
            operation=previous.operation if previous is not None else value.operation,
        )
    except (TypeError, ValueError):
        return None


def _operation_from_previous(
    previous: TerminalEvidence | None,
) -> Literal["translate", "review", "register", "convert"]:
    """失敗Evidenceへ直前の操作種別を引き継ぎ、記録がなければtranslateを既定値とする。"""

    return previous.operation if previous is not None else "translate"


def _safe_phase(value: str | None) -> TerminalPhase | None:
    """Task名を大文字に揃え、検証Evidenceで許可されたphaseだけを採用する。"""

    if value is None:
        return None
    upper = value.upper()
    return cast("TerminalPhase", upper) if upper in get_args(TerminalPhase) else None


def _safe_stage(value: object) -> TerminalStage | None:
    """stageを固定の許可集合に限定し、任意の文字列をEvidenceへ載せない。"""

    return cast("TerminalStage", value) if value in get_args(TerminalStage) else None


def _nonnegative_int(value: object) -> int:
    """件数からbool・負値・非整数を除き、不正値は0としてEvidenceを構成する。"""

    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _optional_nonnegative_int(value: object) -> int | None:
    """未取得token数はNoneのまま残し、値がある場合は非負整数の診断値へ揃える。"""

    return _nonnegative_int(value) if value is not None else None


def _child_parser() -> argparse.ArgumentParser:
    """debug childの起動要求Fileのpathだけを受け取る引数parserを用意する。"""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--child", type=Path)
    return parser


def _child_entry(spec_path: Path) -> int:  # noqa: PLR0911
    """既存`execute_public_run()`へ委譲するchild境界。"""

    value = load_json(spec_path)
    spec_path.unlink(missing_ok=True)
    if not isinstance(value, Mapping):
        return 2
    try:
        repository_root = Path(value["repository_root"])
        run_id = _canonical_run_id(str(value["run_id"]))
        operation = value["operation"]
        backend = value["backend"]
        evidence_path = Path(value["evidence_path"])
        heartbeat_path = Path(value["heartbeat_path"])
        if operation not in get_args(
            Literal["translate", "review", "register", "convert"]
        ):
            return 2
        if backend not in get_args(Literal["llm", "libretranslate"]):
            return 2
        from translate.common.lifecycle import (  # noqa: PLC0415
            PreparedRun,
            PublicRunError,
            execute_public_run,
        )
        from translate.common.runs import RunRepository  # noqa: PLC0415
        from translate.common.settings import load_settings  # noqa: PLC0415

        repository = RunRepository(repository_root)
        record = repository.load(run_id)
        paths = repository.paths(run_id)
        inputs = {item.role: paths.root / item.relative_path for item in record.inputs}
        prepared = PreparedRun(record, paths, inputs, True)
        settings = load_settings(operation, backend)
        started_at = datetime.now(UTC)
        store = EvidenceStore(evidence_path, temp_root=paths.root)
        heartbeat_store = EvidenceStore(heartbeat_path)

        def callback(event: object) -> None:
            """製品の進捗を本文なしのheartbeatへ変換し、外部Evidenceと監視用Fileへ保存する。"""

            heartbeat = evidence_from_progress(
                event,
                run_id=run_id,
                operation=operation,
                started_at=started_at,
                previous=store.read(),
            )
            store.write(heartbeat)
            heartbeat_store.write(heartbeat)

        initial = TerminalEvidence(
            run_id=run_id,
            operation=operation,
            status="running",
            started_at=started_at,
            heartbeat_at=started_at,
        )
        store.write(initial)
        heartbeat_store.write(initial)
        with bind_call_counts() as call_counts:
            try:
                execute_public_run(repository, prepared, settings, backend, callback)
            except PublicRunError as error:
                failed = evidence_from_failure(
                    error.failure,
                    started_at=started_at,
                    previous=store.read(),
                ).with_update(**call_counts)
                store.write(failed)
                return 1
            else:
                counts = workspace_counts(paths.root)
                completed = (store.read() or initial).with_update(
                    status="completed",
                    finished_at=datetime.now(UTC),
                    heartbeat_at=datetime.now(UTC),
                    **counts,
                    **call_counts,
                )
                store.write(completed)
                return 0
    except Exception:  # noqa: BLE001
        return 2


def main() -> None:
    """Debug-only child entrypoint; product interface remains cli.py/main.py."""

    args = _child_parser().parse_args()
    if args.child is not None:
        raise SystemExit(_child_entry(args.child))


if __name__ == "__main__":
    main()
