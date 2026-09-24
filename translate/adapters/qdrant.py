"""Qdrant検索と参照文書登録を一つのinterfaceで提供する。"""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import NAMESPACE_URL, uuid5

import httpx
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http import models

from translate.adapters import pdf
from translate.adapters.docling import DoclingClient
from translate.common.terminal_evidence import count_external_call
from translate.common.workspace import (
    atomic_write_bytes,
    atomic_write_json,
    sha256_file,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.settings import Settings

SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}
CHUNK_SCHEMA = "registration-v2"
CHUNK_SIZE = 1_000
CHUNK_OVERLAP = 100
# Bounded requests avoid scaling embedding and retrieve payloads with the whole input.
REGISTRATION_BATCH_SIZE = 16
RegistrationStage = Literal[
    "collect", "hash", "split", "extract", "write", "verify", "replace"
]
REGISTRATION_STAGES = frozenset(
    {"collect", "hash", "split", "extract", "write", "verify", "replace"}
)


class RegistrationError(RuntimeError):
    """登録stageと安全な下位例外型だけを公開する。"""

    def __init__(self, stage: RegistrationStage, cause: BaseException) -> None:
        """登録失敗stageと原因型を公開し、文書本文や接続詳細を例外メッセージへ含めない。"""

        if stage not in REGISTRATION_STAGES:
            msg = "invalid registration stage"
            raise ValueError(msg)
        self.stage = stage
        self.cause_type = type(cause).__name__
        super().__init__(
            f"Qdrant registration failed during {stage}: {self.cause_type}"
        )


class _VerificationIncompleteError(OSError):
    """書込み後のPoint確認がまだ完了していないことを示す。"""


@dataclass(frozen=True, slots=True)
class RegistrationSource:
    """Run pathから独立した登録対象とIdentity。"""

    path: Path
    logical_path: str
    source_key: str


@dataclass(frozen=True, slots=True)
class _PreparedSource:
    source: RegistrationSource
    source_hash: str
    revision: str
    parts: tuple[Path, ...]


def _retryable(error: Exception) -> bool:
    """通信・I/O障害と一時的なHTTP statusを、Qdrant操作の再試行対象として分類する。"""

    status = getattr(error, "status_code", None)
    return (
        isinstance(
            error,
            (
                httpx.TransportError,
                TimeoutError,
                ConnectionError,
                OSError,
                _VerificationIncompleteError,
            ),
        )
        or status in {408, 429}
        or (isinstance(status, int) and status >= 500)
    )


def _retry[T](
    settings: Settings,
    operation: Callable[[], T],
    *,
    deadline: float | None = None,
    retry_type_error: bool = False,
) -> T:
    """期限内で一時障害を有限回再試行し、TypeErrorは指定された外部書込み境界だけで扱う。"""

    expires = deadline or time.monotonic() + settings.task_deadline_seconds
    for attempt in range(1, settings.retry_attempts + 1):
        _ensure_time(expires)
        try:
            result = operation()
        except Exception as error:
            retryable = _retryable(error) or (
                retry_type_error and isinstance(error, TypeError)
            )
            if not retryable or attempt >= settings.retry_attempts:
                raise
            _ensure_time(expires)
            delay = min(
                settings.retry_base_seconds * (2 ** (attempt - 1)),
                settings.retry_max_seconds,
            )
            time.sleep(
                random.uniform(  # noqa: S311
                    0, min(delay, max(0.0, expires - time.monotonic()))
                )
            )
        else:
            _ensure_time(expires)
            return result
    msg = "Qdrant operation exhausted without response"
    raise RuntimeError(msg)


def _ensure_time(deadline: float) -> float:
    """共通期限までの残秒数を返し、期限切れなら次の登録処理へ進めず停止する。"""

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        msg = "registration deadline exceeded"
        raise TimeoutError(msg)
    return remaining


def _registration_client(settings: Settings, deadline: float) -> QdrantClient:
    """現在の残時間を上限にした登録用Clientを生成する。"""

    count_external_call("qdrant")
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=_qdrant_timeout(settings, deadline),
    )


def _qdrant_timeout(settings: Settings, deadline: float) -> int:
    """Qdrantの整数秒timeoutを残時間以下へ切り下げる。"""

    available = min(settings.request_timeout_seconds, _ensure_time(deadline))
    if available < 1:
        msg = "registration deadline has less than one second remaining"
        raise TimeoutError(msg)
    return int(available)


