"""排他拒否が実行所有者の保存情報と診断を壊さないことを検証する。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from translate_v1.common import lifecycle
from translate_v1.common.lifecycle import FailureRecord, PreparedRun, PublicRunError
from translate_v1.common.progress import ProgressEvent, TaskStatusEvent, report_task_status
from translate_v1.common.runs import RunRepository
from translate_v1.common.workspace import OutputInUseError, OutputLock, atomic_write_json

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate_v1.common.progress import ProgressCallback
    from translate_v1.common.runs import Operation, RunRecord
    from translate_v1.common.settings import Backend, Settings


@pytest.fixture(params=["translate", "review", "register", "convert"])
def execution(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    settings_factory: Callable[..., Settings],
) -> tuple[RunRepository, PreparedRun, Settings]:
    """外部処理の手前にある共通実行境界だけを試す実保存fixtureを作る。"""

    settings = settings_factory(runs_dir=tmp_path / "runs")
    repository = RunRepository(settings.runs_dir)
    source = tmp_path / "source.md"
    source.write_text("fixture", encoding="utf-8")
    operation: Operation = request.param
    record = repository.create(operation, {"source": source}, {}, "fixture")
    paths = repository.paths(record.run_id)
    prepared = PreparedRun(record, paths, {"source": source}, resumed=False)
    return repository, prepared, settings


def _saved_files(root: Path) -> dict[str, bytes]:
    """所有者のdataをbyte比較する。Windowsで読取り不能なlockfileは除く。"""

    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path != root / ".workspace/run.lock"
    }


@pytest.mark.parametrize("previous_failure", [False, True])
def test_rejected_execution_preserves_owner_files_and_does_not_start_operation(
    execution: tuple[RunRepository, PreparedRun, Settings],
    monkeypatch: pytest.MonkeyPatch,
    *,
    previous_failure: bool,
) -> None:
    """全操作で拒否側の保存・log設定・外部処理を0にし旧failureを誤採用しない。"""

    repository, prepared, settings = execution
    repository.save(prepared.record.model_copy(update={"status": "running"}))
    workspace = prepared.paths.workspace
    log = workspace / "logs/run.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"owner log")
    (workspace / "checkpoints.sqlite").write_bytes(b"owner checkpoint")
    (prepared.paths.outputs / "output.docx").write_bytes(b"owner output")
    if previous_failure:
        atomic_write_json(
            workspace / "failure.json",
            FailureRecord(
                run_id=prepared.record.run_id,
                task="PREVIOUS",
                error_type="PreviousFailure",
                reason="PreviousFailure",
                failed_at=datetime.now(UTC),
            ).model_dump(mode="json"),
        )
    calls: list[str] = []
    # 拒否側はlog設定にも製品処理にも到達してはならない。
    monkeypatch.setattr(
        lifecycle, "configure_logging", lambda *_a, **_k: calls.append("log")
    )
    monkeypatch.setattr(
        lifecycle, "_execute_operation", lambda *_a, **_k: calls.append("operation")
    )
    with OutputLock(workspace):
        before = _saved_files(prepared.paths.root)
        with pytest.raises(PublicRunError) as captured:
            lifecycle.execute_public_run(repository, prepared, settings)
        assert _saved_files(prepared.paths.root) == before
        assert calls == []
        assert captured.value.failure.error_type == "OutputInUseError"
        assert captured.value.failure.task == prepared.record.operation.upper()
        assert "PREVIOUS" not in str(captured.value)
        assert str(workspace) not in str(captured.value)
    assert repository.load(prepared.record.run_id).status == "running"


def _assert_owned(workspace: Path) -> None:
    """実portalockerの再取得拒否により排他保持を確認する。"""

    with pytest.raises(OutputInUseError), OutputLock(workspace):
        pytest.fail("owner lock must remain held")


@pytest.mark.parametrize("outcome", ["completed", "failed"])
# 同じ所有者実行内の5副作用境界を観測するためspyを同じTest scopeへ置く。
def test_owner_holds_lock_through_terminal_save_and_cleanup(  # noqa: C901, PLR0915
    outcome: str,
    execution: tuple[RunRepository, PreparedRun, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """最新metadata・Task通知・終端保存・log解除の全境界で排他を保証する。"""

    repository, prepared, settings = execution
    repository.save(prepared.record.model_copy(update={"warnings": ["newer warning"]}))
    workspace = prepared.paths.workspace
    failure_path = workspace / "failure.json"
    original_save, original_unlink = repository.save, Path.unlink
    phases: list[str] = []

    def save(record: RunRecord) -> RunRecord:
        """状態書込みの直前にも別呼出を拒否し、最新warningを維持する。"""

        _assert_owned(workspace)
        phases.append(record.status)
        if record.status in {"completed", "failed"}:
            with pytest.raises(PublicRunError) as rejected:
                lifecycle.execute_public_run(repository, prepared, settings)
            assert rejected.value.failure.error_type == "OutputInUseError"
        return original_save(record)

    def write_failure(path: Path, value: object) -> None:
        """障害Artifact公開時の実lockを確認して既存writerへ委譲する。"""

        _assert_owned(workspace)
        phases.append("failure")
        atomic_write_json(path, value)

    def unlink(path: Path, *, missing_ok: bool = False) -> None:
        """成功時の旧失敗記録削除も排他内であることを確認する。"""

        if path == failure_path:
            _assert_owned(workspace)
            phases.append("clear-failure")
        original_unlink(path, missing_ok=missing_ok)

    def logging(*_args: object) -> None:
        """log開始と解放の両方で排他を保持していることを確認する。"""

        _assert_owned(workspace)
        phases.append("logging")

    def operation(
        _prepared: PreparedRun,
        _settings: Settings,
        _backend: Backend,
        callback: ProgressCallback,
    ) -> tuple[Path, ...]:
        """外部serviceなしでTask通知と成功または所有者自身の失敗を再現する。"""

        _assert_owned(workspace)
        report_task_status(TaskStatusEvent("OWNER", "started"))
        callback(ProgressEvent("OWNER", current=1, total=1))
        if outcome == "failed":
            raise TimeoutError
        return ()

    monkeypatch.setattr(repository, "save", save)
    monkeypatch.setattr(lifecycle, "atomic_write_json", write_failure)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(lifecycle, "configure_logging", logging)
    monkeypatch.setattr(lifecycle, "_execute_operation", operation)
    if outcome == "failed":
        with pytest.raises(PublicRunError) as captured:
            lifecycle.execute_public_run(repository, prepared, settings)
        assert captured.value.failure.error_type == "TimeoutError"
        assert phases[-3:] == ["failure", "failed", "logging"]
    else:
        completed, _outputs = lifecycle.execute_public_run(
            repository, prepared, settings
        )
        assert completed.status == "completed"
        assert phases[-3:] == ["clear-failure", "completed", "logging"]
    assert phases.count("logging") == 2
    record = repository.load(prepared.record.run_id)
    assert record.status == outcome
    assert "newer warning" in record.warnings
    assert record.last_task == "OWNER"
    with OutputLock(workspace):
        assert failure_path.exists() == (outcome == "failed")


def test_resume_is_available_after_owner_releases_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """拒否後に実prepare_runの互換性判定を通り、同じIDでResumeできる。"""

    settings = settings_factory(runs_dir=tmp_path / "runs")
    settings.templates_dir.mkdir()
    (settings.templates_dir / "template.docx").write_bytes(b"template hash fixture")
    source = tmp_path / "source.md"
    source.write_text("fixture", encoding="utf-8")
    repository = RunRepository(settings.runs_dir)
    prepared = lifecycle.prepare_run(
        repository, "convert", {"source": source}, settings
    )
    with OutputLock(prepared.paths.workspace), pytest.raises(PublicRunError):
        lifecycle.execute_public_run(repository, prepared, settings)
    resumed = lifecycle.prepare_run(
        repository,
        "convert",
        {"source": source},
        settings,
        resume_id=prepared.record.run_id,
    )
    # 変換器の起動だけを置換し、公開境界とmetadata保存は実処理を使う。
    monkeypatch.setattr(lifecycle, "_execute_operation", lambda *_a, **_k: ())
    completed, _outputs = lifecycle.execute_public_run(repository, resumed, settings)
    assert resumed.resumed
    assert completed.run_id == prepared.record.run_id
    assert completed.status == "completed"
    assert not (prepared.paths.workspace / "failure.json").exists()
