"""Atomic Artifact publishの障害境界を検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from translate.common.workspace import (
    atomic_publish_directory,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)

if TYPE_CHECKING:
    from pathlib import Path


def _publish_file(kind: str, target: Path) -> None:
    if kind == "text":
        atomic_write_text(target, "new-complete")
    elif kind == "json":
        atomic_write_json(target, {"value": "new-complete"})
    else:
        atomic_write_bytes(target, b"new-complete")


@pytest.mark.parametrize("phase", ["write", "flush", "validate", "replace"])
@pytest.mark.parametrize("kind", ["text", "json", "binary"])
def test_file_publish_preserves_old_complete_artifact_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    kind: str,
) -> None:
    """各phaseの失敗で旧完全版だけを観測できる。"""

    target = tmp_path / "artifact"
    target.write_bytes(b"old-complete")

    def fail(current: str, _path: Path) -> None:
        if current == phase:
            msg = f"injected {phase} failure"
            raise RuntimeError(msg)

    monkeypatch.setattr("translate.common.workspace._phase", fail)

    with pytest.raises(RuntimeError, match="injected"):
        _publish_file(kind, target)

    assert target.read_bytes() == b"old-complete"
    assert not list(tmp_path.glob(".artifact.*"))


@pytest.mark.parametrize("phase", ["write", "flush", "validate", "replace"])
def test_directory_publish_preserves_old_complete_artifact_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    """Directory更新失敗時に旧directoryを保持してtemporaryを除去する。"""

    target = tmp_path / "pages"
    target.mkdir()
    (target / "page.txt").write_text("old-complete", encoding="utf-8")

    def build(directory: Path) -> None:
        (directory / "page.txt").write_text("new-complete", encoding="utf-8")

    def validate(directory: Path) -> None:
        assert (directory / "page.txt").read_text(encoding="utf-8") == "new-complete"

    def fail(current: str, _path: Path) -> None:
        if current == phase:
            msg = f"injected {phase} failure"
            raise RuntimeError(msg)

    monkeypatch.setattr("translate.common.workspace._phase", fail)

    with pytest.raises(RuntimeError, match="injected"):
        atomic_publish_directory(target, build, validate)

    assert (target / "page.txt").read_text(encoding="utf-8") == "old-complete"
    assert not list(tmp_path.glob(".pages.*"))


def test_artifacts_publish_only_after_validation(tmp_path: Path) -> None:
    """成功時は各形式を検証済みの完全版へ置換する。"""

    text = tmp_path / "value.txt"
    binary = tmp_path / "value.bin"
    data = tmp_path / "value.json"
    directory = tmp_path / "pages"

    atomic_write_text(text, "日本語")
    atomic_write_bytes(binary, b"\x00\x01")
    atomic_write_json(data, {"valid": True})
    atomic_publish_directory(
        directory,
        lambda temporary: (temporary / "page.txt").write_text(
            "complete", encoding="utf-8"
        ),
    )

    assert text.read_text(encoding="utf-8") == "日本語"
    assert binary.read_bytes() == b"\x00\x01"
    assert json.loads(data.read_text(encoding="utf-8")) == {"valid": True}
    assert json.loads((directory / ".complete.json").read_text(encoding="utf-8")) == {
        "complete": True
    }
