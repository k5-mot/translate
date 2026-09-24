"""Task失敗の保存、公開表示、Resume後の解消を検証する。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.exceptions import OutputParserException
from typer.testing import CliRunner

import cli
from translate.adapters.llm import LLMError, LLMOutputTruncatedError
from translate.adapters.qdrant import RegistrationError, RegistrationStage
from translate.common.lifecycle import (
    FailureRecord,
    PublicRunError,
    execute_public_run,
    execute_run,
    prepare_run,
)
from translate.common.progress import TaskStatusEvent, report_task_status
from translate.common.runs import RunRepository
from translate.common.workspace import atomic_write_bytes
from translate.tasks.structure import StructurePageError

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.progress import ProgressCallback
    from translate.common.settings import Backend, Settings


def _templates(root: Path) -> Path:
    """
    Run準備に必要なTemplate群を隔離領域へ用意し、失敗契約の検証を設定不足から切り離す。
    """

    root.mkdir()
    for name in ("structure", "translation", "review"):
        (root / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (root / "glossary.csv").write_text("english,japanese\n", encoding="utf-8")
    (root / "template.docx").write_bytes(b"template")
    return root


@pytest.mark.integration
def test_failure_record_is_safe_and_removed_after_resume(  # noqa: PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """失敗Taskを構造化保存し、成功Resume時だけactive failureを消す。"""

    secret = "secret-credential-value"  # noqa: S105
    body = "SOURCE-BODY-MUST-NOT-PERSIST"
    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
        openai_api_key=secret,
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings)
    attempts = 0

    class ServiceError(OSError):
        page = 4
        group = "group-2"
        target_id = "body/7"

    def workflow(
        _source: Path,
        output_dir: Path,
        _backend: Backend,
        _settings: Settings,
        _callback: ProgressCallback | None,
        _workspace: Path | None,
    ) -> Path:
        """
        初回は機密値入りのTask障害を通知し、再開時は成果物と完了通知を返して失敗記録の解
        消を検証する。
        """

        nonlocal attempts
        attempts += 1
        report_task_status(TaskStatusEvent("TRANSLATE", "started"))
        if attempts == 1:
            error = ServiceError(f"token={secret} body={body}")
            report_task_status(
                TaskStatusEvent(
                    "TRANSLATE",
                    "failed",
                    page=error.page,
                    group=error.group,
                    target_id=error.target_id,
                    error=error,
                )
            )
            raise error
        output = output_dir / "document.ja.docx"
        atomic_write_bytes(output, b"done")
        report_task_status(TaskStatusEvent("TRANSLATE", "completed"))
        return output

    monkeypatch.setattr("translate.common.lifecycle.run_translation", workflow)

    with pytest.raises(ServiceError):
        execute_run(repository, prepared, settings)

    failure_path = prepared.paths.workspace / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure["run_id"] == prepared.record.run_id
    assert failure["task"] == "TRANSLATE"
    assert failure["page"] == 4
    assert failure["group"] == "group-2"
    assert failure["target_id"] == "body/7"
    assert failure["error_type"] == "ServiceError"
    assert failure["reason"] == "ServiceError"
    assert secret not in failure_path.read_text(encoding="utf-8")
    assert body not in failure_path.read_text(encoding="utf-8")

    log_path = prepared.paths.workspace / "logs" / "run.log"
    failed_log = log_path.read_text(encoding="utf-8")
    assert "task=TRANSLATE" in failed_log
    assert "page=4" in failed_log
    assert secret not in failed_log
    assert body not in failed_log

    resumed = prepare_run(
        repository,
        "translate",
        {"source": source},
        settings,
        resume_id=prepared.record.run_id,
    )
    completed, outputs = execute_run(repository, resumed, settings)

    assert completed.status == "completed"
    assert outputs[0].read_bytes() == b"done"
    assert not failure_path.exists()
    assert "task=TRANSLATE" in log_path.read_text(encoding="utf-8")


def test_cli_failure_boundary_does_not_render_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLIは構造化された安全な原因だけを非zero終了で表示する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    failure = FailureRecord(
        run_id="run-safe",
        task="DOCLING",
        page=3,
        target_id="source",
        error_type="ServiceFailure",
        reason="ServiceFailure status=503",
        failed_at="2026-09-20T00:00:00Z",
    )

    monkeypatch.setattr(cli, "load_settings", lambda *_args: object())
    monkeypatch.setattr(cli, "_prepare", lambda *_args: (object(), object()))

    def fail(*_args: object, **_kwargs: object) -> object:
        """安全なFailureRecordを持つ公開例外を投げ、CLIの表示と終了codeを検査する。"""

        raise PublicRunError(failure)

    monkeypatch.setattr(cli, "execute_public_run", fail)
    result = CliRunner().invoke(
        cli.app,
        ["translate", str(source), "--output-dir", str(tmp_path / "out")],
    )

    assert result.exit_code == 1
    assert "run_id=run-safe task=DOCLING" in result.output
    assert "page=3" in result.output
    assert "status=503" in result.output
    assert "Traceback" not in result.output


def test_cli_process_failure_is_safe_and_nonzero(tmp_path: Path) -> None:
    """実CLI processの変換失敗はtracebackや入力本文を公開しない。"""

    sentinel = "DOCUMENT-BODY-SENTINEL"
    source = tmp_path / "source.md"
    source.write_text(sentinel, encoding="utf-8")
    reference = tmp_path / "invalid.docx"
    reference.write_text("not a zip", encoding="utf-8")
    environment = os.environ.copy()
    environment["TRANSLATE_RUNS_DIR"] = str(tmp_path / "runs")

    completed = subprocess.run(
        [
            sys.executable,
            str(cli.__file__),
            "convert",
            str(source),
            "--output",
            str(tmp_path / "output.docx"),
            "--reference-doc",
            str(reference),
        ],
        cwd=Path(cli.__file__).parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode != 0
    assert "run_id=" in output
    assert "task=CONVERT" in output
    assert "cause=RuntimeError" in output
    assert sentinel not in output
    assert "Traceback" not in output


def test_registration_error_exposes_only_allowlisted_stage_and_cause_type() -> None:
    """登録Errorへraw response、path、job IDおよび本文を転記しない。"""

    sentinel = "SECRET body=/private/input.pdf job_id=docling-123 raw=response"
    for stage in (
        "collect",
        "hash",
        "split",
        "extract",
        "write",
        "verify",
        "replace",
    ):
        error = RegistrationError(stage, RuntimeError(sentinel))
        assert error.stage == stage
        assert error.cause_type == "RuntimeError"
        assert sentinel not in str(error)
        assert "private" not in str(error)
        assert "docling-123" not in str(error)

    with pytest.raises(ValueError, match="invalid registration stage"):
        RegistrationError("unknown", RuntimeError(sentinel))  # type: ignore[arg-type]


def test_legacy_failure_json_remains_readable() -> None:
    """stage追加前のfailure JSONはoptional fieldなしで読める。"""

    failure = FailureRecord.model_validate_json(
        json.dumps(
            {
                "run_id": "legacy",
                "task": "REGISTER",
                "error_type": "RuntimeError",
                "reason": "RuntimeError",
                "failed_at": "2026-09-20T00:00:00Z",
            }
        )
    )

    assert failure.stage is None
    assert failure.cause_type is None
    assert failure.failure_kind is None
    assert failure.finish_reason is None
    assert failure.input_tokens is None
    assert failure.output_tokens is None
    assert failure.total_tokens is None


@pytest.mark.integration
def test_output_truncation_is_safe_atomic_and_backward_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """出力枯渇のallowlist診断だけを保存し、途中成果物を公開しない。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings)

    def workflow(*_args: object, **_kwargs: object) -> Path:
        """
        STRUCTUREの出力切断とusageを通知し、公開診断への伝播と成果物未公開を検証する。
        """

        llm_error = LLMError(
            "text-output",
            LLMOutputTruncatedError(),
            failure_kind="output-truncated",
            finish_reason="length",
            input_tokens=1_328,
            output_tokens=4_096,
            total_tokens=5_424,
        )
        error = StructurePageError(3, "page/3", llm_error)
        report_task_status(
            TaskStatusEvent(
                "STRUCTURE",
                "failed",
                page=error.page,
                target_id=error.target_id,
                stage=error.stage,
                cause_type=error.cause_type,
                failure_kind=error.failure_kind,
                finish_reason=error.finish_reason,
                input_tokens=error.input_tokens,
                output_tokens=error.output_tokens,
                total_tokens=error.total_tokens,
                error=error,
            )
        )
        raise error

    monkeypatch.setattr("translate.common.lifecycle.run_translation", workflow)

    with pytest.raises(PublicRunError) as captured:
        execute_public_run(repository, prepared, settings)

    failure = captured.value.failure
    diagnostic = (
        str(captured.value)
        + (prepared.paths.workspace / "failure.json").read_text(encoding="utf-8")
        + (prepared.paths.workspace / "logs" / "run.log").read_text(encoding="utf-8")
    )
    assert failure.stage == "text-output"
    assert failure.cause_type == "LLMOutputTruncatedError"
    assert failure.failure_kind == "output-truncated"
    assert failure.finish_reason == "length"
    assert (failure.input_tokens, failure.output_tokens, failure.total_tokens) == (
        1_328,
        4_096,
        5_424,
    )
    assert "kind=output-truncated" in str(captured.value)
    assert "finish_reason=length" in str(captured.value)
    assert not any(prepared.paths.outputs.iterdir())
    for forbidden in ("prompt", "DOCUMENT", "raw=", "reasoning"):
        assert forbidden not in diagnostic


