"""Detached terminal Evidenceの契約とwatchdog回帰Test。"""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import portalocker
import pytest
from pydantic import ValidationError
from uuid_utils.compat import uuid7

from translate.common import terminal_evidence
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

if TYPE_CHECKING:
    from collections.abc import Iterator


def _evidence(run_id: str, operation: str = "translate") -> TerminalEvidence:
    """指定Runと操作の実行中Evidenceを作り、終了状態や安全な更新の試験の基準にする。"""

    return TerminalEvidence(
        run_id=run_id,
        operation=operation,  # type: ignore[arg-type]
        status="running",
        started_at=datetime.now(UTC),
    )


def test_evidence_io_holds_exactly_one_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Evidenceの読書きがそれぞれ単一の排他保持中に行われ、lockが入れ子にならないか検査する
    。
    """

    store = EvidenceStore(tmp_path / "terminal.json")
    evidence = _evidence(str(uuid7()))
    store.write(evidence)
    depth = 0
    acquisitions = 0
    original_read = terminal_evidence.load_json
    original_write = terminal_evidence.atomic_write_json

    @contextmanager
    def tracked_lock(path: Path) -> Iterator[None]:
        """取得回数と深さを記録して再入を拒否し、Evidence操作の排他範囲を可視化する。"""

        nonlocal depth, acquisitions
        assert path == store.path
        assert depth == 0
        depth += 1
        acquisitions += 1
        try:
            yield
        finally:
            depth -= 1

    def read(path: Path) -> object:
        """
        一つのlock保持を確認して実読込みへ委譲し、読込みが排他外へ漏れないか調べる。
        """

        assert depth == 1
        return original_read(path)

    def write(path: Path, value: object) -> None:
        """一つのlock保持を確認して実保存へ委譲し、書込みが排他外へ漏れないか調べる。"""

        assert depth == 1
        original_write(path, value)

    monkeypatch.setattr(terminal_evidence, "_evidence_lock", tracked_lock)
    monkeypatch.setattr(terminal_evidence, "load_json", read)
    monkeypatch.setattr(terminal_evidence, "atomic_write_json", write)
    assert store.read() == evidence
    assert store.write(evidence) == evidence
    assert depth == 0
    assert acquisitions == 2


@pytest.mark.parametrize("content", ['{"broken":', "[]", "{}"])
def test_evidence_corruption_is_not_success(tmp_path: Path, content: str) -> None:
    """
    破損または不正なEvidenceを有効な終了記録として受け入れず、再開許可に使わないか確認す
    る。
    """

    path = tmp_path / "terminal.json"
    path.write_text(content, encoding="utf-8")
    store = EvidenceStore(path)
    assert store.read() is None
    assert not store.allows_public_resume()


def test_heartbeat_path_operations_are_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """実heartbeat経路のパス解決・存在確認も、置換と同じlock内で実行する。"""

    path = tmp_path / "heartbeat.json"
    terminal = EvidenceStore(tmp_path / "terminal.json")
    value = _evidence(str(uuid7()))
    EvidenceStore(path).write(value)
    terminal.write(value)
    original_resolve = Path.resolve
    original_exists = Path.exists
    original_lock = terminal_evidence._evidence_lock  # noqa: SLF001
    held: set[Path] = set()
    operations: list[str] = []

    @contextmanager
    def tracked_lock(target: Path) -> Iterator[None]:
        """既存lockを取得し、再入と取得範囲を検査して必ず記録を解放する。"""

        assert target not in held
        with original_lock(target):
            held.add(target)
            try:
                yield
            finally:
                held.remove(target)

    def resolve(target: Path, *, strict: bool = False) -> Path:
        """heartbeatの正規化時に同じFileのlockがあることを確認して標準APIへ委譲する。"""

        if target == path:
            assert path in held, "heartbeat resolve outside lock"
            operations.append("resolve")
        return original_resolve(target, strict=strict)

    def exists(target: Path) -> bool:
        """heartbeatの存在確認が排他外へ漏れないことを検査する。"""

        if target == path:
            assert path in held, "heartbeat exists outside lock"
            operations.append("exists")
        return original_exists(target)

    monkeypatch.setattr(terminal_evidence, "_evidence_lock", tracked_lock)
    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "exists", exists)
    actual = terminal_evidence._read_heartbeat(path, terminal)  # noqa: SLF001
    assert actual == value
    assert operations[0] == "resolve"
    assert "exists" in operations
    assert not held


def test_evidence_resolve_failure_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """パス解決失敗を隠さず伝え、後続readerを妨げるlockを残さない。"""

    path = tmp_path / "terminal.json"
    value = _evidence(str(uuid7()))
    EvidenceStore(path).write(value)
    original_resolve = Path.resolve
    failure = PermissionError("fixture resolve failure")

    def resolve(target: Path, *, strict: bool = False) -> Path:
        """対象Fileの正規化だけを失敗させ、無関係な標準API利用は維持する。"""

        if target == path:
            raise failure
        return original_resolve(target, strict=strict)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "resolve", resolve)
        with pytest.raises(PermissionError) as raised:
            EvidenceStore(path)
        assert raised.value is failure
    assert EvidenceStore(path).read() == value


def test_evidence_normalizes_relative_paths_and_rejects_temp_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """排他範囲の拡張後も相対pathを正規化し、別表記のtemp内部Evidenceを拒否する。"""

    monkeypatch.chdir(tmp_path)
    store = EvidenceStore(Path("evidence") / ".." / "terminal.json")
    assert store.path == tmp_path / "terminal.json"
    value = _evidence(str(uuid7()))
    store.write(value)
    assert EvidenceStore(tmp_path / "terminal.json").read() == value
    with pytest.raises(ValueError, match="outside"):
        EvidenceStore(
            Path("outside") / ".." / "temp" / "terminal.json",
            temp_root=tmp_path / "temp",
        )
    assert not (tmp_path / "temp" / "terminal.json").exists()


def test_evidence_write_error_releases_lock_and_preserves_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evidence書込み失敗時に旧版を保持し、lock解放後の次の更新が成功するか検証する。"""

    store = EvidenceStore(tmp_path / "terminal.json")
    initial = _evidence(str(uuid7()))
    store.write(initial)
    failure = OSError("fixture write failure")

    def fail(_path: Path, _value: object) -> None:
        """Evidence保存を指定例外で失敗させ、旧内容の保持とlock解放を試験する。"""

        raise failure

    with monkeypatch.context() as scoped:
        scoped.setattr(terminal_evidence, "atomic_write_json", fail)
        with pytest.raises(OSError, match="fixture write failure"):
            store.write(initial.with_update(current=1))
    assert store.read() == initial
    assert store.write(initial.with_update(current=2)).current == 2


