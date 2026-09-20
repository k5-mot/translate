"""CLIとStreamlitで共有するRun選択、実行、Resumeおよびexport。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from translate.adapters.langfuse import bind_observation_context
from translate.adapters.qdrant import RegistrationSource, register_documents
from translate.common.fingerprint import (
    Fingerprint,
    ResumeCompatibility,
    build_fingerprint,
    check_resume_compatibility,
)
from translate.common.logger import configure_logging
from translate.common.progress import TaskStatusEvent, bind_task_status
from translate.common.redaction import credential_values, safe_failure_reason
from translate.common.runs import InputSource, collect_input_sources
from translate.common.workspace import (
    OutputLock,
    atomic_write_bytes,
    atomic_write_json,
    sha256_file,
)
from translate.tasks.docx import run as create_docx
from translate.workflows.comparison_review import run as run_review
from translate.workflows.translation import run as run_translation

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.progress import ProgressCallback, ProgressEvent
    from translate.common.runs import Operation, RunPaths, RunRecord, RunRepository
    from translate.common.settings import Backend, Settings


class ResumeRejectedError(ValueError):
    """指定Runが現在の入力・設定とは互換でない。"""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__("resume rejected: " + "; ".join(reasons))


LOGGER = logging.getLogger(__name__)


class FailureRecord(BaseModel):
    """本文とraw例外を含まない一回のRun失敗。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    task: str
    page: int | None = None
    group: str | None = None
    target_id: str | None = None
    error_type: str
    reason: str
    failed_at: datetime


class PublicRunError(RuntimeError):
    """公開entry pointへ返す、既にredactされたRun失敗。"""

    def __init__(self, failure: FailureRecord) -> None:
        self.failure = failure
        super().__init__(format_failure(failure))


@dataclass(frozen=True, slots=True)
class PreparedRun:
    """検証済みRunとRun内入力path。"""

    record: RunRecord
    paths: RunPaths
    inputs: dict[str, Path]
    resumed: bool


@dataclass(frozen=True, slots=True)
class RunCandidate:
    """同一入力Runと現在設定との互換性。"""

    record: RunRecord
    compatibility: ResumeCompatibility


def fingerprint_for(
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend = "llm",
    source_id: str | None = None,
) -> Fingerprint:
    """操作別のRule、用語集、Templateを含むfingerprintを作る。"""

    rules: dict[str, Path] = {}
    glossary: Path | None = None
    template: Path | None = None
    if operation == "translate":
        rules = {
            name: settings.templates_dir / f"{name}-rules.md"
            for name in ("structure", "translation", "review")
        }
        glossary = settings.templates_dir / "glossary.csv"
        template = settings.templates_dir / "template.docx"
    elif operation == "review":
        rules = {"review": settings.templates_dir / "review-rules.md"}
        glossary = settings.templates_dir / "glossary.csv"
    elif operation == "convert":
        template = inputs.get("reference_doc", settings.templates_dir / "template.docx")
    sources = _collect_sources(operation, inputs, source_id)
    hashes = {item.role: sha256_file(item.path) for item in sources}
    return build_fingerprint(
        operation=operation,
        backend=backend,
        input_hashes=hashes,
        settings=settings,
        rule_paths=rules,
        glossary_path=glossary,
        template_path=template,
        input_manifest=(
            [
                {
                    "role": item.role,
                    "logical_path": item.logical_path,
                    "source_key": item.source_key,
                    "size": item.path.stat().st_size,
                }
                for item in sources
            ]
            if operation == "register"
            else None
        ),
    )


def candidates_for(
    repository: RunRepository,
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend = "llm",
    source_id: str | None = None,
) -> tuple[RunCandidate, ...]:
    """同一入力かつ同じ操作のRunを新しい順に返す。"""

    current = fingerprint_for(operation, inputs, settings, backend, source_id)
    scanned = repository.find_by_input_hashes(current.snapshot["inputs"])
    return tuple(
        RunCandidate(record, check_resume_compatibility(record, current))
        for record in scanned.records
        if record.operation == operation
    )


