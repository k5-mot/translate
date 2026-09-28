"""Checkpointの保存境界で例外だけを安全化し、通常値と実行制御を維持する。"""

from __future__ import annotations

import sqlite3
from asyncio import CancelledError
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphBubbleUp, GraphInterrupt, NodeCancelledError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Interrupt, RetryPolicy

from translate_v1.adapters.checkpoint import CheckpointSerializer, open_checkpoint
from translate_v1.common.settings import Settings
from translate_v1.workflows import comparison_review, translation

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class DataclassError(Exception):
    """標準serializerが例外より先にdataclassとして処理するケースを再現する。"""

    body: str


class CustomReprError(Exception):
    """機密値を含む独自repr/strを呼ばないことを検査するための例外。"""

    def __repr__(self) -> str:
        """呼ばれた場合は失敗させ、例外の表示を経由した変換を検出する。"""

        pytest.fail("exception repr must not be evaluated")

    def __str__(self) -> str:
        """自由文を生成するstrにも保存処理から触れないことを検証する。"""

        message = "exception str must not be evaluated"
        raise AssertionError(message)


@pytest.mark.parametrize(
    "error",
    [
        ValueError("BODY-MARKER", "CREDENTIAL-MARKER", b"BINARY-MARKER"),
        DataclassError("BODY-MARKER"),
        CustomReprError("BODY-MARKER"),
        type("BODY_MARKER", (Exception,), {})("CREDENTIAL-MARKER"),
        KeyboardInterrupt("BODY-MARKER"),
        SystemExit("BODY-MARKER"),
    ],
    ids=["ordinary", "dataclass", "custom-repr", "unknown-type", "keyboard", "exit"],
)
def test_checkpoint_serializer_never_renders_exception(error: BaseException) -> None:
    """例外種別・chain・notesによらず固定分類だけを保存し、元例外には触れない。"""

    cause = RuntimeError("CAUSE-MARKER")
    context = RuntimeError("CONTEXT-MARKER")
    error.__cause__ = cause
    error.__context__ = context
    error.add_note("NOTE-MARKER")
    arguments = error.args
    serializer = CheckpointSerializer()

    encoded = serializer.dumps_typed(error)

    assert serializer.loads_typed(encoded) == "TaskError"
    assert JsonPlusSerializer().loads_typed(encoded) == "TaskError"
    assert b"MARKER" not in encoded[1]
    assert error.args == arguments
    assert error.__cause__ is cause
    assert error.__context__ is context
    assert error.__notes__ == ["NOTE-MARKER"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        b"artifact-reference",
        bytearray(b"artifact-reference"),
        {"path": "artifacts/document.json", "page": 2, "warnings": []},
        ("source_split", "target_split"),
        datetime(2026, 9, 25, tzinfo=UTC),
    ],
)
def test_checkpoint_serializer_keeps_standard_roundtrip(value: object) -> None:
    """通常値の保存byte列と復元を標準serializerと揃え、既存形式との互換性を保つ。"""

    standard = JsonPlusSerializer()
    protected = CheckpointSerializer()
    original = standard.dumps_typed(value)
    encoded = protected.dumps_typed(value)

    assert encoded == original
    assert standard.loads_typed(encoded) == protected.loads_typed(original)
    assert not protected.pickle_fallback


@pytest.mark.parametrize("fail", [False, True])
def test_checkpoint_connection_closes_on_all_exits(
    tmp_path: Path, *, fail: bool
) -> None:
    """正常終了・例外終了のどちらでもDB接続を閉じ、Windowsでファイルを解放する。"""

    database = tmp_path / "checkpoint.sqlite"
    error = RuntimeError("synthetic failure")
    expected = (
        pytest.raises(RuntimeError, match="synthetic failure")
        if fail
        else nullcontext()
    )
    with expected, open_checkpoint(database) as saver:
        saver.setup()
        if fail:
            raise error
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        saver.conn.execute("SELECT 1")
    destination = tmp_path / "closed.sqlite"
    database.rename(destination)
    with open_checkpoint(destination) as reopened:
        assert reopened.conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.parametrize("operation", ["translate", "review"])
