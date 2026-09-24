"""共通Run RepositoryのUnit test。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from uuid import RFC_4122, UUID

import pytest
from uuid_utils.compat import uuid7

from translate.common import runs
from translate.common.runs import RunRepository
from translate.common.workspace import OutputLock

if TYPE_CHECKING:
    from pathlib import Path


def test_uuid7_reuses_installed_generator_and_preserves_public_type() -> None:
    """導入済み生成器を直接使い、標準UUID型と公開ID形式を維持する。"""

    assert runs.uuid7 is uuid7
    value = uuid7()

    assert isinstance(value, UUID)
    assert value.version == 7
    assert value.variant == RFC_4122
    assert str(UUID(str(value))) == str(value)


def test_uuid7_sampled_time_and_uniqueness() -> None:
    """呼出元が渡した時刻をmillisecond精度で保持し、多数生成で衝突しない。"""

    sampled_ns = time.time_ns()
    seconds, nanoseconds = divmod(sampled_ns, 1_000_000_000)
    values = [uuid7(timestamp=seconds, nanos=nanoseconds) for _ in range(2_000)]

    assert len(set(values)) == len(values)
    assert all(value.int >> 80 == sampled_ns // 1_000_000 for value in values)


def test_create_and_load_run(tmp_path: Path) -> None:
    """UUIDv7 Runと三つの標準directoryを永続化する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"example-pdf")
    repository = RunRepository(tmp_path / "runs")

    before = time.time_ns() // 1_000_000
    created = repository.create(
        "translate",
        {"source": source},
        {"backend": "llm", "model": "example"},
        "fingerprint-value",
    )
    after = time.time_ns() // 1_000_000
    paths = repository.paths(created.run_id)
    loaded = repository.load(created.run_id)

    assert UUID(created.run_id).version == 7
    assert before <= UUID(created.run_id).int >> 80 <= after
    assert paths.inputs.is_dir()
    assert paths.outputs.is_dir()
    assert paths.workspace.is_dir()
    assert loaded == created
    assert (paths.root / loaded.inputs[0].relative_path).read_bytes() == b"example-pdf"


def test_run_json_contains_only_lifecycle_metadata(tmp_path: Path) -> None:
    """作成時metadataの主要fieldを確認し、入力の本文markerが含まれないか検査する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"secret-document-body")
    repository = RunRepository(tmp_path / "runs")
    record = repository.create(
        "translate", {"source": source}, {"backend": "llm"}, "fingerprint"
    )

    raw = repository.paths(record.run_id).metadata.read_text(encoding="utf-8")
    metadata = json.loads(raw)

    assert metadata["status"] == "created"
    assert metadata["input_hashes"] == {"source": record.inputs[0].sha256}
    assert metadata["settings_snapshot"] == {"backend": "llm"}
    assert metadata["fingerprint"] == "fingerprint"
    assert metadata["last_task"] is None
    assert "secret-document-body" not in raw


def test_list_and_find_runs_exclude_corrupt_metadata(tmp_path: Path) -> None:
    """非UUID名のdirectoryを警告付きで一覧から除外し、有効候補を更新日時順に返す。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"same-input")
    repository = RunRepository(tmp_path / "runs")
    older = repository.create(
        "translate", {"source": source}, {"backend": "llm"}, "fingerprint"
    )
    newer = repository.create(
        "translate", {"source": source}, {"backend": "llm"}, "fingerprint"
    )
    corrupt = repository.root / "corrupt-run"
    corrupt.mkdir()
    (corrupt / "run.json").write_text("{invalid", encoding="utf-8")

    scanned = repository.list_runs()
    candidates = repository.find_by_input_hashes(older.input_hashes)

    assert [item.run_id for item in scanned.records] == [newer.run_id, older.run_id]
    assert [item.run_id for item in candidates.records] == [newer.run_id, older.run_id]
    assert candidates.warnings == scanned.warnings
    assert candidates.warnings == (
        "invalid run metadata excluded: corrupt-run: run_id must be a canonical UUIDv7",
    )