def test_evidence_lock_uses_bounded_existing_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    既存portalockerに渡す有限待機設定を捕捉し、独自の無期限lock待機を使わないか確認する
    。
    """

    original = portalocker.Lock
    options = []

    def capture(path: Path, **kwargs: object) -> portalocker.Lock:
        """実Lockへ委譲しながら要求設定を記録し、Test自体の待機は0秒に固定する。"""

        options.append(kwargs)
        return original(path, mode="a+b", timeout=0)

    monkeypatch.setattr(portalocker, "Lock", capture)
    with terminal_evidence._evidence_lock(tmp_path / "evidence.json"):  # noqa: SLF001
        pass
    assert options == [{"mode": "a+b", "timeout": 10, "check_interval": 0.01}]


def test_evidence_terminal_survives_stale_running_update(tmp_path: Path) -> None:
    """
    完了済みEvidenceを古いrunning更新が巻き戻さず、有効な終了記録を維持するか調べる。
    """

    store = EvidenceStore(tmp_path / "terminal.json")
    running = _evidence(str(uuid7()))
    completed = running.with_update(
        status="completed", finished_at=datetime.now(UTC), exit_code=0
    )
    store.write(completed)
    assert store.write(running) == completed
    assert store.read() == completed
    assert store.allows_public_resume()


def test_evidence_permission_failure_is_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Evidence読込みの権限障害を欠落や成功へ変換せず、同じ例外として伝えるか検査する。
    """

    store = EvidenceStore(tmp_path / "terminal.json")
    store.write(_evidence(str(uuid7())))
    failure = PermissionError("fixture permission failure")

    def fail(_path: Path) -> object:
        """読込み時に同じPermissionErrorを投げ、障害が握りつぶされないか確認する。"""

        raise failure

    monkeypatch.setattr(terminal_evidence, "load_json", fail)
    with pytest.raises(PermissionError) as raised:
        store.read()
    assert raised.value is failure