@pytest.mark.parametrize(
    ("error", "expected_type", "interrupted"),
    [
        (GraphBubbleUp(), GraphBubbleUp, False),
        (GraphInterrupt([Interrupt("safe-interrupt")]), None, True),
        (CancelledError("safe-cancel"), NodeCancelledError, False),
        (KeyboardInterrupt(), KeyboardInterrupt, False),
        (SystemExit(2), SystemExit, False),
    ],
    ids=["bubble", "interrupt", "cancel", "keyboard", "exit"],
)
def test_serializer_preserves_graph_control(  # noqa: PLR0913
    operation: str,
    error: BaseException,
    expected_type: type[BaseException] | None,
    *,
    interrupted: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """両製品Graphの制御例外の伝播・中断位置を標準Saverと比較する。"""

    def fail_split(*_args: object, **_kwargs: object) -> None:
        """Graphの最初のTaskで制御例外を注入し、保存方針変更の副作用を調べる。"""

        raise error

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(translation.split, "run", fail_split)
    workflow = translation if operation == "translate" else comparison_review
    settings = Settings(templates_dir=tmp_path)
    config = {"configurable": {"thread_id": "control-test"}, "max_concurrency": 1}
    snapshots = []
    for protected in (False, True):
        database = tmp_path / f"control-{protected}.sqlite"
        manager = (
            open_checkpoint(database)
            if protected
            else SqliteSaver.from_conn_string(str(database))
        )
        with manager as saver:
            compiled = workflow.build_graph(settings).compile(checkpointer=saver)
            observed_type = None
            try:
                compiled.invoke(
                    {"source": "source.pdf", "workspace_dir": str(tmp_path)},
                    config,
                    durability="sync",
                )
            except BaseException as captured:  # noqa: BLE001
                observed_type = type(captured)
            assert observed_type is expected_type
            snapshot = compiled.get_state(config)
            interrupts = [
                item.value for task in snapshot.tasks for item in task.interrupts
            ]
            assert bool(interrupts) is interrupted
            snapshots.append((snapshot.next, interrupts))
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize("exhaust", [False, True])
def test_serializer_keeps_exception_type_retry_policy(
    tmp_path: Path, *, exhaust: bool
) -> None:
    """型に基づく有限retryの成功と枯渇を、元のOSErrorを変えず処理する。"""

    calls = 0
    error = OSError("synthetic safe failure")

    def attempt(_state: dict[str, object]) -> dict[str, object]:
        """初回だけ、または常に失敗し、型指定retryの回数と最終伝播を検査する。"""

        nonlocal calls
        calls += 1
        if calls == 1 or exhaust:
            raise error
        return {"path": "artifact.json"}

    builder = StateGraph(dict)
    builder.add_node(
        "attempt",
        attempt,
        retry_policy=RetryPolicy(
            initial_interval=0, max_attempts=2, jitter=False, retry_on=OSError
        ),
    )
    builder.add_edge(START, "attempt")
    builder.add_edge("attempt", END)
    config = {"configurable": {"thread_id": "retry-test"}, "max_concurrency": 1}
    with open_checkpoint(tmp_path / "retry.sqlite") as saver:
        compiled = builder.compile(checkpointer=saver)
        if exhaust:
            with pytest.raises(OSError, match="synthetic safe failure") as captured:
                compiled.invoke({}, config, durability="sync")
            assert captured.value is error
            assert compiled.get_state(config).tasks[0].error == "TaskError"
        else:
            assert compiled.invoke({}, config, durability="sync") == {
                "path": "artifact.json"
            }
            assert compiled.get_state(config).next == ()
    assert calls == 2
