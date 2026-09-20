"""Run schema version 2、Directory manifestおよびstreaming copyを検証する。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from translate.common.lifecycle import (
    ResumeRejectedError,
    export_run,
    fingerprint_for,
    prepare_run,
)
from translate.common.runs import InputSource, RunRepository, collect_input_sources
from translate.common.workspace import atomic_write_bytes, atomic_write_json

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.settings import Settings


SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}


def _templates(root: Path) -> Path:
    root.mkdir()
    for name in ("structure", "translation", "review"):
        (root / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (root / "glossary.csv").write_text("term,訳\n", encoding="utf-8")
    (root / "template.docx").write_bytes(b"template")
    return root


def test_version_one_run_remains_readable_and_resumable(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """旧Runは登録以外のResume、一覧、export、削除に利用できる。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings)
    metadata = repository.paths(prepared.record.run_id).metadata
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["schema_version"] = 1
    for item in value["inputs"]:
        item.pop("logical_path", None)
        item.pop("source_key", None)
    atomic_write_json(metadata, value)
    output = repository.paths(prepared.record.run_id).outputs / "result.docx"
    atomic_write_bytes(output, b"complete")
    legacy = repository.save(
        repository.load(prepared.record.run_id).model_copy(
            update={"status": "completed"}
        )
    )

    assert legacy.schema_version == 1
    assert repository.list_runs().records[0].run_id == legacy.run_id
    assert prepare_run(
        repository,
        "translate",
        {"source": source},
        settings,
        resume_id=legacy.run_id,
    ).resumed
    exported = export_run(repository, legacy.run_id, tmp_path / "export")
    assert exported[0].read_bytes() == b"complete"
    repository.delete(legacy.run_id)
    assert not repository.paths(legacy.run_id).root.exists()


def test_directory_manifest_is_canonical_and_rejects_empty_or_duplicate(
    tmp_path: Path,
) -> None:
    """対応Fileだけを論理path順で収集し、曖昧なmanifestを拒否する。"""

    source = tmp_path / "references"
    (source / "nested").mkdir(parents=True)
    (source / "z.txt").write_text("z", encoding="utf-8")
    (source / "nested" / "a.md").write_text("a", encoding="utf-8")
    (source / "ignored.bin").write_bytes(b"ignored")

    values = collect_input_sources(
        {"reference": source},
        supported_extensions=SUPPORTED,
        source_namespace="manual-source",
    )

    assert [item.logical_path for item in values] == [
        "references/nested/a.md",
        "references/z.txt",
    ]
    assert all(item.source_key for item in values)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no supported input"):
        collect_input_sources({"reference": empty}, supported_extensions=SUPPORTED)

    first = tmp_path / "one" / "same.md"
    second = tmp_path / "two" / "same.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate logical"):
        collect_input_sources(
            {"one": first, "two": second}, supported_extensions=SUPPORTED
        )


def test_linked_input_and_unsafe_logical_path_leave_no_partial_run(
    tmp_path: Path,
) -> None:
    """linkとtraversalをRun root作成前またはcleanup付きで拒否する。"""

    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    linked = tmp_path / "linked.md"
    try:
        linked.symlink_to(source)
    except OSError:
        pytest.skip("この環境ではsymlinkを作成できない")
    with pytest.raises(ValueError, match="linked input"):
        collect_input_sources({"reference": linked}, supported_extensions=SUPPORTED)

    repository = RunRepository(tmp_path / "runs")
    with pytest.raises(ValueError, match="unsafe logical"):
        repository.create(
            "register",
            [InputSource(role="reference", path=source, logical_path="../escape.md")],
            {"inputs": {}},
            "fingerprint",
        )
    assert not repository.list_runs().records
    assert not list(repository.root.glob("*"))


def test_copy_hashes_in_chunks_without_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """大きい入力を全体読込みせずcopyし、metadataへ本文を保存しない。"""

    source = tmp_path / "large.pdf"
    source.write_bytes(b"streaming-sentinel" * 100_000)
    original = Path.read_bytes

    def guarded(path: Path) -> bytes:
        if path == source:
            message = "source.read_bytes must not be used"
            raise AssertionError(message)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    repository = RunRepository(tmp_path / "runs")
    record = repository.create(
        "translate", {"source": source}, {"inputs": {"source": "hash"}}, "fp"
    )
    copied = repository.paths(record.run_id).root / record.inputs[0].relative_path
    raw = repository.paths(record.run_id).metadata.read_text(encoding="utf-8")

    assert copied.stat().st_size == source.stat().st_size
    assert "streaming-sentinel" not in raw


def test_registration_fingerprint_tracks_manifest_but_not_qdrant(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """logical source identityは互換性へ含め、Qdrant状態は除外する。"""

    source = tmp_path / "reference.md"
    source.write_text("same content", encoding="utf-8")
    settings = settings_factory(
        templates_dir=_templates(tmp_path / "templates"),
        qdrant_collection="first",
    )

    first = fingerprint_for(
        "register", {"reference": source}, settings, source_id="source-a"
    )
    identity_changed = fingerprint_for(
        "register", {"reference": source}, settings, source_id="source-b"
    )
    qdrant_changed = fingerprint_for(
        "register",
        {"reference": source},
        settings.model_copy(update={"qdrant_collection": "second"}),
        source_id="source-a",
    )

    assert first.value != identity_changed.value
    assert first == qdrant_changed
    assert first.snapshot["input_manifest"][0]["logical_path"] == "reference.md"


def test_version_one_registration_resume_is_rejected_but_management_works(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """source keyのない旧登録Runは再開だけ拒否して管理操作を維持する。"""

    source = tmp_path / "reference.md"
    source.write_text("reference", encoding="utf-8")
    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(
        repository,
        "register",
        {"reference": source},
        settings,
        source_id="reference-library",
    )
    metadata = repository.paths(prepared.record.run_id).metadata
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["schema_version"] = 1
    for item in value["inputs"]:
        item.pop("logical_path", None)
        item.pop("source_key", None)
    atomic_write_json(metadata, value)

    with pytest.raises(ResumeRejectedError, match="stable source keys"):
        prepare_run(
            repository,
            "register",
            {"reference": source},
            settings,
            resume_id=prepared.record.run_id,
            source_id="reference-library",
        )

    output = repository.paths(prepared.record.run_id).outputs / "registration.json"
    atomic_write_bytes(output, b"{}")
    legacy = repository.save(
        repository.load(prepared.record.run_id).model_copy(
            update={"status": "completed"}
        )
    )
    assert repository.list_runs().records[0].run_id == legacy.run_id
    assert export_run(repository, legacy.run_id, tmp_path / "export")
    repository.delete(legacy.run_id)
    assert not repository.paths(legacy.run_id).root.exists()
