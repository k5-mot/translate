"""UIへ依存しない進捗通知。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """一つのTask進捗。"""

    task: str
    current: int = 0
    total: int = 0
    message: str = ""
    level: str = "info"


ProgressCallback = Callable[[ProgressEvent], None]


TaskPhase = Literal["started", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class TaskStatusEvent:
    """進捗値を変えないTask実行境界。"""

    task: str
    phase: TaskPhase
    page: int | None = None
    group: str | None = None
    target_id: str | None = None
    stage: str | None = None
    cause_type: str | None = None
    error: BaseException | None = None


TaskStatusCallback = Callable[[TaskStatusEvent], None]
_TASK_STATUS_CALLBACK: ContextVar[TaskStatusCallback | None] = ContextVar(
    "translate_task_status_callback", default=None
)


@contextmanager
def bind_task_status(callback: TaskStatusCallback | None) -> Iterator[None]:
    """現在の実行contextへTask status sinkを束縛する。"""

    token = _TASK_STATUS_CALLBACK.set(callback)
    try:
        yield
    finally:
        _TASK_STATUS_CALLBACK.reset(token)


def report_task_status(event: TaskStatusEvent) -> None:
    """sinkがある場合だけTask境界を通知する。"""

    callback = _TASK_STATUS_CALLBACK.get()
    if callback is not None:
        callback(event)


def report(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    """callbackが設定されている場合だけ進捗を通知する。"""

    if callback is not None:
        callback(event)


class WorkflowProgress:
    """Task slotを一度だけ数え、Resume後も単調なeventを生成する。"""

    def __init__(
        self,
        slots: Mapping[str, int],
        callback: ProgressCallback | None,
        completed: list[str] | None = None,
    ) -> None:
        self.slots = slots
        self.callback = callback
        self.completed = set(completed or [])
        self.total = max(slots.values(), default=0)

    def emit(self, task: str, *, skipped: bool = False) -> None:
        """未通知Taskを記録し、slot数からcurrent/totalを通知する。"""

        if task in self.completed:
            return
        self.completed.add(task)
        current = len(
            {self.slots[name] for name in self.completed if name in self.slots}
        )
        report(
            self.callback,
            ProgressEvent(
                task=task,
                current=current,
                total=self.total,
                message=f"{task} {'省略' if skipped else '完了'}",
                level="skipped" if skipped else "info",
            ),
        )
