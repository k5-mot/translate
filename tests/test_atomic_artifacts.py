"""Atomic Artifact publishの障害境界を検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from translate_v1.common.workspace import (
    atomic_publish_directory,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)

if TYPE_CHECKING:
    from pathlib import Path


def _publish_file(kind: str, target: Path) -> None:
    """同じ公開障害Testをtext・JSON・binaryの三つの保存入口へ適用する。"""

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
    """各公開phaseに例外を注入し、復帰後の旧完全版と一時Fileの除去を確認する。"""

    target = tmp_path / "artifact"
    target.write_bytes(b"old-complete")

    def fail(current: str, _path: Path) -> None:
        """指定したFile公開段階だけで失敗させ、旧成果物が残るか検証できるようにする。"""

        if current == phase:
            msg = f"injected {phase} failure"
            raise RuntimeError(msg)

    monkeypatch.setattr("translate_v1.common.workspace._phase", fail)

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
        """公開待ちの一時directoryに新しい完全版を作り、旧版との区別を可能にする。"""

        (directory / "page.txt").write_text("new-complete", encoding="utf-8")

    def validate(directory: Path) -> None:
        """検証callbackが新しい完全版を受け取ったことを確認する。"""

        assert (directory / "page.txt").read_text(encoding="utf-8") == "new-complete"

    def fail(current: str, _path: Path) -> None:
        """
        指定したdirectory公開段階だけで失敗させ、rollbackと一時領域の除去を検証する。
        """

        if current == phase:
            msg = f"injected {phase} failure"
            raise RuntimeError(msg)

    monkeypatch.setattr("translate_v1.common.workspace._phase", fail)

    with pytest.raises(RuntimeError, match="injected"):
        atomic_publish_directory(target, build, validate)

    assert (target / "page.txt").read_text(encoding="utf-8") == "old-complete"
    assert not list(tmp_path.glob(".pages.*"))


def test_artifacts_publish_only_after_validation(tmp_path: Path) -> None:
    """新規公開後のtext・binary・JSONの値と、directoryの完了markerを確認する。"""

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
