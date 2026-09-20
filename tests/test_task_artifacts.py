"""TaskとAdapterがatomic publish境界を経由することを検証する。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from translate.tasks import position

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "directory",
    [PROJECT_ROOT / "translate" / "tasks", PROJECT_ROOT / "translate" / "adapters"],
    ids=["tasks", "adapters"],
)
def test_modules_do_not_publish_with_direct_path_writes(directory: Path) -> None:
    """全Task/AdapterからPathの直接write APIを排除する。"""

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
        if name == "replace":
            msg = "injected replace failure"
            raise RuntimeError(msg)

    monkeypatch.setattr("translate.common.workspace._phase", fail)

    with pytest.raises(RuntimeError, match="injected"):
        position.run(source, output)

    assert (output / "document.json").read_text(encoding="utf-8") == "old-complete"
    assert not list(tmp_path.glob(".position.*"))
