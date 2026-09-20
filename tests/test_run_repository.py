"""共通Run RepositoryのUnit test。"""

from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from translate.common.identifiers import uuid7
from translate.common.runs import RunRepository
from translate.common.workspace import OutputLock

if TYPE_CHECKING:
    from pathlib import Path


def test_uuid7_has_rfc_layout_and_injected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """固定時刻と乱数からUUIDv7のfield配置を検証する。"""

    timestamp_ms = 0x0123456789AB
    random_bits = (0xABC << 62) | 0x0123456789ABCDEF
    monkeypatch.setattr(time, "time_ns", lambda: timestamp_ms * 1_000_000)
    monkeypatch.setattr(
        secrets,
        "randbits",
        lambda bits: random_bits if bits == 74 else 0,
    )

    value = uuid7()

    assert value.version == 7
    assert value.variant == "specified in RFC 4122"
    assert value.int >> 80 == timestamp_ms
    assert (value.int >> 64) & 0xFFF == 0xABC
    assert value.int & ((1 << 62) - 1) == 0x0123456789ABCDEF


def test_uuid7_time_range_and_uniqueness() -> None:
    """生成時刻をmillisecond精度で保持し、多数生成で衝突しない。"""

    before = time.time_ns() // 1_000_000
    values = [uuid7() for _ in range(2_000)]
    after = time.time_ns() // 1_000_000

    assert len(set(values)) == len(values)
    assert all(before <= value.int >> 80 <= after for value in values)


def test_create_and_load_run(tmp_path: Path) -> None:
    """UUIDv7 Runと三つの標準directoryを永続化する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"example-pdf")
    repository = RunRepository(tmp_path / "runs")

    created = repository.create(
        "translate",
        {"source": source},
        {"backend": "llm", "model": "example"},
        "fingerprint-value",
    )
    paths = repository.paths(created.run_id)
    loaded = repository.load(created.run_id)

    assert UUID(created.run_id).version == 7
    assert paths.inputs.is_dir()
    assert paths.outputs.is_dir()
    assert paths.workspace.is_dir()
    assert loaded == created
    assert (paths.root / loaded.inputs[0].relative_path).read_bytes() == b"example-pdf"


def test_run_json_contains_only_lifecycle_metadata(tmp_path: Path) -> None:
    """run.jsonへ本文やbinaryを保存せず、必要なLifecycle項目だけを持つ。"""

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
    """破損Runを警告付きで隔離し、同一入力候補を新しい順で返す。"""

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
    """symlinkまたはjunctionをRun directoryとして辿らない。"""

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
