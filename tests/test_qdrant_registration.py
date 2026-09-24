"""参照文書登録のrevision置換と部分失敗を検証する。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, ClassVar
from zipfile import ZIP_DEFLATED, ZipFile

import pypdfium2 as pdfium
import pytest
from langchain_core.documents import Document
from typer.testing import CliRunner

import cli
from translate.adapters import qdrant
from translate.common.runs import RunRepository

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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
    fail_write_call: ClassVar[int | None] = None
    write_calls: ClassVar[int] = 0
    write_batch_sizes: ClassVar[list[int]] = []
    retrieve_batch_sizes: ClassVar[list[int]] = []
    client_timeouts: ClassVar[list[float]] = []

    def __init__(self, **kwargs: object) -> None:
        """構築時のtimeoutを記録し、登録の残期限がQdrant Clientへ渡るか確認する。"""

        timeout = kwargs.get("timeout")
        if isinstance(timeout, int | float):
            type(self).client_timeouts.append(float(timeout))

    @classmethod
    def reset(cls) -> None:
        """
        Point集合・障害回数・呼出履歴を初期化し、登録Test間で状態を共有しないようにする
        。
        """

        cls.points = {}
        cls.delete_calls = 0
        cls.retrieve_failures = 0
        cls.delete_failures = 0
        cls.write_failures = 0
        cls.fail_write_call = None
        cls.write_calls = 0
        cls.write_batch_sizes = []
        cls.retrieve_batch_sizes = []
        cls.client_timeouts = []

    def collection_exists(self, _collection: str) -> bool:
        """
        保存済みPointがある場合だけcollectionありとし、初回作成と追加入力の経路を切り替
        える。
        """

        return bool(self.points)

    def retrieve(self, **kwargs: object) -> list[_Record]:
        """要求ID数を記録し、指定回数だけ未確認を返した後に保存済みPointを照合する。"""

        type(self).retrieve_batch_sizes.append(len(kwargs["ids"]))  # type: ignore[arg-type]
        if self.retrieve_failures:
            type(self).retrieve_failures -= 1
            return []
        return [
            _Record(id=point_id)
            for point_id in kwargs["ids"]  # type: ignore[union-attr]
            if point_id in self.points
        ]

    def delete(self, **kwargs: object) -> None:
        """
        選択した削除障害を発生させ、成功時は同じsource keyの旧revisionだけをPoint集合か
        ら除く。
        """

        type(self).delete_calls += 1
        if self.delete_failures:
            type(self).delete_failures -= 1
            message = "temporary delete failure"
            raise OSError(message)
        selector = kwargs["points_selector"]
        source_key = selector.must[0].match.value
        current_revision = selector.must_not[0].match.value
        type(self).points = {
            point_id: document
            for point_id, document in self.points.items()
            if not (
                document.metadata["source_key"] == source_key
                and document.metadata.get("registration_revision") != current_revision
            )
        }


class _FakeStore:
    def __init__(self, **_kwargs: object) -> None:
        # VectorStoreの構築引数を受けるだけのdoubleとし、通信やClient生成を行わない。
        pass

    def add_documents(self, documents: list[Document], *, ids: list[str]) -> list[str]:
        """batch寸法と呼出数を記録し、指定回の障害またはID対応のPoint保存を行う。"""

        _FakeClient.write_calls += 1
        _FakeClient.write_batch_sizes.append(len(documents))
        should_fail = _FakeClient.fail_write_call == _FakeClient.write_calls
        if _FakeClient.write_failures:
            _FakeClient.write_failures -= 1
            should_fail = True
        if should_fail:
            message = "temporary write failure"
            raise OSError(message)
        _FakeClient.points.update(dict(zip(ids, documents, strict=True)))
        return ids

    @classmethod
    def from_documents(
        cls, documents: list[Document], _embedding: object, **kwargs: object
    ) -> _FakeStore:
        """collection初回作成の書込みを模擬し、batch障害注入と決定的IDの保存を行う。"""

        _FakeClient.write_calls += 1
        _FakeClient.write_batch_sizes.append(len(documents))
        should_fail = _FakeClient.fail_write_call == _FakeClient.write_calls
        if _FakeClient.write_failures:
            _FakeClient.write_failures -= 1
            should_fail = True
        if should_fail:
            message = "temporary write failure"
            raise OSError(message)
        ids = kwargs["ids"]
        _FakeClient.points.update(dict(zip(ids, documents, strict=True)))
        return cls()


@pytest.fixture(autouse=True)
def _qdrant_double(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Qdrant・Embedding・sleepを隔離したdoubleへ置き換え、登録を実サービスなしで検査する。
    """

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