def prepare_run(
    repository: RunRepository,
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend = "llm",
    resume_id: str | None = None,
    source_id: str | None = None,
) -> PreparedRun:
    """明示Runを検証して開くか、新しいRunと入力copyを作る。"""

    sources = _collect_sources(operation, inputs, source_id)
    current = fingerprint_for(operation, inputs, settings, backend, source_id)
    if resume_id is None:
        record = repository.create(operation, sources, current.snapshot, current.value)
        return PreparedRun(
            record,
            repository.paths(record.run_id),
            _copied_inputs(repository, record),
            False,
        )
    record = repository.load(resume_id)
    reasons: list[str] = []
    if record.operation != operation:
        reasons.append(f"operation: saved={record.operation!r}, current={operation!r}")
    compatibility = check_resume_compatibility(record, current)
    reasons.extend(compatibility.reasons)
    if operation == "register" and (
        record.schema_version < 2
        or any(item.source_key is None for item in record.inputs)
    ):
        reasons.append(
            "input schema: version 1 registration runs lack stable source keys; "
            "create a new run"
        )
    if reasons:
        raise ResumeRejectedError(tuple(reasons))
    return PreparedRun(
        record,
        repository.paths(record.run_id),
        _copied_inputs(repository, record),
        True,
    )


def execute_run(
    repository: RunRepository,
    prepared: PreparedRun,
    settings: Settings,
    backend: Backend = "llm",
    callback: ProgressCallback | None = None,
) -> tuple[RunRecord, tuple[Path, ...]]:
    """Run lock内で操作を実行し、成功・失敗statusと最後のTaskを保存する。"""

    record = repository.save(prepared.record.model_copy(update={"status": "running"}))
    configure_logging(
        prepared.paths.workspace / "logs" / "run.log",
        credential_values(settings),
    )

    failure_path = prepared.paths.workspace / "failure.json"
    failure_written = False
    observation_warnings = set(record.warnings)

    def progress(event: ProgressEvent) -> None:
        nonlocal record
        record = repository.save(record.model_copy(update={"last_task": event.task}))
        if callback is not None:
            callback(event)

    def task_status(event: TaskStatusEvent) -> None:
        nonlocal failure_written, record
        if event.phase in {"started", "failed"}:
            record = repository.save(
                record.model_copy(update={"last_task": event.task})
            )
        if event.phase != "failed":
            return
        error = event.error or RuntimeError("task failed")
        failure = FailureRecord(
            run_id=record.run_id,
            task=event.task,
            page=event.page,
            group=event.group,
            target_id=event.target_id,
            error_type=type(error).__name__,
            reason=safe_failure_reason(error),
            failed_at=datetime.now(UTC),
        )
        atomic_write_json(failure_path, failure.model_dump(mode="json"))
        LOGGER.error("Run task failed: %s", format_failure(failure))
        failure_written = True

    def observation_warning(warning: str) -> None:
        nonlocal record
        if warning in observation_warnings:
            return
        observation_warnings.add(warning)
        record = repository.save(
            record.model_copy(update={"warnings": [*record.warnings, warning]})
        )

    try:
        try:
            with (
                OutputLock(prepared.paths.workspace),
                bind_task_status(task_status),
                bind_observation_context(
                    credential_values(settings),
                    observation_warning,
                    prepared.record.operation.upper(),
                ),
            ):
                outputs = _execute_operation(prepared, settings, backend, progress)
        except Exception as error:
            if not failure_written:
                task_status(
                    TaskStatusEvent(
                        record.last_task or prepared.record.operation.upper(),
                        "failed",
                        error=error,
                    )
                )
            warning = safe_failure_reason(error)
            record = repository.save(
                record.model_copy(
                    update={
                        "status": "failed",
                        "warnings": [*record.warnings, warning],
                    }
                )
            )
            raise
        failure_path.unlink(missing_ok=True)
        record = repository.save(record.model_copy(update={"status": "completed"}))
        return record, outputs
    finally:
        # Release Windows FileHandler before export or Run deletion.
        configure_logging()