def _embeddings(settings: Settings) -> OpenAIEmbeddings:
    """登録・検索用Embedding Clientを構成し、検証counterへClient生成を通知する。"""

    count_external_call("embedding")
    return OpenAIEmbeddings(
        model=settings.embedding_model or "",
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
    )


def _store(settings: Settings) -> QdrantVectorStore:
    """指定済みcollectionへEmbedding Clientを接続し、類似検索用VectorStoreを得る。"""

    return QdrantVectorStore.from_existing_collection(
        collection_name=settings.qdrant_collection or "",
        embedding=_embeddings(settings),
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )


def search(
    settings: Settings,
    query: str,
    limit: int = 5,
    artifact_path: Path | None = None,
) -> list[dict[str, object]]:
    """queryに近い参照文書を有限retryし、再現用Artifactを保存する。"""

    if not settings.qdrant_enabled or not query.strip():
        return []
    count_external_call("qdrant")
    results = _retry(
        settings,
        lambda: [
            {"text": document.page_content, **document.metadata, "score": score}
            for document, score in _store(settings).similarity_search_with_score(
                query, k=limit
            )
        ],
    )
    if artifact_path is not None:
        atomic_write_json(
            artifact_path,
            {
                "query": query,
                "collection": settings.qdrant_collection,
                "searched_at": datetime.now(UTC).isoformat(),
                "citations": sorted(
                    {
                        str(item["source"])
                        for item in results
                        if item.get("source") is not None
                    }
                ),
                "results": results,
            },
        )
    return results


def _docling_text(path: Path, settings: Settings, deadline: float) -> str:
    """binary文書を残時間以内の条件でDoclingへ送り、ZIP内の単一JSONから登録textを得る。"""

    if not settings.docling_url:
        msg = "DOCLING_SERVER_URL is required for binary reference documents"
        raise ValueError(msg)
    remaining = _ensure_time(deadline)
    payload, _ = DoclingClient(
        settings.docling_url,
        settings.docling_api_key,
        ocr_preset=settings.docling_ocr_preset,
        ocr_lang=settings.docling_ocr_lang,
        force_ocr=settings.docling_force_ocr,
        retry_attempts=settings.retry_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        timeout_seconds=min(settings.request_timeout_seconds, remaining),
        deadline_seconds=remaining,
    ).convert(path)
    with tempfile.TemporaryDirectory(prefix="qdrant-docling-") as temporary:
        archive_path = Path(temporary) / "result.zip"
        atomic_write_bytes(archive_path, payload)
        with zipfile.ZipFile(archive_path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".json")]
            if len(names) != 1:
                msg = "Docling result must contain exactly one JSON file"
                raise ValueError(msg)
            value = json.loads(archive.read(names[0]))
    texts = [
        str(item.get("text", "")).strip()
        for collection in ("texts", "tables", "pictures")
        for item in value.get(collection, [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    _ensure_time(deadline)
    return "\n\n".join(texts)


def _text(path: Path, settings: Settings, deadline: float) -> str:
    """参照文書の形式に応じUTF-8読取りかDocling抽出を選び、分割対象textを得る。"""

    if path.suffix.casefold() in {".md", ".markdown", ".txt"}:
        _ensure_time(deadline)
        return path.read_text(encoding="utf-8")
    return _docling_text(path, settings, deadline)


def register_documents(
    settings: Settings,
    paths: list[Path | RegistrationSource],
    workspace_dir: Path | None = None,
) -> int:
    """文書を有界単位で抽出・Embeddingし、確認後にrevisionを置換する。"""

    deadline = time.monotonic() + settings.task_deadline_seconds
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if workspace_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="qdrant-registration-")
        workspace = Path(temporary.name)
    else:
        workspace = workspace_dir
        workspace.mkdir(parents=True, exist_ok=True)
    try:
        return _register(settings, paths, workspace, deadline)
    finally:
        if temporary is not None:
            temporary.cleanup()


def _register(
    settings: Settings,
    paths: list[Path | RegistrationSource],
    workspace: Path,
    deadline: float,
) -> int:
    """入力を逐次抽出して決定的IDのchunkを書込み・確認し、その後に同じ入力の旧版を削除する。"""

    try:
        sources = _registration_sources(paths)
    except ValueError:
        raise
    except Exception as error:  # noqa: BLE001
        raise RegistrationError("collect", error) from None
    if not sources:
        msg = "no supported reference documents found"
        raise ValueError(msg)

    prepared: list[_PreparedSource] = []
    for source in sources:
        try:
            _ensure_time(deadline)
            source_hash = sha256_file(source.path)
        except Exception as error:  # noqa: BLE001
            raise RegistrationError("hash", error) from None
        try:
            parts = _source_parts(source, source_hash, settings, workspace, deadline)
        except RegistrationError:
            raise
        except Exception as error:  # noqa: BLE001
            raise RegistrationError("split", error) from None
        prepared.append(
            _PreparedSource(
                source=source,
                source_hash=source_hash,
                revision=_registration_revision(source, source_hash, settings),
                parts=parts,
            )
        )

    try:
        _ensure_time(deadline)
        embedding = _embeddings(settings)
    except Exception as error:  # noqa: BLE001
        raise RegistrationError("write", error) from None

    collection = settings.qdrant_collection or ""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    documents: list[Document] = []
    ids: list[str] = []
    total = 0

    for item in prepared:
        chunk_index = 0
        for part_number, part in enumerate(item.parts, 1):
            try:
                text = _text(part, settings, deadline)
                chunks = splitter.split_text(text)
                _ensure_time(deadline)
            except Exception as error:  # noqa: BLE001
                raise RegistrationError("extract", error) from None
            for chunk in chunks:
                metadata: dict[str, object] = {
                    "source": item.source.logical_path,
                    "source_key": item.source.source_key,
                    "source_hash": item.source_hash,
                    "registration_revision": item.revision,
                    "chunk_schema": CHUNK_SCHEMA,
                    "chunk": chunk_index,
                }
                if item.source.path.suffix.casefold() == ".pdf":
                    metadata["part"] = part_number
                documents.append(Document(page_content=chunk, metadata=metadata))
                ids.append(
                    str(
                        uuid5(
                            NAMESPACE_URL,
                            f"{item.source.source_key}:{item.revision}:{chunk_index}",
                        )
                    )
                )
                chunk_index += 1
                total += 1
                if len(documents) == REGISTRATION_BATCH_SIZE:
                    _write_and_verify(
                        settings,
                        embedding,
                        collection,
                        documents,
                        ids,
                        deadline,
                    )
                    documents = []
                    ids = []

    if documents:
        _write_and_verify(
            settings,
            embedding,
            collection,
            documents,
            ids,
            deadline,
        )
    if total == 0:
        error = ValueError("reference documents contain no extractable text")
        raise RegistrationError("extract", error) from None

    for item in prepared:
        selector = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.source_key",
                    match=models.MatchValue(value=item.source.source_key),
                )
            ],
            must_not=[
                models.FieldCondition(
                    key="metadata.registration_revision",
                    match=models.MatchValue(value=item.revision),
                )
            ],
        )
        try:
            _retry(
                settings,
                lambda selector=selector: _registration_client(
                    settings, deadline
                ).delete(
                    collection_name=collection,
                    points_selector=selector,
                    wait=True,
                ),
                deadline=deadline,
            )
        except Exception as error:  # noqa: BLE001
            raise RegistrationError("replace", error) from None
    return total


