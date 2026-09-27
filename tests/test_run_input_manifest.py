"""Run schema version 2、Directory manifestおよびstreaming copyを検証する。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from translate_v1.common import runs
from translate_v1.common.lifecycle import (
    ResumeRejectedError,
    export_run,
    fingerprint_for,
    prepare_run,
)
from translate_v1.common.runs import InputSource, RunRepository, collect_input_sources
from translate_v1.common.workspace import atomic_write_bytes, atomic_write_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from io import BufferedIOBase

    from translate_v1.common.settings import Settings


SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}


@pytest.mark.parametrize("same_path", [False, True])
def test_copy_preserves_preexisting_target(tmp_path: Path, *, same_path: bool) -> None:
    """排他的作成の衝突時は、別の既存先も元入力自身も削除・上書きしない。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic source")
    target = source if same_path else tmp_path / "existing.pdf"
    expected = b"synthetic source" if same_path else b"synthetic existing target"
    target.write_bytes(expected)

    with pytest.raises(FileExistsError):
        runs._copy_verified(source, target)  # noqa: SLF001

    assert target.is_file()
    assert target.read_bytes() == expected
    assert source.read_bytes() == b"synthetic source"


@pytest.mark.parametrize("existing_target", [False, True])
def test_source_open_failure_never_cleans_target(
    tmp_path: Path, *, existing_target: bool
) -> None:
    """元入力を開けなかった場合は、コピー先のopenもunlinkも行わない。"""

    source = tmp_path / "missing.pdf"
    target = tmp_path / "target.pdf"
    if existing_target:
        target.write_bytes(b"existing target")
    original_open = Path.open
    original_unlink = Path.unlink
    with (
        patch.object(Path, "open", autospec=True, side_effect=original_open) as opened,
        patch.object(
            Path, "unlink", autospec=True, side_effect=original_unlink
        ) as removed,
        pytest.raises(FileNotFoundError),
    ):
        runs._copy_verified(source, target)  # noqa: SLF001

    opened.assert_called_once_with(source, "rb")
    removed.assert_not_called()
    assert target.exists() is existing_target
    if existing_target:
        assert target.read_bytes() == b"existing target"


@pytest.mark.parametrize(
    "content", [b"", b"copy-and-hash" * 200_000], ids=["empty", "large"]
)
def test_copy_uses_bounded_stdlib_io_and_preserves_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    """実Fileのread/readintoを監視し、標準copy/hash・size・mtimeを検証する。"""

    source = tmp_path / "source.pdf"
    target = tmp_path / "copy.pdf"
    source.write_bytes(content)
    # Use an exact whole-second timestamp to avoid filesystem precision differences.
    os.utime(source, (1_600_000_000, 1_600_000_000))
    original_open = Path.open
    read_sizes: list[int] = []
    hash_sizes: list[int] = []

    def observe_open(path: Path, mode: str) -> BufferedIOBase:
        """実streamに観測だけを追加し、無制限readを失敗させる。"""

        stream = cast("BufferedIOBase", original_open(path, mode))
        read = stream.read
        readinto = stream.readinto

        def bounded_read(size: int = -1) -> bytes:
            """コピー元の各readが正の有限buffer指定を持つことを確認する。"""

            assert 0 < size <= 1024 * 1024
            read_sizes.append(size)
            return read(size)

        def bounded_readinto(buffer: bytearray) -> int | None:
            """hash用の再利用bufferが入力全量ではなく有限サイズであることを確認する。"""

            assert 0 < len(buffer) <= 1024 * 1024
            hash_sizes.append(len(buffer))
            return readinto(buffer)

        if path == source:
            monkeypatch.setattr(stream, "read", bounded_read)
        else:
            monkeypatch.setattr(stream, "readinto", bounded_readinto)
        return stream

    with (
        patch.object(Path, "open", autospec=True, side_effect=observe_open),
        patch.object(
            runs.shutil, "copyfileobj", wraps=runs.shutil.copyfileobj
        ) as copied,
        patch.object(runs.hashlib, "file_digest", wraps=hashlib.file_digest) as hashed,
    ):
        digest, size = runs._copy_verified(source, target)  # noqa: SLF001

    assert target.read_bytes() == content
    assert source.read_bytes() == content
    assert size == len(content)
    assert digest == hashlib.sha256(content).hexdigest()
    assert target.stat().st_mtime_ns == source.stat().st_mtime_ns
    assert read_sizes
    assert hash_sizes
    copied.assert_called_once()
    hashed.assert_called_once()


@pytest.mark.parametrize(
    "phase", ["read", "write", "flush", "fsync", "hash", "copystat"]
)
def test_failed_copy_closes_streams_before_removing_partial_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """コピー作成後の各障害で元例外を保ち、close後だけ不完全Fileを除去する。"""

    source = tmp_path / "source.pdf"
    target = tmp_path / "partial.pdf"
    source.write_bytes(b"source remains unchanged")
    original_open = Path.open
    original_unlink = Path.unlink
    streams: list[BufferedIOBase] = []
    failure = OSError("synthetic copy failure")

    def failing_open(path: Path, mode: str) -> BufferedIOBase:
        """実streamを作り、指定した読取り・書込み・flush境界だけで失敗させる。"""

        stream = cast("BufferedIOBase", original_open(path, mode))
        streams.append(stream)
        if (phase == "read" and path == source) or (
            phase in {"write", "flush"} and path == target
        ):
            monkeypatch.setattr(stream, phase, Mock(side_effect=failure))
        return stream

    def checked_unlink(path: Path, *, missing_ok: bool = False) -> None:
        """開いたFileがすべて閉じた後だけ、対象の実削除を許可する。"""

        assert path == target
        assert all(stream.closed for stream in streams)
        original_unlink(path, missing_ok=missing_ok)

    # Inject only one stage; all other filesystem and hashing operations remain real.
    if phase == "fsync":
        monkeypatch.setattr(runs.os, "fsync", Mock(side_effect=failure))
    elif phase == "hash":
        monkeypatch.setattr(runs.hashlib, "file_digest", Mock(side_effect=failure))
    elif phase == "copystat":
        monkeypatch.setattr(runs.shutil, "copystat", Mock(side_effect=failure))
    with (
        patch.object(Path, "open", autospec=True, side_effect=failing_open),
        patch.object(
            Path, "unlink", autospec=True, side_effect=checked_unlink
        ) as removed,
        pytest.raises(OSError, match="synthetic copy failure") as captured,
    ):
        runs._copy_verified(source, target)  # noqa: SLF001

    assert captured.value is failure
    removed.assert_called_once_with(target, missing_ok=True)
    assert not target.exists()
    assert source.read_bytes() == b"source remains unchanged"