def test_uuid4_run_is_excluded_and_rejected_before_path_access(tmp_path: Path) -> None:
    """旧UUIDv4 metadataを一覧から除外し、公開操作用pathも作らない。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    repository = RunRepository(tmp_path / "runs")
    current = repository.create("translate", {"source": source}, {}, "fingerprint")
    legacy_id = "00000000-0000-4000-8000-000000000001"
    legacy_root = repository.root / legacy_id
    legacy_root.mkdir()
    metadata = json.loads(repository.paths(current.run_id).metadata.read_text())
    metadata["run_id"] = legacy_id
    (legacy_root / "run.json").write_text(json.dumps(metadata), encoding="utf-8")

    scanned = repository.list_runs()
    reason = "run_id must be a canonical UUIDv7"
    warning = f"invalid run metadata excluded: {legacy_id}: {reason}"

    assert [record.run_id for record in scanned.records] == [current.run_id]
    assert scanned.warnings == (warning,)
    with pytest.raises(ValueError, match="UUIDv7"):
        repository.load(legacy_id)
    with pytest.raises(ValueError, match="UUIDv7"):
        repository.delete(legacy_id)


def test_find_runs_requires_all_role_hashes(tmp_path: Path) -> None:
    """比較Runでは片側だけ同じ入力を候補として扱わない。"""

    source = tmp_path / "source.pdf"
    target = tmp_path / "target.pdf"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    repository = RunRepository(tmp_path / "runs")
    record = repository.create(
        "review",
        {"source": source, "target": target},
        {},
        "fingerprint",
    )

    assert not repository.find_by_input_hashes(
        {"source": record.input_hashes["source"]}
    ).records


def test_delete_rejects_running_locked_missing_and_outside_runs(tmp_path: Path) -> None:
    """実行中、lock中、存在しない、root外の削除を拒否する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    repository = RunRepository(tmp_path / "runs")
    record = repository.create("translate", {"source": source}, {}, "fingerprint")
    running = repository.save(record.model_copy(update={"status": "running"}))

    with pytest.raises(RuntimeError, match="active"):
        repository.delete(running.run_id)

    stopped = repository.save(running.model_copy(update={"status": "failed"}))
    with (
        OutputLock(repository.paths(stopped.run_id).workspace),
        pytest.raises(RuntimeError, match="already in use"),
    ):
        repository.delete(stopped.run_id)

    with pytest.raises(FileNotFoundError):
        repository.delete("00000000-0000-7000-8000-000000000000")
    with pytest.raises(ValueError, match="UUIDv7"):
        repository.delete("../outside")


def test_delete_rejects_linked_run_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """symlinkをRun削除で拒否する。作成権限がない環境ではlink判定を模擬する。"""

    repository = RunRepository(tmp_path / "runs")
    repository.root.mkdir()
    run_id = "00000000-0000-7000-8000-000000000001"
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = repository.root / run_id
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        linked.mkdir()
        path_type = type(linked)
        original = path_type.is_symlink
        monkeypatch.setattr(
            path_type,
            "is_symlink",
            lambda self: self == linked or original(self),
        )

    with pytest.raises(ValueError, match="linked"):
        repository.delete(run_id)
    assert outside.is_dir()


def test_delete_removes_only_run_and_preserves_export(tmp_path: Path) -> None:
    """Run全体を消しても外部export成果物を保持する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    repository = RunRepository(tmp_path / "runs")
    record = repository.create("translate", {"source": source}, {}, "fingerprint")
    paths = repository.paths(record.run_id)
    result = paths.outputs / "translated.docx"
    result.write_bytes(b"complete-result")
    exported = tmp_path / "exported.docx"
    exported.write_bytes(result.read_bytes())

    repository.delete(record.run_id)

    assert not paths.root.exists()
    assert exported.read_bytes() == b"complete-result"
