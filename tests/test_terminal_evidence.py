"""Detached terminal Evidenceの契約とwatchdog回帰Test。"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from translate.common import terminal_evidence
from translate.common.identifiers import uuid7
from translate.common.lifecycle import FailureRecord
from translate.common.runs import RunRepository
from translate.common.settings import Settings
from translate.common.terminal_evidence import (
    DetachedResult,
    EvidenceStore,
    TerminalEvidence,
    cleanup_detached_temp,
    evidence_from_failure,
    evidence_from_progress,
    run_detached,
    run_public_run_detached,
    workspace_counts,
)


def _evidence(run_id: str, operation: str = "translate") -> TerminalEvidence:
    return TerminalEvidence(
        run_id=run_id,
        operation=operation,  # type: ignore[arg-type]
        status="running",
        started_at=datetime.now(UTC),
    )


def test_terminal_evidence_forbids_arbitrary_fields_and_unsafe_names() -> None:
    run_id = str(uuid7())
    with pytest.raises(ValidationError):
        TerminalEvidence(
            **_evidence(run_id).model_dump(),
            prompt="document body",
        )
    with pytest.raises(ValidationError):
        _evidence(run_id).with_update(task="secret value")
    completed = _evidence(run_id).with_update(status="completed")
    with pytest.raises(ValueError, match="cannot transition"):
        completed.with_update(status="running")


def test_evidence_store_rejects_temp_root_and_invalid_terminal(tmp_path: Path) -> None:
    run_id = str(uuid7())
    temp_root = Path("temp")
    with pytest.raises(ValueError, match="outside"):
        EvidenceStore(temp_root / "evidence.json", temp_root=temp_root)
    evidence = _evidence(run_id)
    missing = EvidenceStore(Path("missing.json"))
    assert not missing.contains_valid_terminal()
    assert not missing.allows_public_resume()
    assert not EvidenceStore(Path("missing.json")).allows_public_resume()
    completed = evidence.with_update(
        status="completed", exit_code=0, finished_at=datetime.now(UTC)
    )
    store = EvidenceStore(tmp_path / "terminal.json")
    store.write(completed)
    assert store.allows_public_resume()
    assert evidence.status == "running"


def test_progress_and_failure_are_reduced_to_safe_values() -> None:
    run_id = str(uuid7())
    progress = evidence_from_progress(
        SimpleNamespace(task="STRUCTURE", current=3, total=351),
        run_id=run_id,
        operation="translate",
        started_at=datetime.now(UTC),
    )
    assert progress.phase == "STRUCTURE"
    assert progress.current == 3
    failure = FailureRecord(
        run_id=run_id,
        task="TRANSLATE",
        stage="text-output",
        cause_type="TimeoutError",
        error_type="ProviderError",
        failure_kind="output-truncated",
        finish_reason="length",
        input_tokens=20,
        output_tokens=30,
        total_tokens=50,
        reason="ProviderError",
        failed_at=datetime.now(UTC),
    )
    failed = evidence_from_failure(
        failure, started_at=progress.started_at, previous=progress
    )
    assert failed.status == "failed"
    assert failed.stage == "text-output"
    assert failed.total_tokens == 50
    assert failed.cause_type == "TimeoutError"


def test_external_call_counter_restores_nested_and_failed_contexts() -> None:
    """入れ子contextと例外終了の後に外側/未束縛のcounterへ戻る。"""

    inner_values: list[dict[str, int]] = []
    failure = RuntimeError("fixture failure")

    def fail_in_context() -> None:
        with terminal_evidence.bind_call_counts() as inner:
            terminal_evidence.count_external_call("embedding")
            inner_values.append(dict(inner))
            raise failure

    with terminal_evidence.bind_call_counts() as outer:
        terminal_evidence.count_external_call("llm")
        with pytest.raises(RuntimeError, match="fixture failure"):
            fail_in_context()
        terminal_evidence.count_external_call("qdrant")
    terminal_evidence.count_external_call("llm")
    assert dict(outer) == {"llm_calls": 1, "embedding_calls": 0, "qdrant_calls": 1}
    assert inner_values == [{"llm_calls": 0, "embedding_calls": 1, "qdrant_calls": 0}]


@pytest.mark.parametrize(
    ("phase", "stage", "expected_phase", "expected_stage"),
    [
        ("structure", "text-invoke", "STRUCTURE", "text-invoke"),
        ("REVIEW", "text-output", "REVIEW", "text-output"),
        ("private value", "private value", None, None),
        (None, None, None, None),
    ],
)
def test_evidence_literal_narrowing_keeps_allowlist(
    phase: str | None,
    stage: str | None,
    expected_phase: str | None,
    expected_stage: str | None,
) -> None:
    assert terminal_evidence._safe_phase(phase) == expected_phase  # noqa: SLF001
    assert terminal_evidence._safe_stage(stage) == expected_stage  # noqa: SLF001


def test_evidence_and_counts_contain_no_sensitive_or_external_values(
    tmp_path: Path,
) -> None:
    run_id = str(uuid7())
    root = tmp_path / "run"
    (root / ".workspace").mkdir(parents=True)
    (root / "outputs").mkdir()
    (root / ".workspace" / "checkpoint.sqlite").write_bytes(b"sqlite")
    (root / "outputs" / "result.docx").write_bytes(b"artifact")
    value = evidence_from_progress(
        SimpleNamespace(task="STRUCTURE", current=1, total=2),
        run_id=run_id,
        operation="translate",
        started_at=datetime.now(UTC),
    )
    serialized = json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
    for forbidden in (
        "SECRET",
        "https://user:password@example.test",
        "prompt body",
        "raw response",
        "traceback",
    ):
        assert forbidden not in serialized
    assert workspace_counts(root) == {"checkpoint_count": 1, "artifact_count": 1}


def test_cleanup_detached_temp_preserves_external_evidence(tmp_path: Path) -> None:
    root = tmp_path / "temp"
    root.mkdir()
    (root / ".detached-temp-root").write_text(
        '{"version": 1, "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV", '
        '"purpose": "detached-run"}\n',
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    assert cleanup_detached_temp(root)
    assert not root.exists()
    assert evidence.exists()


def test_detached_watchdog_collects_completion_without_stdout(tmp_path: Path) -> None:
    run_id = str(uuid7())
    temp_root = tmp_path / "temp"
    evidence_path = tmp_path / "terminal.json"
    code = (
        "from datetime import UTC, datetime; "
        "from pathlib import Path; "
        "import sys; "
        "from translate.common.terminal_evidence import "
        "EvidenceStore, TerminalEvidence; "
        "e=TerminalEvidence(run_id=sys.argv[1], operation='translate', "
        "status='completed', "
        "started_at=datetime.now(UTC), finished_at=datetime.now(UTC)); "
        "EvidenceStore(Path(sys.argv[2]), temp_root=Path(sys.argv[3])).write(e)"
    )
    result = run_detached(
        [sys.executable, "-c", code, run_id, str(evidence_path), str(temp_root)],
        run_id=run_id,
        operation="translate",
        evidence_path=evidence_path,
        temp_root=temp_root,
        timeout_seconds=10,
        poll_seconds=0.01,
    )
    assert result.evidence.status == "completed"
    assert result.exit_code == 0
    assert evidence_path.exists()


def test_detached_watchdog_times_out_without_restart(tmp_path: Path) -> None:
    run_id = str(uuid7())
    temp_root = tmp_path / "temp"
    evidence_path = tmp_path / "terminal.json"
    result = run_detached(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        run_id=run_id,
        operation="translate",
        evidence_path=evidence_path,
        temp_root=temp_root,
        timeout_seconds=0.1,
        poll_seconds=0.01,
    )
    assert result.evidence.status == "timeout"
    assert result.evidence.cause_type == "watchdog-timeout"
    assert result.exit_code is not None
    time.sleep(0.05)


@pytest.mark.parametrize(
    ("code", "expected"),
    [("raise SystemExit(3)", "failed"), ("pass", "unexpected-exit")],
)
def test_detached_watchdog_never_promotes_missing_terminal(
    tmp_path: Path, code: str, expected: str
) -> None:
    run_id = str(uuid7())
    result = run_detached(
        [sys.executable, "-c", code],
        run_id=run_id,
        operation="translate",
        evidence_path=tmp_path / "terminal.json",
        temp_root=tmp_path / "temp",
        timeout_seconds=10,
        poll_seconds=0.01,
    )
    assert result.evidence.status == expected


def test_public_detached_runner_uses_existing_lifecycle_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = str(uuid7())
    captured: dict[str, object] = {}

    def fake_watchdog(command: list[str], **kwargs: object) -> DetachedResult:
        captured["command"] = command
        captured.update(kwargs)
        return DetachedResult(
            evidence=_evidence(run_id).with_update(status="unexpected-exit"),
            exit_code=2,
        )

    monkeypatch.setattr(
        "translate.common.terminal_evidence.run_detached", fake_watchdog
    )
    temp_root = tmp_path / "temp"
    result = run_public_run_detached(
        tmp_path / "runs",
        run_id,
        "translate",
        "llm",
        evidence_path=tmp_path / "evidence.json",
        temp_root=temp_root,
    )
    assert result.exit_code == 2
    command = captured["command"]
    assert isinstance(command, list)
    assert "--child" in command
    request = Path(command[-1])
    assert not request.exists()
    assert captured["run_id"] == run_id
    assert captured["operation"] == "translate"


def test_public_detached_runner_executes_existing_convert_lifecycle(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# detached\n\ncontent\n", encoding="utf-8")
    repository = RunRepository(tmp_path / "runs")
    settings = Settings(templates_dir=Path("translate/templates"))
    record = repository.create("convert", {"source": source}, {}, "test")
    result = run_public_run_detached(
        repository.root,
        record.run_id,
        "convert",
        "llm",
        evidence_path=tmp_path / "evidence.json",
        temp_root=tmp_path / "temp",
        timeout_seconds=60,
        poll_seconds=0.02,
    )
    assert result.evidence.status == "completed", result.evidence
    assert repository.load(record.run_id).status == "completed"
    assert (repository.paths(record.run_id).outputs / "source.docx").exists()
    assert settings.templates_dir.exists()