def execute_public_run(
    repository: RunRepository,
    prepared: PreparedRun,
    settings: Settings,
    backend: Backend = "llm",
    callback: ProgressCallback | None = None,
) -> tuple[RunRecord, tuple[Path, ...]]:
    """公開entry point向けにraw例外を安全なRun失敗へ変換する。"""

    try:
        return execute_run(repository, prepared, settings, backend, callback)
    except Exception as error:  # noqa: BLE001
        failure = load_failure(repository, prepared.record.run_id)
        if failure is None:
            failure = FailureRecord(
                run_id=prepared.record.run_id,
                task=prepared.record.last_task or prepared.record.operation.upper(),
                error_type=type(error).__name__,
                reason=safe_failure_reason(error),
                failed_at=datetime.now(UTC),
            )
        raise PublicRunError(failure) from None


def export_run(
    repository: RunRepository, run_id: str, destination: Path
) -> tuple[Path, ...]:
    """Run成果物をroot外へatomic copyし、Run削除から独立させる。"""

    record = repository.load(run_id)
    if record.status != "completed":
        msg = f"run is not completed: {run_id} ({record.status})"
        raise RuntimeError(msg)
    paths = repository.paths(run_id)
    exported: list[Path] = []
    for source in sorted(path for path in paths.outputs.rglob("*") if path.is_file()):
        target = destination / source.relative_to(paths.outputs)
        atomic_write_bytes(target, source.read_bytes())
        exported.append(target)
    if not exported:
        msg = f"run has no outputs: {run_id}"
        raise FileNotFoundError(msg)
    return tuple(exported)


def run_size(repository: RunRepository, run_id: str) -> int:
    """一覧表示用にRun directory内の通常File size合計を返す。"""

    root = repository.paths(run_id).root
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def load_failure(repository: RunRepository, run_id: str) -> FailureRecord | None:
    """Runのactive failureを検証して読む。"""

    path = repository.paths(run_id).workspace / "failure.json"
    if not path.exists():
        return None
    return FailureRecord.model_validate_json(path.read_text(encoding="utf-8"))


def format_failure(failure: FailureRecord) -> str:
    """CLI/UI共通の秘密を含まない失敗表示を作る。"""

    targets = [
        f"page={failure.page}" if failure.page is not None else None,
        f"group={failure.group}" if failure.group is not None else None,
        f"target={failure.target_id}" if failure.target_id is not None else None,
    ]
    suffix = " ".join(item for item in targets if item)
    prefix = f"run_id={failure.run_id} task={failure.task}"
    return f"{prefix} {suffix} cause={failure.reason}".replace("  ", " ")


def _copied_inputs(repository: RunRepository, record: RunRecord) -> dict[str, Path]:
    root = repository.paths(record.run_id).root
    return {item.role: root / item.relative_path for item in record.inputs}


def _collect_sources(
    operation: Operation,
    inputs: dict[str, Path],
    source_id: str | None,
) -> tuple[InputSource, ...]:
    extensions = (
        {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}
        if operation == "register"
        else None
    )
    return collect_input_sources(
        inputs,
        supported_extensions=extensions,
        source_namespace=source_id,
    )


def _execute_operation(
    prepared: PreparedRun,
    settings: Settings,
    backend: Backend,
    callback: ProgressCallback,
) -> tuple[Path, ...]:
    operation = prepared.record.operation
    if operation == "translate":
        result = run_translation(
            prepared.inputs["source"],
            prepared.paths.outputs,
            backend,
            settings,
            callback,
            prepared.paths.workspace,
        )
        return (result,)
    if operation == "review":
        result = run_review(
            prepared.inputs["source_en"],
            prepared.inputs["translation_ja"],
            prepared.paths.outputs / "review.md",
            settings,
            callback,
            prepared.paths.workspace,
        )
        return (result,)
    if operation == "register":
        count = register_documents(
            settings,
            [
                RegistrationSource(
                    path=prepared.paths.root / item.relative_path,
                    logical_path=item.logical_path or item.name,
                    source_key=item.source_key or "",
                )
                for item in prepared.record.inputs
            ],
        )
        result = prepared.paths.outputs / "registration.json"
        atomic_write_json(result, {"registered_chunks": count})
        return (result,)
    source = prepared.inputs["source"]
    template = prepared.inputs.get(
        "reference_doc", settings.templates_dir / "template.docx"
    )
    result = create_docx(
        source,
        prepared.paths.outputs / f"{source.stem}.docx",
        template,
    )
    return (result,)
