"""参照資料をEmbeddingしてQdrantへ登録するRegister Pipeline。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict
from uuid_utils import uuid7

from translate.adapters.docling import DoclingClient
from translate.adapters.embedding import embed
from translate.adapters.pdf import split_pdf
from translate.adapters.qdrant import upsert_revision
from translate.artifact_store import (
    ProcessingLock,
    canonical_hash,
    load_model,
    sha256_file,
    write_model,
)
from translate.models.artifacts import (
    InputFile,
    ProcessingError,
    RegistrationRecord,
    RegistrationResult,
    RegistrationSourceResult,
)
from translate.pipeline import InputError

if TYPE_CHECKING:
    from translate.common.config import Config

_SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}
_TEXT = {".md", ".markdown", ".txt"}
_CHUNK_SCHEMA = "registration-v1"
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 100
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class RegistrationOutcome(BaseModel):
    """CLIへ返すRegistration IDと記録path。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    registration_id: str
    processing_directory: Path
    record: Path


@dataclass(frozen=True, slots=True)
class _Source:
    """登録対象fileと論理path、Qdrant source key。"""

    path: Path
    logical_path: str
    source_key: str
    input: InputFile


def register_paths(
    paths: list[Path],
    config: Config,
    *,
    source_id: str | None = None,
    resume_id: str | None = None,
    outputs: Path | None = None,
) -> RegistrationOutcome:
    """入力を列挙・抽出・分割し、決定的Point IDでQdrantへ登録する。"""

    if not paths:
        raise InputError("at least one registration path is required")
    if len(paths) > 1 and source_id is None:
        raise InputError("source-id is required for multiple registration paths")
    if source_id is not None:
        _validate_source_id(source_id)
    config.require_register()
    outputs_root = (outputs or Path.cwd() / "outputs").resolve()
    try:
        sources = _collect(paths, source_id, outputs_root)
    except ValueError as error:
        raise InputError(str(error)) from error
    if (
        any(source.path.suffix.casefold() not in _TEXT for source in sources)
        and config.docling_server_url is None
    ):
        raise InputError("Docling settings are required for binary references")
    registration_id = _processing_id(resume_id)
    top_name = source_id or _single_top_name(paths)
    root = outputs_root / top_name / registration_id
    record_path = root / "registration.json"
    fingerprint = _fingerprint(sources, source_id, config)
    with ProcessingLock(root):
        record = _record(
            record_path,
            registration_id,
            source_id,
            sources,
            fingerprint,
            config,
            resume_id is not None,
        )
        try:
            if record.status == "succeeded" and record.result is not None:
                return RegistrationOutcome(
                    registration_id=registration_id,
                    processing_directory=root,
                    record=record_path,
                )
            _register_sources(record, record_path, sources, config)
        except KeyboardInterrupt:
            record.status = "cancelled"
            record.updated_at = datetime.now(UTC)
            write_model(record_path, record)
            raise
        except Exception as error:
            record.status = "failed"
            record.error = ProcessingError(
                code="registration_failed",
                message="Reference registration did not complete.",
                cause_type=type(error).__name__,
                retryable=True,
            )
            record.updated_at = datetime.now(UTC)
            write_model(record_path, record)
            raise
    return RegistrationOutcome(
        registration_id=registration_id,
        processing_directory=root,
        record=record_path,
    )