@pytest.mark.integration
def test_structure_diagnostics_reach_failure_log_and_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """STRUCTUREのallowlist診断だけをLifecycleと公開表示へ伝播する。"""

    sentinel = "SECRET prompt=DOCUMENT raw=RESPONSE"
    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings)

    def workflow(*_args: object, **_kwargs: object) -> Path:
        """
        機密本文付き解析例外をSTRUCTURE障害に包み、公開・保存境界での秘匿を検証する。
        """

        error = StructurePageError(
            2, "page/2", LLMError("text-parse", OutputParserException(sentinel))
        )
        report_task_status(
            TaskStatusEvent(
                "STRUCTURE",
                "failed",
                page=error.page,
                target_id=error.target_id,
                stage=error.stage,
                cause_type=error.cause_type,
                error=error,
            )
        )
        raise error

    monkeypatch.setattr("translate.common.lifecycle.run_translation", workflow)

    with pytest.raises(PublicRunError) as captured:
        execute_public_run(repository, prepared, settings)

    failure = captured.value.failure
    persisted = prepared.paths.workspace / "failure.json"
    log = prepared.paths.workspace / "logs" / "run.log"
    diagnostic = (
        str(captured.value)
        + persisted.read_text(encoding="utf-8")
        + log.read_text(encoding="utf-8")
    )
    assert failure.task == "STRUCTURE"
    assert failure.page == 2
    assert failure.target_id == "page/2"
    assert failure.stage == "text-parse"
    assert failure.cause_type == "OutputParserException"
    assert "stage=text-parse" in str(captured.value)
    assert "cause=OutputParserException" in str(captured.value)
    for forbidden in ("SECRET", "DOCUMENT", "RESPONSE", sentinel):
        assert forbidden not in diagnostic


