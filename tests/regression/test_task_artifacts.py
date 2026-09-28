"""直接writeの表記と、POSITION公開失敗時の旧成果物保持を検査する。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from translate_v1.tasks import position

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "directory",
    [
        PROJECT_ROOT / "translate_v1" / "tasks",
        PROJECT_ROOT / "translate_v1" / "adapters",
    ],
    ids=["tasks", "adapters"],
)
def test_modules_do_not_publish_with_direct_path_writes(directory: Path) -> None:
    """Task/Adapter直下のPythonにwrite_text/write_bytesの呼出表記がないか検査する。"""

    violations: list[str] = []
    for module in directory.glob("*.py"):
        source = module.read_text(encoding="utf-8")
        if ".write_text(" in source or ".write_bytes(" in source:
            violations.append(module.name)

    assert not violations


def test_task_directory_is_not_replaced_before_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task途中のpublish失敗で旧完全版directoryを保持する。"""

    source = tmp_path / "source.json"
    source.write_text(
        json.dumps({"body": {"self_ref": "#/body", "children": []}}),
        encoding="utf-8",
    )
    output = tmp_path / "position"
    output.mkdir()
    (output / "document.json").write_text("old-complete", encoding="utf-8")

    def fail(name: str, _path: Path) -> None:
        """成果物の置換段階だけを失敗させ、Taskが旧完全版を維持するか検証する。"""

        if name == "replace":
            msg = "injected replace failure"
            raise RuntimeError(msg)

    monkeypatch.setattr("translate_v1.common.workspace._phase", fail)

    with pytest.raises(RuntimeError, match="injected"):
        position.run(source, output)

    assert (output / "document.json").read_text(encoding="utf-8") == "old-complete"
    assert not list(tmp_path.glob(".position.*"))
