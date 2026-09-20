"""Taskと公開entry pointの経過時間出力を検証する。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from translate.document import Document, Page
from translate.tasks import check

if TYPE_CHECKING:
    import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_every_task_and_public_entry_point_uses_perf_counter() -> None:
    """計測を各run/entry point内に保ち、専用stateやFileを増やさない。"""

    task_modules = [
        path
        for path in (PROJECT_ROOT / "translate" / "tasks").glob("*.py")
        if path.name != "__init__.py"
    ]
    missing = [
        path.name
        for path in task_modules
        if "def run(" in (source := path.read_text(encoding="utf-8"))
        and ("time.perf_counter()" not in source or "[TIME]" not in source)
    ]

    assert not missing
    for entry_point in (PROJECT_ROOT / "cli.py", PROJECT_ROOT / "main.py"):
        source = entry_point.read_text(encoding="utf-8")
        assert "time.perf_counter()" in source
        assert "[TIME] TOTAL" in source
    assert not list(PROJECT_ROOT.rglob("*timing-state*"))


def test_task_timing_includes_task_page_and_group_identifiers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """計測行からTaskとpage/group対象を識別できる。"""

    check.run(Document(pages=[Page(number=2)]), None, tmp_path / "check")

    output = capsys.readouterr().out
    assert "[TIME] CHECK" in output
    assert "page=" in output
    assert "group=" in output