def test_registration_removes_legacy_and_changed_setting_revisions(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """確認済み現revision以外はlegacy field欠落を含めて除去する。"""

    source = tmp_path / "reference.md"
    source.write_text("current content", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_base_seconds=0,
    )
    assert qdrant.register_documents(settings, [source]) == 1
    current = next(iter(_FakeClient.points.values()))
    source_key = str(current.metadata["source_key"])
    _FakeClient.points["legacy"] = Document(
        page_content="legacy",
        metadata={"source_key": source_key, "source_hash": "old"},
    )
    _FakeClient.points["changed-setting"] = Document(
        page_content="changed",
        metadata={
            "source_key": source_key,
            "source_hash": current.metadata["source_hash"],
            "registration_revision": "obsolete-settings",
        },
    )

    assert qdrant.register_documents(settings, [source]) == 1

    assert len(_FakeClient.points) == 1
    assert next(iter(_FakeClient.points.values())).metadata == current.metadata


def test_registration_revision_covers_schema_extraction_and_chunk_settings(
    tmp_path: Path, settings_factory: Callable[..., Settings]
) -> None:
    """source hash・分割数・OCR変更によるrevision差と固定schema名を確認する。"""

    source = tmp_path / "reference.pdf"
    source.write_bytes(b"pdf")
    registration_source = qdrant.RegistrationSource(
        path=source,
        logical_path="reference.pdf",
        source_key="stable-source",
    )
    base = settings_factory(
        split_pages=10,
        docling_ocr_preset="auto",
        docling_ocr_lang="eng",
        docling_force_ocr=False,
    )
    changed_split = base.model_copy(update={"split_pages": 5})
    changed_ocr = base.model_copy(update={"docling_force_ocr": True})

    revision = qdrant._registration_revision(  # noqa: SLF001
        registration_source, "source-hash", base
    )

    assert revision == qdrant._registration_revision(  # noqa: SLF001
        registration_source, "source-hash", base
    )
    assert revision != qdrant._registration_revision(  # noqa: SLF001
        registration_source, "other-hash", base
    )
    assert revision != qdrant._registration_revision(  # noqa: SLF001
        registration_source, "source-hash", changed_split
    )
    assert revision != qdrant._registration_revision(  # noqa: SLF001
        registration_source, "source-hash", changed_ocr
    )
    assert qdrant.CHUNK_SCHEMA == "registration-v2"


def test_registration_batches_are_bounded_and_point_ids_are_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """VectorStore書込みとretrieveのdoubleで16件以下のbatchとID再現性を確認する。"""

    class ManyChunks:
        def __init__(self, **_kwargs: object) -> None:
            # 分割設定を受けるだけのdoubleとし、実splitterの生成を避ける。
            pass

        def split_text(self, _text: str) -> list[str]:
            """130個の固定Chunkを返し、登録batchの上限とIDの決定性を検査可能にする。"""

            return [f"chunk-{index:03d}" for index in range(130)]

    monkeypatch.setattr(qdrant, "RecursiveCharacterTextSplitter", ManyChunks)
    source = tmp_path / "reference.md"
    source.write_text("content", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_base_seconds=0,
    )

    assert qdrant.register_documents(settings, [source]) == 130
    first_ids = set(_FakeClient.points)
    assert _FakeClient.write_batch_sizes == [16] * 8 + [2]
    assert max(_FakeClient.retrieve_batch_sizes) <= qdrant.REGISTRATION_BATCH_SIZE

    assert qdrant.register_documents(settings, [source]) == 130
    assert set(_FakeClient.points) == first_ids
    assert _FakeClient.write_batch_sizes == [16] * 8 + [2]
    assert max(_FakeClient.write_batch_sizes) <= qdrant.REGISTRATION_BATCH_SIZE
    assert max(_FakeClient.retrieve_batch_sizes) <= qdrant.REGISTRATION_BATCH_SIZE


def test_pdf_is_stream_hashed_split_once_and_reused_within_page_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """原PDFのread_bytesを禁止し、23頁を10/10/3頁へ一回だけ分割して再利用する。"""

    source = tmp_path / "large.pdf"
    with pdfium.PdfDocument.new() as document:
        for _ in range(23):
            document.new_page(100, 100)
        document.save(source)
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        docling_url="https://docling.invalid",
        split_pages=10,
        retry_base_seconds=0,
    )
    workspace = tmp_path / "workspace"
    split_calls = 0
    part_page_counts: list[int] = []
    original_split = qdrant.pdf.split
    original_read_bytes = type(source).read_bytes

    def split_spy(*args: object, **kwargs: object) -> object:
        """実PDF分割に委譲して回数を数え、同じ入力で分割が再利用されるか確認する。"""

        nonlocal split_calls
        split_calls += 1
        return original_split(*args, **kwargs)

    def reject_original_read_bytes(path: Path) -> bytes:
        """原本PDFに対するPath.read_bytesだけを拒否し、他のFileは元の処理へ渡す。"""

        if path == source:
            pytest.fail("original PDF must not be loaded by Path.read_bytes")
        return original_read_bytes(path)

    def extract_spy(path: Path, _settings: Settings, _deadline: float) -> str:
        """
        Doclingへ渡るPDF partのページ数を数え、実抽出の代わりにpart固有textを返す。
        """

        with pdfium.PdfDocument(path) as part:
            part_page_counts.append(len(part))
        return f"part-{path.stem}"

    monkeypatch.setattr(qdrant.pdf, "split", split_spy)
    monkeypatch.setattr(type(source), "read_bytes", reject_original_read_bytes)
    monkeypatch.setattr(qdrant, "_docling_text", extract_spy)

    assert qdrant.register_documents(settings, [source], workspace) == 3
    first_ids = set(_FakeClient.points)
    assert qdrant.register_documents(settings, [source], workspace) == 3

    assert split_calls == 1
    assert part_page_counts == [10, 10, 3, 10, 10, 3]
    assert max(part_page_counts) <= settings.split_pages
    assert set(_FakeClient.points) == first_ids


