"""参照文書登録のrevision置換と部分失敗を検証する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import pytest
from typer.testing import CliRunner

import cli
from translate.adapters import qdrant
from translate.common.runs import RunRepository

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from langchain_core.documents import Document

    from translate.common.settings import Settings


@dataclass
class _Record:
    id: str


class _FakeClient:
    """QdrantのPoint IDとrevision削除だけを再現する。"""

    points: ClassVar[dict[str, Document]] = {}
    delete_calls: ClassVar[int] = 0
    retrieve_failures: ClassVar[int] = 0
    delete_failures: ClassVar[int] = 0
    write_failures: ClassVar[int] = 0

    def __init__(self, **_kwargs: object) -> None:
        pass

    @classmethod
    def reset(cls) -> None:
        cls.points = {}
        cls.delete_calls = 0
        cls.retrieve_failures = 0
        cls.delete_failures = 0
        cls.write_failures = 0

    def collection_exists(self, _collection: str) -> bool:
        return bool(self.points)

    def retrieve(self, **kwargs: object) -> list[_Record]:
        if self.retrieve_failures:
            self.retrieve_failures -= 1
            return []
        return [
            _Record(id=point_id)
            for point_id in kwargs["ids"]  # type: ignore[union-attr]
            if point_id in self.points
        ]

    def delete(self, **kwargs: object) -> None:
        type(self).delete_calls += 1
        if self.delete_failures:
            type(self).delete_failures -= 1
            message = "temporary delete failure"
            raise OSError(message)
        selector = kwargs["points_selector"]
        source_key = selector.must[0].match.value
        current_hash = selector.must_not[0].match.value
        type(self).points = {
            point_id: document
            for point_id, document in self.points.items()
            if not (
                document.metadata["source_key"] == source_key
                and document.metadata["source_hash"] != current_hash
            )
        }


class _FakeStore:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def add_documents(self, documents: list[Document], *, ids: list[str]) -> list[str]:
        if _FakeClient.write_failures:
            _FakeClient.write_failures -= 1
            message = "temporary write failure"
            raise OSError(message)
        _FakeClient.points.update(dict(zip(ids, documents, strict=True)))
        return ids

    @classmethod
    def from_documents(
        cls, documents: list[Document], _embedding: object, **kwargs: object
    ) -> _FakeStore:
        if _FakeClient.write_failures:
            _FakeClient.write_failures -= 1
            message = "temporary write failure"
            raise OSError(message)
        ids = kwargs["ids"]
        _FakeClient.points.update(dict(zip(ids, documents, strict=True)))
        return cls()


@pytest.fixture(autouse=True)
def _qdrant_double(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.reset()
    monkeypatch.setattr(qdrant, "QdrantClient", _FakeClient)
    monkeypatch.setattr(qdrant, "QdrantVectorStore", _FakeStore)
    monkeypatch.setattr(qdrant, "_embeddings", lambda _settings: object())
    monkeypatch.setattr(qdrant.time, "sleep", lambda _value: None)


def test_reregistration_replaces_revision_without_duplicate_chunks(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """再登録は同一IDをupsertし、新revision確認後に旧Pointを除去する。"""

    source = tmp_path / "reference.md"
    source.write_text("first revision", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_base_seconds=0,
    )

    assert qdrant.register_documents(settings, [source]) == 1
    first_ids = set(_FakeClient.points)
    assert qdrant.register_documents(settings, [source]) == 1
    assert set(_FakeClient.points) == first_ids

    source.write_text("second revision", encoding="utf-8")
    assert qdrant.register_documents(settings, [source]) == 1

    assert len(_FakeClient.points) == 1
    only_document = next(iter(_FakeClient.points.values()))
    assert only_document.page_content == "second revision"
    assert _FakeClient.delete_calls == 3


def test_verification_partial_failure_never_reports_success(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """書込みが部分状態でも確認不能なら有限retry後に操作全体を失敗させる。"""

    source = tmp_path / "reference.md"
    source.write_text("content", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_attempts=3,
        retry_base_seconds=0,
    )
    _FakeClient.retrieve_failures = 3

    with pytest.raises(qdrant.RegistrationError, match="during verify"):
        qdrant.register_documents(settings, [source])

    assert len(_FakeClient.points) == 1
    assert _FakeClient.delete_calls == 0


def test_registration_retries_write_verify_and_revision_delete(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """書込み・確認・旧revision削除の一時障害を有限回で回復する。"""

    source = tmp_path / "reference.md"
    source.write_text("first", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_attempts=3,
        retry_base_seconds=0,
    )
    _FakeClient.write_failures = 1
    _FakeClient.retrieve_failures = 1
    assert qdrant.register_documents(settings, [source]) == 1

    source.write_text("second", encoding="utf-8")
    _FakeClient.delete_failures = 1
    assert qdrant.register_documents(settings, [source]) == 1
    assert len(_FakeClient.points) == 1
    assert next(iter(_FakeClient.points.values())).page_content == "second"


@pytest.mark.parametrize("stage", ["write", "delete"])
def test_registration_permanent_stage_failure_is_not_success(
    stage: str, tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """書込みまたは置換が回復しなければ登録操作全体を失敗にする。"""

    source = tmp_path / "reference.md"
    source.write_text("first", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_attempts=2,
        retry_base_seconds=0,
    )
    if stage == "delete":
        assert qdrant.register_documents(settings, [source]) == 1
        source.write_text("second", encoding="utf-8")
        _FakeClient.delete_failures = 2
    else:
        _FakeClient.write_failures = 2

    expected_stage = "replace" if stage == "delete" else stage
    with pytest.raises(qdrant.RegistrationError, match=f"during {expected_stage}"):
        qdrant.register_documents(settings, [source])


def test_public_cli_directory_reregistration_replaces_across_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """公開CLIの異なるRunでも同じsource IDは旧revisionを置換する。"""

    source_dir = tmp_path / "references"
    source_dir.mkdir()
    source = source_dir / "guide.md"
    source.write_text("first revision", encoding="utf-8")
    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_base_seconds=0,
    )
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    runner = CliRunner()

    first = runner.invoke(
        cli.app,
        ["register", str(source_dir), "--source-id", "product-guides"],
    )
    source.write_text("second revision", encoding="utf-8")
    second = runner.invoke(
        cli.app,
        ["register", str(source_dir), "--source-id", "product-guides"],
    )

    assert first.exit_code == second.exit_code == 0, second.output
    assert len(RunRepository(settings.runs_dir).list_runs().records) == 2
    assert len(_FakeClient.points) == 1
    document = next(iter(_FakeClient.points.values()))
    assert document.page_content == "second revision"
    assert document.metadata["source"] == "references/guide.md"