def test_cleanup_refusal_does_not_replace_original_copy_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """削除拒否が起きても保存成功にはせず、元の同期失敗を呼出元へ返す。"""

    source = tmp_path / "source.pdf"
    target = tmp_path / "partial.pdf"
    source.write_bytes(b"synthetic source")
    failure = OSError("synthetic sync failure")
    monkeypatch.setattr(runs.os, "fsync", Mock(side_effect=failure))
    with (
        patch.object(
            Path, "unlink", side_effect=PermissionError("cleanup refused")
        ) as removed,
        pytest.raises(OSError, match="synthetic sync failure") as captured,
    ):
        runs._copy_verified(source, target)  # noqa: SLF001

    assert captured.value is failure
    removed.assert_called_once_with(missing_ok=True)
    assert target.is_file()
    assert source.read_bytes() == b"synthetic source"


@pytest.mark.parametrize("cleanup_refused", [False, True])
def test_prepare_copy_failure_preserves_existing_data_and_publishes_no_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    *,
    cleanup_refused: bool,
) -> None:
    """公開準備中のcopy障害は新規保存先だけを後始末し、他の正本・exportを保持する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic source")
    repository = RunRepository(tmp_path / "runs")
    existing = repository.create("translate", {"source": source}, {}, "fp")
    existing_metadata = repository.paths(existing.run_id).metadata.read_bytes()
    existing_input = (
        repository.paths(existing.run_id).root / existing.inputs[0].relative_path
    )
    existing_output = repository.paths(existing.run_id).outputs / "result.docx"
    existing_output.write_bytes(b"existing output")
    exported = tmp_path / "export.docx"
    exported.write_bytes(b"existing export")
    settings = settings_factory(
        runs_dir=repository.root, templates_dir=_templates(tmp_path / "templates")
    )
    failure = OSError("synthetic metadata copy failure")
    monkeypatch.setattr(runs.shutil, "copystat", Mock(side_effect=failure))
    if cleanup_refused:
        monkeypatch.setattr(
            Path, "unlink", Mock(side_effect=PermissionError("refused"))
        )
        # rmtree(ignore_errors=True) leaves the directory when the OS denies removal.
        monkeypatch.setattr(runs.shutil, "rmtree", Mock(return_value=None))

    with pytest.raises(OSError, match="synthetic metadata copy failure") as captured:
        prepare_run(repository, "translate", {"source": source}, settings)

    assert captured.value is failure
    roots = list(repository.root.iterdir())
    assert len(roots) == (2 if cleanup_refused else 1)
    assert repository.list_runs().records == (existing,)
    for root in roots:
        if root != repository.paths(existing.run_id).root:
            assert not (root / "run.json").exists()
            assert list((root / "inputs").rglob("source.pdf"))
    assert repository.paths(existing.run_id).metadata.read_bytes() == existing_metadata
    assert existing_input.read_bytes() == source.read_bytes() == b"synthetic source"
    assert existing_output.read_bytes() == b"existing output"
    assert exported.read_bytes() == b"existing export"


def test_new_run_root_collision_never_cleans_existing_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UUIDv7保存先の衝突時は、既存rootの入力・成果物・metadataを保持する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    repository = RunRepository(tmp_path / "runs")
    existing = repository.create("translate", {"source": source}, {}, "fp")
    root = repository.paths(existing.run_id).root
    (root / "outputs" / "result.docx").write_bytes(b"existing output")
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(runs, "uuid7", Mock(return_value=UUID(existing.run_id)))

    with pytest.raises(FileExistsError):
        repository.create("translate", {"source": source}, {}, "fp")

    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert source.read_bytes() == b"source"


def _templates(root: Path) -> Path:
    """入力manifestの互換性Testに必要な規則・用語集・Templateを固定内容で用意する。"""

    root.mkdir()
    for name in ("structure", "translation", "review"):
        (root / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (root / "glossary.csv").write_text("term,訳\n", encoding="utf-8")
    (root / "template.docx").write_bytes(b"template")
    return root


def test_version_one_run_remains_readable_and_resumable(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """schema v1の翻訳Runが再開準備・一覧・export・削除を通る。UUIDはv7を使う。"""

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
    """入力のread_bytes呼出を禁止し、copy後のsizeとmetadata内の本文marker不在を確認する。"""

    source = tmp_path / "large.pdf"
    source.write_bytes(b"streaming-sentinel" * 100_000)
    original = Path.read_bytes

    def guarded(path: Path) -> bytes:
        """元入力のread_bytes呼出だけを拒否する。他の読込みAPIやsize上限は検査しない。"""

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