def test_detached_high_frequency_evidence_and_heartbeat_io(tmp_path: Path) -> None:
    """モデルを起動せず、既存の親子監視で両JSONの競合を検証する。"""

    run_id = str(uuid7())
    evidence = tmp_path / "terminal.json"
    heartbeat = tmp_path / "heartbeat.json"
    code = """
# Exercise only diagnostic I/O; do not create model or embedding clients.
import sys
from datetime import UTC, datetime
from pathlib import Path
from translate.common.terminal_evidence import EvidenceStore, TerminalEvidence
store = EvidenceStore(Path(sys.argv[2]))
heartbeat = EvidenceStore(Path(sys.argv[3]))
current = TerminalEvidence(run_id=sys.argv[1], operation='translate',
    status='running', started_at=datetime.now(UTC), total=100)
for number in range(1, 101):
    current = current.with_update(current=number, heartbeat_at=datetime.now(UTC))
    store.write(current)
    heartbeat.write(current)
store.write(current.with_update(status='completed', finished_at=datetime.now(UTC)))
"""
    result = run_detached(
        [sys.executable, "-c", code, run_id, str(evidence), str(heartbeat)],
        run_id=run_id,
        operation="translate",
        evidence_path=evidence,
        heartbeat_path=heartbeat,
        temp_root=tmp_path / "temp",
        timeout_seconds=10,
        poll_seconds=0.001,
    )
    assert result.exit_code == 0
    assert result.evidence.status == "completed"
    assert result.evidence.current == result.evidence.total == 100
    assert EvidenceStore(evidence).allows_public_resume()
    assert EvidenceStore(heartbeat).read().current == 100


def test_terminal_evidence_forbids_arbitrary_fields_and_unsafe_names() -> None:
    """任意本文欄・不正Task名・終端から実行中への遷移をEvidenceが拒否するか調べる。"""

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
    """
    削除対象内へのEvidence保存と終了記録の欠落を拒否し、有効な完了証拠だけを許可するか調
    べる。
    """

    run_id = str(uuid7())
    temp_root = tmp_path / "temp"
    with pytest.raises(ValueError, match="outside"):
        EvidenceStore(temp_root / "evidence.json", temp_root=temp_root)
    evidence = _evidence(run_id)
    missing = EvidenceStore(tmp_path / "missing.json")
    assert not missing.contains_valid_terminal()
    assert not missing.allows_public_resume()
    assert not EvidenceStore(tmp_path / "missing.json").allows_public_resume()
    completed = evidence.with_update(
        status="completed", exit_code=0, finished_at=datetime.now(UTC)
    )
    store = EvidenceStore(tmp_path / "terminal.json")
    store.write(completed)
    assert store.allows_public_resume()
    assert evidence.status == "running"


def test_progress_and_failure_are_reduced_to_safe_values() -> None:
    """
    進捗と失敗情報から許可された分類・件数・usageをEvidenceへ移せることを確認する。
    """

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
        """入れ子counter内で失敗させ、外側のcounterへcontextが正しく戻るか検証する。"""

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
    """
    phaseとstageの許可集合を検証し、任意文字列を診断Evidenceへ取り込まないか確認する。
    """

    assert terminal_evidence._safe_phase(phase) == expected_phase  # noqa: SLF001
    assert terminal_evidence._safe_stage(stage) == expected_stage  # noqa: SLF001


def test_evidence_and_counts_contain_no_sensitive_or_external_values(
    tmp_path: Path,
) -> None:
    """無害な進捗fixtureの既知文字列不在とFile件数を確認する。機密値は入力しない。"""

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
    """印付き一時領域の削除と外部Evidence保持を確認する。印のRun ID照合は試さない。"""

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
    """
    標準出力を使わず終了Evidenceを書くchildを実行し、watchdogが完了と終了codeを回収する
    か検証する。
    """

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
    """
    終了しないchildを期限で止め、timeout分類とprocess終了を記録することを確認する。
    """

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
    """childが終了しても有効な終了Evidenceがなければ成功へ昇格しないことを検証する。"""

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
    """公開診断runnerがchild起動用要求を渡し、終了後に要求Fileを除去するか検査する。"""

    run_id = str(uuid7())
    captured: dict[str, object] = {}

    def fake_watchdog(command: list[str], **kwargs: object) -> DetachedResult:
        """
        childを起動せずcommandと引数を捕捉し、異常終了結果を返してrunnerの後片付けを調べ
        る。
        """

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
    """
    実childから既存convert処理を実行し、完了Evidence・Run状態・DOCX成果物が揃うか検証す
    る。
    """

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