def test_failed_middle_batch_preserves_old_revision_and_resume_converges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """中間batch失敗時は旧revisionを残し、再実行で完全な新revisionへ収束する。"""

    class ManyChunks:
        def __init__(self, **_kwargs: object) -> None:
            # 分割設定を受けるだけに留め、中間batch障害試験を実splitterから独立させる。
            pass

        def split_text(self, _text: str) -> list[str]:
            """
            固定130Chunkを返し、中間batchの失敗後も同じIDで登録を収束できるか検査する。
            """

            return [f"chunk-{index:03d}" for index in range(130)]

    source = tmp_path / "reference.md"
    source.write_text("old", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_attempts=1,
        retry_base_seconds=0,
    )
    assert qdrant.register_documents(settings, [source]) == 1
    old_ids = set(_FakeClient.points)
    old_revision = next(iter(_FakeClient.points.values())).metadata[
        "registration_revision"
    ]
    source.write_text("new", encoding="utf-8")
    monkeypatch.setattr(qdrant, "RecursiveCharacterTextSplitter", ManyChunks)
    _FakeClient.write_calls = 0
    _FakeClient.fail_write_call = 2

    with pytest.raises(qdrant.RegistrationError, match="during write"):
        qdrant.register_documents(settings, [source])

    partial_new_ids = set(_FakeClient.points) - old_ids
    assert len(partial_new_ids) == 16
    assert any(
        document.metadata["registration_revision"] == old_revision
        for document in _FakeClient.points.values()
    )

    _FakeClient.fail_write_call = None
    _FakeClient.write_calls = 0
    assert qdrant.register_documents(settings, [source]) == 130
    assert partial_new_ids <= set(_FakeClient.points)
    assert len(_FakeClient.points) == 130
    revisions = {
        document.metadata["registration_revision"]
        for document in _FakeClient.points.values()
    }
    assert old_revision not in revisions
    assert len(revisions) == 1


def test_registration_deadline_is_shared_by_extraction_and_qdrant_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """共通絶対期限を超えた処理は現在stageのTimeoutErrorとして停止する。"""

    now = [0.0]

    class ExpiringSplitter:
        def __init__(self, **_kwargs: object) -> None:
            # 分割設定を無処理で受け、分割中に期限が尽きる条件だけを注入する。
            pass

        def split_text(self, _text: str) -> list[str]:
            """
            模擬時計を期限後へ進めてChunkを返し、後続の登録が残期限を再確認するか調べる
            。
            """

            now[0] = 2.0
            return ["too late"]

    monkeypatch.setattr(qdrant.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(qdrant, "RecursiveCharacterTextSplitter", ExpiringSplitter)
    source = tmp_path / "reference.md"
    source.write_text("content", encoding="utf-8")
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        task_deadline_seconds=1,
        retry_base_seconds=0,
    )

    with pytest.raises(qdrant.RegistrationError) as captured:
        qdrant.register_documents(settings, [source])

    assert captured.value.stage == "extract"
    assert captured.value.cause_type == "TimeoutError"
    assert _FakeClient.points == {}