def test_failure_diagnostics_reject_values_outside_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """任意のstageとcause文字列はFailure Artifactへ保存しない。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings)

    def workflow(*_args: object, **_kwargs: object) -> Path:
        """
        許可外の分類文字列と負のusageを通知し、失敗Artifactが不正値を排除するか調べる。
        """

        error = RuntimeError("raw")
        report_task_status(
            TaskStatusEvent(
                "STRUCTURE",
                "failed",
                stage="prompt=SECRET",
                cause_type="Not Valid",
                failure_kind="SECRET-kind",
                finish_reason="SECRET-finish",
                input_tokens=-1,
                output_tokens=-2,
                total_tokens=-3,
                error=error,
            )
        )
        raise error

    monkeypatch.setattr("translate.common.lifecycle.run_translation", workflow)

    with pytest.raises(RuntimeError, match="raw"):
        execute_run(repository, prepared, settings)

    failure = FailureRecord.model_validate_json(
        (prepared.paths.workspace / "failure.json").read_text(encoding="utf-8")
    )
    assert failure.stage is None
    assert failure.cause_type is None
    assert failure.failure_kind is None
    assert failure.finish_reason is None
    assert failure.input_tokens is None
    assert failure.output_tokens is None
    assert failure.total_tokens is None


@pytest.mark.parametrize("stage", ["extract", "write", "verify", "replace"])
def test_registration_stage_failure_is_public_safe_and_resumable(
    stage: RegistrationStage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """公開Lifecycleはstage診断を保存し、成果0件のfailed RunをResume可能にする。"""

    sentinel = "credential=SECRET body=DOCUMENT raw=RESPONSE job_id=JOB-123"
    settings = settings_factory(runs_dir=tmp_path / "runs")
    source = tmp_path / "reference.md"
    source.write_text("SOURCE-TEXT-SENTINEL", encoding="utf-8")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "register", {"reference": source}, settings)

    def fail_registration(*_args: object, **_kwargs: object) -> int:
        """
        指定stageの登録障害を発生させ、診断の秘匿・成果物未公開・Resume準備を検証する。
        """

        raise RegistrationError(stage, RuntimeError(sentinel))

    monkeypatch.setattr(
        "translate.common.lifecycle.register_documents", fail_registration
    )

    with pytest.raises(PublicRunError) as captured:
        execute_public_run(repository, prepared, settings)

    failure = captured.value.failure
    persisted = prepared.paths.workspace / "failure.json"
    log = prepared.paths.workspace / "logs" / "run.log"
    public_text = str(captured.value)
    diagnostic_text = (
        public_text
        + persisted.read_text(encoding="utf-8")
        + log.read_text(encoding="utf-8")
    )
    assert failure.task == "REGISTER"
    assert failure.stage == stage
    assert failure.cause_type == "RuntimeError"
    assert f"stage={stage}" in public_text
    assert "cause=RuntimeError" in public_text
    assert repository.load(prepared.record.run_id).status == "failed"
    assert not (prepared.paths.outputs / "registration.json").exists()
    for forbidden in ("SECRET", "DOCUMENT", "RESPONSE", "JOB-123", sentinel):
        assert forbidden not in diagnostic_text

    resumed = prepare_run(
        repository,
        "register",
        {"reference": source},
        settings,
        resume_id=prepared.record.run_id,
    )
    assert resumed.resumed is True
    assert resumed.record.run_id == prepared.record.run_id
