"""Task失敗の保存、公開表示、Resume後の解消を検証する。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

import cli
from translate.common.lifecycle import (
    FailureRecord,
    PublicRunError,
    execute_run,
    prepare_run,
)
from translate.common.progress import TaskStatusEvent, report_task_status
from translate.common.runs import RunRepository
from translate.common.workspace import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.progress import ProgressCallback
    from translate.common.settings import Backend, Settings


def _templates(root: Path) -> Path:
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