def _register_sources(
    record: RegistrationRecord,
    record_path: Path,
    sources: list[_Source],
    config: Config,
) -> None:
    """各資料の新revisionを書込み確認し、進捗を最上位記録へ保存する。"""

    completed = {
        item.logical_path: item
        for item in (record.result.sources if record.result else [])
    }
    results: list[RegistrationSourceResult] = []
    for source in sources:
        revision = _revision(source, config)
        previous = completed.get(source.logical_path)
        if previous is not None and previous.revision == revision:
            results.append(previous)
            continue
        text = _extract(source.path, config)
        chunks = _chunks(text)
        if not chunks:
            raise ValueError(
                f"reference contains no extractable text: {source.logical_path}"
            )
        vectors = embed(chunks, config)
        points = [
            {
                "id": str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{source.source_key}\0{revision}\0{index}",
                    )
                ),
                "vector": vector,
                "payload": {
                    "source_key": source.source_key,
                    "revision": revision,
                    "chunk_index": index,
                    "logical_path": source.logical_path,
                    "content": chunk,
                    "content_sha256": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    "chunk_schema": _CHUNK_SCHEMA,
                    "embedding_model": config.openai_embedding_model,
                },
            }
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        written = upsert_revision(
            config=config,
            source_key=source.source_key,
            revision=revision,
            points=points,
            vector_size=len(vectors[0]),
        )
        results.append(
            RegistrationSourceResult(
                logical_path=source.logical_path,
                sha256=source.input.sha256,
                revision=revision,
                point_count=len(points),
                status="registered" if written else "unchanged",
            )
        )
        record.result = RegistrationResult(
            collection=config.qdrant_collection or "",
            embedding_model=config.openai_embedding_model or "",
            sources=results,
            total_points=sum(item.point_count for item in results),
        )
        record.status = "processing"
        record.updated_at = datetime.now(UTC)
        write_model(record_path, record)
    record.result = RegistrationResult(
        collection=config.qdrant_collection or "",
        embedding_model=config.openai_embedding_model or "",
        sources=results,
        total_points=sum(item.point_count for item in results),
    )
    record.status = "succeeded"
    record.error = None
    record.updated_at = datetime.now(UTC)
    write_model(record_path, record)


def _collect(
    paths: list[Path], source_id: str | None, outputs_root: Path
) -> list[_Source]:
    """入力をsymlink非追跡で展開し、重複しない論理path順へ正規化する。"""

    collected: list[tuple[Path, str]] = []
    for value in paths:
        root = value.resolve()
        if root.is_file():
            if root.suffix.casefold() not in _SUPPORTED:
                raise ValueError(f"unsupported registration file: {root.name}")
            collected.append((root, root.name))
            continue
        if not root.is_dir():
            raise ValueError(f"registration path does not exist: {value}")
        for path in sorted(root.rglob("*")):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix.casefold() not in _SUPPORTED
            ):
                continue
            resolved = path.resolve()
            if resolved.is_relative_to(outputs_root):
                continue
            collected.append(
                (resolved, f"{root.name}/{path.relative_to(root).as_posix()}")
            )
    if not collected:
        raise ValueError("no supported reference documents found")
    logical_paths = [logical for _, logical in collected]
    if len(logical_paths) != len(set(logical_paths)):
        raise ValueError("registration inputs contain duplicate logical paths")
    return [
        _Source(
            path=path,
            logical_path=logical,
            source_key=f"{source_id}/{logical}" if source_id else logical,
            input=InputFile(
                role="reference",
                logical_path=logical,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            ),
        )
        for path, logical in sorted(collected, key=lambda item: item[1])
    ]