def _write_and_verify(
    settings: Settings,
    embedding: OpenAIEmbeddings,
    collection: str,
    documents: list[Document],
    ids: list[str],
    deadline: float,
) -> None:
    """全Pointが既存なら省略し、未充足ならbatch書込み後に全IDを確認して失敗stageを区別する。"""

    def batch_exists() -> bool:
        """再実行の重複書込みを避けるため、今回の全Point IDがcollectionに存在するか照合する。"""

        client = _registration_client(settings, deadline)
        if not client.collection_exists(collection):
            return False
        records = client.retrieve(
            collection_name=collection,
            ids=ids,
            with_payload=False,
            with_vectors=False,
        )
        actual = {str(record.id) for record in records}
        return set(ids) <= actual

    try:
        if _retry(settings, batch_exists, deadline=deadline):
            return
    except Exception as error:  # noqa: BLE001
        raise RegistrationError("verify", error) from None

    def write_batch() -> None:
        """Embedding付きbatchをcollectionへ追加し、未作成なら最初のbatchから作成する。"""

        client = _registration_client(settings, deadline)
        if client.collection_exists(collection):
            QdrantVectorStore(
                client=client,
                collection_name=collection,
                embedding=embedding,
            ).add_documents(documents, ids=ids)
            return
        QdrantVectorStore.from_documents(
            documents,
            embedding,
            ids=ids,
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection_name=collection,
            timeout=_qdrant_timeout(settings, deadline),
        )

    try:
        # Some OpenAI-compatible local embedding servers surface a transient,
        # malformed response as TypeError. Retry only this external write boundary.
        _retry(
            settings,
            write_batch,
            deadline=deadline,
            retry_type_error=True,
        )
    except Exception as error:  # noqa: BLE001
        raise RegistrationError("write", error) from None

    def verify_batch() -> None:
        """書込み後に全Point IDを再取得し、不足は有限再試行対象の確認未完了例外とする。"""

        client = _registration_client(settings, deadline)
        records = client.retrieve(
            collection_name=collection,
            ids=ids,
            with_payload=False,
            with_vectors=False,
        )
        actual = {str(record.id) for record in records}
        missing = set(ids) - actual
        if missing:
            msg = f"registration verification missing {len(missing)} point(s)"
            raise _VerificationIncompleteError(msg)

    try:
        _retry(settings, verify_batch, deadline=deadline)
    except Exception as error:  # noqa: BLE001
        raise RegistrationError("verify", error) from None


