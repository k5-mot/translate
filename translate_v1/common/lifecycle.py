"""CLIとStreamlitで共有するRun選択、実行、Resumeおよびexport。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from translate_v1.adapters.langfuse import bind_observation_context
from translate_v1.adapters.llm import LLM_STAGES, LLMStage
from translate_v1.adapters.qdrant import (
    RegistrationSource,
    RegistrationStage,
    register_documents,
)
from translate_v1.common.fingerprint import (
    Fingerprint,
    ResumeCompatibility,
    build_fingerprint,
    check_resume_compatibility,
)
from translate_v1.common.logger import configure_logging
from translate_v1.common.progress import TaskStatusEvent, bind_task_status
from translate_v1.common.redaction import credential_values, safe_failure_reason
from translate_v1.common.runs import InputSource, collect_input_sources
from translate_v1.common.workspace import (
    OutputInUseError,
    OutputLock,
    atomic_write_bytes,
    atomic_write_json,
    sha256_file,
)
from translate_v1.tasks.docx import run as create_docx
from translate_v1.workflows.comparison_review import run as run_review
from translate_v1.workflows.translation import run as run_translation

if TYPE_CHECKING:
    from pathlib import Path

    from translate_v1.common.progress import ProgressCallback, ProgressEvent
    from translate_v1.common.runs import Operation, RunPaths, RunRecord, RunRepository
    from translate_v1.common.settings import Backend, Settings


class ResumeRejectedError(ValueError):
    """指定Runが現在の入力・設定とは互換でない。"""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        """再開できない項目別の理由を保持し、CLIとUIへ共通の拒否説明を渡す。"""

        self.reasons = reasons
        super().__init__("resume rejected: " + "; ".join(reasons))


LOGGER = logging.getLogger(__name__)
FailureStage = RegistrationStage | LLMStage
FAILURE_STAGES: tuple[FailureStage, ...] = (
    "collect",
    "hash",
    "split",
    "extract",
    "write",
    "verify",
    "replace",
    *LLM_STAGES,
)


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
    stage: FailureStage | None = None
    cause_type: str | None = None
    failure_kind: Literal["output-truncated", "context-exceeded"] | None = None
    finish_reason: Literal["length"] | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    failed_at: datetime


class PublicRunError(RuntimeError):
    """公開entry pointへ返す、既にredactされたRun失敗。"""

    def __init__(self, failure: FailureRecord) -> None:
        """失敗情報を保持し、公開入口へ渡すメッセージを共通の診断表示形式に揃える。"""

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

    # 拒否側はmetadata・失敗記録・所有者のlog設定へ一切触れない。
    with OutputLock(prepared.paths.workspace):
        record = repository.load(prepared.record.run_id)
        record = repository.save(record.model_copy(update={"status": "running"}))
        configure_logging(
            prepared.paths.workspace / "logs" / "run.log",
            credential_values(settings),
        )

        failure_path = prepared.paths.workspace / "failure.json"
        failure_written = False
        observation_warnings = set(record.warnings)

        def progress(event: ProgressEvent) -> None:
            """所有権を保持した呼出の進捗を保存して利用者へ通知する。"""

            nonlocal record
            record = repository.save(
                record.model_copy(update={"last_task": event.task})
            )
            if callback is not None:
                callback(event)

        def task_status(event: TaskStatusEvent) -> None:
            """所有者のTask境界と安全な障害情報を排他保持中に記録する。"""

            nonlocal failure_written, record
            if event.phase in {"started", "failed"}:
                record = repository.save(
                    record.model_copy(update={"last_task": event.task})
                )
            if event.phase != "failed":
                return
            error = event.error or RuntimeError("task failed")
            stage, cause_type = _safe_diagnostics(event.stage, event.cause_type, error)
            output_diagnostics = _safe_output_diagnostics(event, error, stage)
            failure = FailureRecord(
                run_id=record.run_id,
                task=event.task,
                page=event.page,
                group=event.group,
                target_id=event.target_id,
                error_type=type(error).__name__,
                reason=safe_failure_reason(error),
                stage=stage,
                cause_type=cause_type,
                failure_kind=output_diagnostics[0],
                finish_reason=output_diagnostics[1],
                input_tokens=output_diagnostics[2],
                output_tokens=output_diagnostics[3],
                total_tokens=output_diagnostics[4],
                failed_at=datetime.now(UTC),
            )
            atomic_write_json(failure_path, failure.model_dump(mode="json"))
            LOGGER.error("Run task failed: %s", format_failure(failure))
            failure_written = True

        def observation_warning(warning: str) -> None:
            """同じ観測警告を重複保存せず、所有者のmetadataへ追加する。"""

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
        # 排他拒否は今回の呼出だけのErrorであり、所有者の過去の失敗とは別。
        failure = (
            None
            if isinstance(error, OutputInUseError)
            else load_failure(repository, prepared.record.run_id)
        )
        if failure is None:
            stage, cause_type = _safe_diagnostics(None, None, error)
            output_diagnostics = _safe_output_diagnostics(None, error, stage)
            failure = FailureRecord(
                run_id=prepared.record.run_id,
                task=(
                    prepared.record.operation.upper()
                    if isinstance(error, OutputInUseError)
                    else prepared.record.last_task or prepared.record.operation.upper()
                ),
                error_type=type(error).__name__,
                reason=safe_failure_reason(error),
                stage=stage,
                cause_type=cause_type,
                failure_kind=output_diagnostics[0],
                finish_reason=output_diagnostics[1],
                input_tokens=output_diagnostics[2],
                output_tokens=output_diagnostics[3],
                total_tokens=output_diagnostics[4],
                failed_at=datetime.now(UTC),
            )
        raise PublicRunError(failure) from None


def export_run(
    repository: RunRepository, run_id: str, destination: Path
) -> tuple[Path, ...]:
    """完了Runの成果物を指定先へFile単位で置換copyする。指定先がroot外かは検査しない。"""

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
    """FailureRecordの値をCLI/UI共通形式に整える。値の秘密除去はこの関数では行わない。"""

    targets = [
        f"page={failure.page}" if failure.page is not None else None,
        f"group={failure.group}" if failure.group is not None else None,
        f"target={failure.target_id}" if failure.target_id is not None else None,
        f"stage={failure.stage}" if failure.stage is not None else None,
        (f"kind={failure.failure_kind}" if failure.failure_kind is not None else None),
        (
            f"finish_reason={failure.finish_reason}"
            if failure.finish_reason is not None
            else None
        ),
        (
            f"input_tokens={failure.input_tokens}"
            if failure.input_tokens is not None
            else None
        ),
        (
            f"output_tokens={failure.output_tokens}"
            if failure.output_tokens is not None
            else None
        ),
        (
            f"total_tokens={failure.total_tokens}"
            if failure.total_tokens is not None
            else None
        ),
    ]
    suffix = " ".join(item for item in targets if item)
    prefix = f"run_id={failure.run_id} task={failure.task}"
    cause = failure.cause_type or failure.reason
    return f"{prefix} {suffix} cause={cause}".replace("  ", " ")


def _safe_diagnostics(
    stage: str | None,
    cause_type: str | None,
    error: BaseException,
) -> tuple[FailureStage | None, str | None]:
    """固定stageと例外型identifierだけをFailureへ許可する。"""

    candidate_stage = stage or getattr(error, "stage", None)
    candidate_cause = cause_type or getattr(error, "cause_type", None)
    safe_stage: FailureStage | None = (
        candidate_stage if candidate_stage in FAILURE_STAGES else None
    )
    safe_cause = (
        candidate_cause
        if safe_stage is not None
        and isinstance(candidate_cause, str)
        and candidate_cause.isidentifier()
        else None
    )
    return safe_stage, safe_cause


def _safe_output_diagnostics(
    event: TaskStatusEvent | None,
    error: BaseException,
    stage: FailureStage | None,
) -> tuple[
    Literal["output-truncated", "context-exceeded"] | None,
    Literal["length"] | None,
    int | None,
    int | None,
    int | None,
]:
    """許可したLLM stageに対して、既知の失敗分類と非負整数のtoken数だけを採用する。"""

    if stage not in {
        "text-invoke",
        "vision-invoke",
        "text-output",
        "vision-output",
    }:
        return None, None, None, None, None
    kind = (
        event.failure_kind
        if event is not None and event.failure_kind is not None
        else getattr(error, "failure_kind", None)
    )
    reason = (
        event.finish_reason
        if event is not None and event.finish_reason is not None
        else getattr(error, "finish_reason", None)
    )
    if kind == "context-exceeded" and stage in {"text-invoke", "vision-invoke"}:
        reason = None
    elif kind != "output-truncated" or reason != "length":
        return None, None, None, None, None

    def count(name: str) -> int | None:
        """Task通知を優先してtoken数を取得し、bool・負値・非整数を公開診断から除外する。"""

        value = getattr(event, name) if event is not None else None
        if value is None:
            value = getattr(error, name, None)
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else None
        )

    return (
        kind,
        reason,
        count("input_tokens"),
        count("output_tokens"),
        count("total_tokens"),
    )


def _copied_inputs(repository: RunRepository, record: RunRecord) -> dict[str, Path]:
    """元の入力pathへ戻らず処理するため、保存済み入力copyをrole別のpathへ解決する。"""

    root = repository.paths(record.run_id).root
    return {item.role: root / item.relative_path for item in record.inputs}


def _collect_sources(
    operation: Operation,
    inputs: dict[str, Path],
    source_id: str | None,
) -> tuple[InputSource, ...]:
    """登録時だけ拡張子制限とnamespaceを適用し、公開操作の入力を検証済み一覧へ展開する。"""

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
    """準備済み入力を翻訳・比較・登録・DOCX変換へ渡し、公開成果物のpathを揃えて返す。"""

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
            prepared.paths.workspace / "registration",
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