def _extract(path: Path, config: Config) -> str:
    """text形式はUTF-8で読み、binary形式はDocling本文を抽出する。"""

    if path.suffix.casefold() in _TEXT:
        return (
            path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
    with tempfile.TemporaryDirectory(prefix="translate-register-") as temporary_name:
        temporary = Path(temporary_name)
        parts = (
            split_pdf(path, temporary / "parts", config.pdf_split_pages)
            if path.suffix.casefold() == ".pdf"
            else [path]
        )
        return "\n\n".join(_docling_text(part, config) for part in parts)


def _docling_text(path: Path, config: Config) -> str:
    """一つの文書をDoclingへ送り、collection直下の本文を読み順で連結する。"""

    payload, _job_id, _polls = DoclingClient(config).convert(path)
    with tempfile.TemporaryDirectory(prefix="translate-docling-") as temporary_name:
        archive_path = Path(temporary_name) / "result.zip"
        archive_path.write_bytes(payload)
        with zipfile.ZipFile(archive_path) as archive:
            names = [
                name for name in archive.namelist() if name.casefold().endswith(".json")
            ]
            if len(names) != 1:
                raise ValueError("Docling result must contain exactly one JSON file")
            value = json.loads(archive.read(names[0]).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Docling JSON must be an object")
    texts = [
        str(item.get("text", "")).strip()
        for collection in ("texts", "tables", "pictures")
        for item in value.get(collection, [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    return "\n\n".join(texts)


def _chunks(value: str) -> list[str]:
    """段落境界を優先し、最大1000文字・最大100文字重複で分割する。"""

    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        maximum_end = min(start + _CHUNK_SIZE, len(text))
        end = maximum_end
        if maximum_end < len(text):
            boundary = text.rfind("\n\n", start + 1, maximum_end + 1)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - _CHUNK_OVERLAP)
    return chunks


def _revision(source: _Source, config: Config) -> str:
    """入力hash、抽出条件、chunk schema、Embedding modelからrevisionを作る。"""

    return canonical_hash(
        {
            "sha256": source.input.sha256,
            "suffix": source.path.suffix.casefold(),
            "split_pages": config.pdf_split_pages,
            "ocr": [
                config.docling_ocr_preset,
                config.docling_ocr_lang,
                config.docling_force_ocr,
            ],
            "chunk_schema": _CHUNK_SCHEMA,
            "embedding_model": config.openai_embedding_model,
        }
    )


def _fingerprint(
    sources: list[_Source],
    source_id: str | None,
    config: Config,
) -> str:
    """Register Resume判定に必要な順序付き入力と出力影響設定をhash化する。"""

    return canonical_hash(
        {
            "source_id": source_id,
            "inputs": [source.input.model_dump(mode="json") for source in sources],
            "split_pages": config.pdf_split_pages,
            "ocr": [
                config.docling_ocr_preset,
                config.docling_ocr_lang,
                config.docling_force_ocr,
            ],
            "chunk_schema": _CHUNK_SCHEMA,
            "embedding_model": config.openai_embedding_model,
            "collection": config.qdrant_collection,
        }
    )


def _record(
    path: Path,
    registration_id: str,
    source_id: str | None,
    sources: list[_Source],
    fingerprint: str,
    config: Config,
    resuming: bool,
) -> RegistrationRecord:
    """新規Register記録を作るか、入力とfingerprint一致後に保存済み記録を返す。"""

    inputs = [source.input for source in sources]
    if path.is_file():
        record = load_model(path, RegistrationRecord)
        if record.inputs != inputs or record.fingerprint != fingerprint:
            raise InputError(
                "resume inputs or settings do not match the saved registration"
            )
        return record
    if resuming:
        raise InputError("registration to resume does not exist")
    now = datetime.now(UTC)
    record = RegistrationRecord(
        registration_id=registration_id,
        status="processing",
        source_id=source_id,
        inputs=inputs,
        fingerprint=fingerprint,
        collection=config.qdrant_collection or "",
        embedding_model=config.openai_embedding_model or "",
        created_at=now,
        updated_at=now,
    )
    write_model(path, record)
    return record


def _validate_source_id(value: str) -> None:
    """source-idをWindowsを含む安全な単一path要素へ限定する。"""

    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or value[-1] in {" ", "."}
        or any(ord(character) < 32 for character in value)
        or value.split(".", 1)[0].upper() in _RESERVED_NAMES
    ):
        raise InputError("source-id must be a safe single path component")


def _single_top_name(paths: list[Path]) -> str:
    """単一fileまたはdirectoryの成果物最上位名を返す。"""

    if len(paths) != 1:
        raise InputError("source-id is required for multiple paths")
    path = paths[0]
    return path.stem if path.is_file() else path.name


def _processing_id(value: str | None) -> str:
    """新規UUIDv7を生成するか、Resume IDがUUIDv7であることを検査する。"""

    if value is None:
        return str(uuid7())
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise InputError("resume ID must be a canonical UUIDv7") from error
    if parsed.version != 7 or str(parsed) != value.casefold():
        raise InputError("resume ID must be a canonical UUIDv7")
    return value
