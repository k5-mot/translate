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
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import httpx
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http import models

from translate.adapters.docling import DoclingClient
from translate.common.workspace import atomic_write_bytes, atomic_write_json

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.settings import Settings

SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}


class RegistrationError(RuntimeError):
    """Qdrant登録が完全には確認できなかったことを示す。"""


class _VerificationIncompleteError(OSError):
    """書込み後のPoint確認がまだ完了していないことを示す。"""


@dataclass(frozen=True, slots=True)
class RegistrationSource:
    """Run pathから独立した登録対象とIdentity。"""

    path: Path
    logical_path: str
    source_key: str


def _retryable(error: Exception) -> bool:
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


def _retry[T](settings: Settings, operation: Callable[[], T]) -> T:
    deadline = time.monotonic() + settings.task_deadline_seconds
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            return operation()
        except Exception as error:
            if (
                not _retryable(error)
                or attempt >= settings.retry_attempts
                or time.monotonic() >= deadline
            ):
                raise
            delay = min(
                settings.retry_base_seconds * (2 ** (attempt - 1)),
                settings.retry_max_seconds,
            )
            time.sleep(
                random.uniform(  # noqa: S311
                    0, min(delay, max(0.0, deadline - time.monotonic()))
                )
            )
    msg = "Qdrant operation exhausted without response"
    raise RuntimeError(msg)


def _embeddings(settings: Settings) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model or "",
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
    )


def _store(settings: Settings) -> QdrantVectorStore:
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


def _docling_text(path: Path, settings: Settings) -> str:
    if not settings.docling_url:
        msg = "DOCLING_SERVER_URL is required for binary reference documents"
        raise ValueError(msg)
    payload, _ = DoclingClient(
        settings.docling_url,
        settings.docling_api_key,
        ocr_preset=settings.docling_ocr_preset,
        ocr_lang=settings.docling_ocr_lang,
        force_ocr=settings.docling_force_ocr,
        retry_attempts=settings.retry_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        timeout_seconds=settings.request_timeout_seconds,
        deadline_seconds=settings.task_deadline_seconds,
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
    return "\n\n".join(texts)


def _text(path: Path, settings: Settings) -> str:
    if path.suffix.casefold() in {".md", ".markdown", ".txt"}:
        return path.read_text(encoding="utf-8")
    # Note 1: PDF, DOCX and PPTX share one extraction contract through Docling.
    return _docling_text(path, settings)


def register_documents(
    settings: Settings, paths: list[Path | RegistrationSource]
) -> int:
    """文書を収集・分割・Embeddingし、Qdrantへ登録する。"""

    stage = "collect"
    try:
        sources = _registration_sources(paths)
        if not sources:
            msg = "no supported reference documents found"
            raise ValueError(msg)  # noqa: TRY301
        splitter = RecursiveCharacterTextSplitter(chunk_size=1_000, chunk_overlap=100)
        documents: list[Document] = []
        ids: list[str] = []
        revisions: dict[str, tuple[str, str]] = {}
        stage = "extract"
        for source in sources:
            path = source.path
            source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            revisions[source.source_key] = (source.logical_path, source_hash)
            for index, chunk in enumerate(splitter.split_text(_text(path, settings))):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "source": source.logical_path,
                            "source_key": source.source_key,
                            "source_hash": source_hash,
                            "chunk": index,
                        },
                    )
                )
                ids.append(
                    str(
                        uuid5(
                            NAMESPACE_URL,
                            f"{source.source_key}:{source_hash}:{index}",
                        )
                    )
                )
        if not documents:
            msg = "reference documents contain no extractable text"
            raise ValueError(msg)  # noqa: TRY301

        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        collection = settings.qdrant_collection or ""
        embedding = _embeddings(settings)

        def write_all() -> None:
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
            )

        stage = "write"
        _retry(settings, write_all)

        def verify_all() -> None:
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
                raise _VerificationIncompleteError(msg)  # noqa: TRY301

        stage = "verify"
        _retry(settings, verify_all)

        # Note 2: Verify the new revision before removing only older hashes.
        stage = "replace"
        for source_key, (_logical_path, source_hash) in revisions.items():
            selector = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.source_key",
                        match=models.MatchValue(value=source_key),
                    )
                ],
                must_not=[
                    models.FieldCondition(
                        key="metadata.source_hash",
                        match=models.MatchValue(value=source_hash),
                    )
                ],
            )
            _retry(
                settings,
                lambda selector=selector: client.delete(
                    collection_name=collection,
                    points_selector=selector,
                    wait=True,
                ),
            )
    except (ValueError, RegistrationError):
        raise
    except Exception as error:  # noqa: BLE001
        msg = f"Qdrant registration failed during {stage}: {type(error).__name__}"
        raise RegistrationError(msg) from None
    return len(documents)


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