def test_docling_and_qdrant_clients_receive_only_remaining_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """外部Client timeoutはrequest上限と登録残時間の小さい方になる。"""

    captured: dict[str, float] = {}
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as result:
        result.writestr("document.json", '{"texts":[{"text":"ok"}]}')

    class FakeDocling:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            """
            Docling構築時のtimeoutと期限を捕捉し、処理全体の残時間だけが渡るか検証する。
            """

            captured["timeout"] = float(kwargs["timeout_seconds"])
            captured["deadline"] = float(kwargs["deadline_seconds"])

        def convert(self, _path: Path) -> tuple[bytes, str]:
            """
            用意済みZIPを返し、抽出を実サービスなしで成功させて残期限の検査を続ける。
            """

            return archive.getvalue(), "ignored"

    settings = settings_factory(
        docling_url="https://docling.invalid",
        request_timeout_seconds=5,
        qdrant_url="https://qdrant.invalid",
    )
    source = tmp_path / "part.pdf"
    source.write_bytes(b"part")
    now = [10.0]
    monkeypatch.setattr(qdrant.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(qdrant, "DoclingClient", FakeDocling)

    assert qdrant._docling_text(source, settings, deadline=30.0) == "ok"  # noqa: SLF001
    assert captured == {"timeout": 5.0, "deadline": 20.0}

    now[0] = 24.0
    qdrant._registration_client(settings, deadline=30.0)  # noqa: SLF001
    assert _FakeClient.client_timeouts[-1] == 5.0
    now[0] = 28.0
    qdrant._registration_client(settings, deadline=30.0)  # noqa: SLF001
    assert _FakeClient.client_timeouts[-1] == 2.0


def test_only_registration_write_boundary_retries_transient_type_error(
    settings_factory: Callable[..., Settings],
) -> None:
    """retry helperの明示flagでTypeErrorの再試行を許可し、既定では即時伝播する。"""

    settings = settings_factory(retry_attempts=2, retry_base_seconds=0)
    attempts = 0

    def flaky() -> str:
        """初回だけTypeErrorを投げ、helperのflagによる再試行を検証する。"""

        nonlocal attempts
        attempts += 1
        if attempts == 1:
            message = "transient malformed embedding response"
            raise TypeError(message)
        return "ok"

    def programming_error() -> None:
        """
        プログラム不具合相当のTypeErrorを投げ、書込み以外へ再試行許可が広がらないか調べ
        る。
        """

        message = "programming error"
        raise TypeError(message)

    assert (
        qdrant._retry(  # noqa: SLF001
            settings,
            flaky,
            retry_type_error=True,
        )
        == "ok"
    )
    assert attempts == 2

    with pytest.raises(TypeError):
        qdrant._retry(settings, programming_error)  # noqa: SLF001


def test_public_cli_resumes_failed_middle_batch_with_same_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """公開CLIの明示Resumeで部分Pointを決定的にupsertして完了する。"""

    class ManyChunks:
        def __init__(self, **_kwargs: object) -> None:
            # 公開CLI試験用の分割設定を受理し、実splitterは使用しない。
            pass

        def split_text(self, _text: str) -> list[str]:
            """
            公開CLIへ固定130Chunkを供給し、中間batch失敗後の同じRunでの再開を検証する。
            """

            return [f"chunk-{index:03d}" for index in range(130)]

    source = tmp_path / "reference.md"
    source.write_text("content", encoding="utf-8")
    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_attempts=1,
        retry_base_seconds=0,
    )
    monkeypatch.setattr(qdrant, "RecursiveCharacterTextSplitter", ManyChunks)
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    _FakeClient.fail_write_call = 2
    runner = CliRunner()

    failed = runner.invoke(cli.app, ["register", str(source)])
    record = RunRepository(settings.runs_dir).list_runs().records[0]
    partial_ids = set(_FakeClient.points)

    assert failed.exit_code == 1
    assert "task=REGISTER" in failed.output
    assert "stage=write" in failed.output
    assert record.status == "failed"
    assert len(partial_ids) == 16

    _FakeClient.fail_write_call = None
    _FakeClient.write_calls = 0
    resumed = runner.invoke(
        cli.app,
        ["register", str(source), "--resume", record.run_id],
    )
    completed = RunRepository(settings.runs_dir).load(record.run_id)

    assert resumed.exit_code == 0, resumed.output
    assert f"run_id={record.run_id} mode=resume" in resumed.output
    assert completed.status == "completed"
    assert partial_ids <= set(_FakeClient.points)
    assert len(_FakeClient.points) == 130