def _registration_revision(
    source: RegistrationSource,
    source_hash: str,
    settings: Settings,
) -> str:
    """同じ入力の旧Pointと区別するため、原文hashと抽出・分割条件から登録revisionを決める。"""

    binary = source.path.suffix.casefold() in {".pdf", ".docx", ".pptx"}
    value = {
        "schema": CHUNK_SCHEMA,
        "source_hash": source_hash,
        "suffix": source.path.suffix.casefold(),
        "split_pages": (
            settings.split_pages if source.path.suffix.casefold() == ".pdf" else None
        ),
        "docling": (
            {
                "ocr_preset": settings.docling_ocr_preset,
                "ocr_lang": settings.docling_ocr_lang,
                "force_ocr": settings.docling_force_ocr,
            }
            if binary
            else None
        ),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _source_parts(
    source: RegistrationSource,
    source_hash: str,
    settings: Settings,
    workspace: Path,
    deadline: float,
) -> tuple[Path, ...]:
    """大きなPDFを抽出単位へ分割し、同じ入力hashと分割条件の成果物は検査後に再利用する。"""

    if source.path.suffix.casefold() != ".pdf":
        return (source.path,)
    key = hashlib.sha256(
        f"{source.source_key}\0{source_hash}\0{settings.split_pages}".encode()
    ).hexdigest()
    target = workspace / "pdf-parts" / key
    existing = _valid_pdf_parts(target, settings.split_pages)
    if existing is not None:
        return existing
    _ensure_time(deadline)
    pdf.split(source.path, target, settings.split_pages)
    _ensure_time(deadline)
    created = _valid_pdf_parts(target, settings.split_pages)
    if created is None:
        msg = "split PDF artifact is incomplete"
        raise ValueError(msg)
    return created


def _valid_pdf_parts(root: Path, pages_per_part: int) -> tuple[Path, ...] | None:
    """分割成果物の印・manifest・ページ範囲・File配置を検査し、再利用不可ならNoneを返す。"""

    manifest_path = root / "manifest.json"
    if not (root / ".complete.json").is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        items = sorted(manifest["parts"], key=lambda item: int(item["number"]))
        parts: list[Path] = []
        for item in items:
            first = int(item["first_page"])
            last = int(item["last_page"])
            if first < 1 or last < first or last - first + 1 > pages_per_part:
                return None
            candidate = root / Path(str(item["path"])).name
            if not candidate.is_file() or candidate.resolve().parent != root.resolve():
                return None
            parts.append(candidate)
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None
    return tuple(parts) if parts else None


def _registration_sources(
    values: list[Path | RegistrationSource],
) -> list[RegistrationSource]:
    """直接Adapter利用もstable identity付きのFile列へ正規化する。"""

    sources: list[RegistrationSource] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, RegistrationSource):
            candidates = [value]
        else:
            root = value.resolve()
            files = [root] if root.is_file() else sorted(root.rglob("*"))
            candidates = [
                RegistrationSource(
                    path=path.resolve(),
                    logical_path=(
                        path.name
                        if root.is_file()
                        else f"{root.name}/{path.relative_to(root).as_posix()}"
                    ),
                    source_key=hashlib.sha256(
                        os.path.normcase(str(path.resolve())).encode("utf-8")
                    ).hexdigest(),
                )
                for path in files
                if path.is_file() and path.suffix.casefold() in SUPPORTED
            ]
        for source in candidates:
            if source.path.suffix.casefold() not in SUPPORTED:
                continue
            if not source.source_key:
                msg = f"registration source lacks source key: {source.logical_path}"
                raise ValueError(msg)
            if source.source_key in seen:
                msg = f"duplicate registration source key: {source.logical_path}"
                raise ValueError(msg)
            seen.add(source.source_key)
            sources.append(source)
    return sorted(sources, key=lambda item: (item.logical_path, item.source_key))
