"""Streamlit UI inputs module."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

from streamlit.runtime.uploaded_file_manager import UploadedFile

from translate.adapters.artifact_store import (
    replace_path,
    sha256_file,
)
from translate.models.artifacts import (
    ReviewRecord,
    TranslationRecord,
)
from translate.models.upgrade import (
    UpgradeRecord,
)
from translate.pipeline import InputError

from .history import HistoryEntry
from .types import _REGISTER_SUFFIXES


def _stage_translate(upload: UploadedFile, processing_id: str) -> Path:
    """Translate用PDFを原のbasenameで保存する。

    Args:
        upload (UploadedFile): 保存または照合するUpload File。
        processing_id (str): 新規処理またはResume対象の処理ID。

    Returns:
        Path: Translate用PDFを原のbasenameで保存する。
    """

    name = _safe_upload_name(upload.name, {".pdf"})
    return _stage_uploads(
        processing_id,
        [(upload, Path("translate") / name)],
        output_name=Path(name).stem,
    )[0]


def _stage_uploads(
    processing_id: str,
    uploads: list[tuple[UploadedFile, Path]],
    *,
    work_root: Path | None = None,
    output_name: str | None = None,
) -> list[Path]:
    """upload群を一時directoryで完成させてから原子的に公開する。

    Args:
        processing_id (str): 新規処理またはResume対象の処理ID。
        uploads (list[tuple[UploadedFile, Path]]): 保存または照合するUpload File一覧。
        work_root (Path | None): Uploadの一時保存Root Directory。

    Returns:
        list[Path]: upload群を一時directoryで完成させてから原子的に公開する。

    Raises:
        InputError: `staged inputs already exist for processing ID`、`staged upload path must
            be relative`のいずれかと判定した場合。
    """

    root = (work_root or Path.cwd() / "outputs").resolve()
    processing_directory = (
        root / output_name / processing_id if output_name else root / processing_id
    )
    destination = (
        processing_directory / "inputs" if output_name else processing_directory
    )
    if destination.exists():
        raise InputError("staged inputs already exist for processing ID")
    if any(path.is_absolute() or ".." in path.parts for _, path in uploads):
        raise InputError("staged upload path must be relative")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{processing_id}.{uuid4().hex}.tmp"
    temporary.mkdir()
    staged: list[Path] = []
    try:
        for uploaded, relative_path in uploads:
            target = temporary / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(uploaded.getvalue())
            staged.append(target)
        replace_path(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return [destination / path.relative_to(temporary) for path in staged]


def _stage_review(
    source: UploadedFile, translation: UploadedFile, processing_id: str
) -> tuple[Path, Path]:
    """Reviewの原文PDFと訳文PDFをrole別directoryへ保存する。

    Args:
        source (UploadedFile): 変換または検証対象の入力Source。
        translation (UploadedFile): Review対象の日本語訳。
        processing_id (str): 新規処理またはResume対象の処理ID。

    Returns:
        tuple[Path, Path]: Reviewの原文PDFと訳文PDFをrole別directoryへ保存する。
    """

    source_name = _safe_upload_name(source.name, {".pdf"})
    translation_name = _safe_upload_name(translation.name, {".pdf"})
    staged = _stage_uploads(
        processing_id,
        [
            (source, Path("review/source") / source_name),
            (translation, Path("review/translation") / translation_name),
        ],
        output_name=Path(translation_name).stem,
    )
    return staged[0], staged[1]


def _safe_upload_name(name: str, suffixes: set[str]) -> str:
    """upload名を安全な単一basenameと対応拡張子に限定する。

    Args:
        name (str): 安全なUpload File名へ変換する元の名前。
        suffixes (set[str]): 許可する小文字のFile拡張子集合。

    Returns:
        str: upload名を安全な単一basenameと対応拡張子に限定する。

    Raises:
        InputError: `upload name must be a safe file basename`、`uploaded file extension is
            not supported`のいずれかと判定した場合。
    """

    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(character) < 32 or character in '<>:"|?*' for character in name)
        or name.endswith((" ", "."))
        or Path(name).is_reserved()
    ):
        raise InputError("upload name must be a safe file basename")
    if Path(name).suffix.casefold() not in suffixes:
        raise InputError("uploaded file extension is not supported")
    return name


def _stage_register(uploads: list[UploadedFile], processing_id: str) -> list[Path]:
    """Register入力を保存し、ディレクトリ選択時は相対pathを保持する。

    Args:
        uploads (list[UploadedFile]): 保存または照合するUpload File一覧。
        processing_id (str): 新規処理またはResume対象の処理ID。

    Returns:
        list[Path]: Register入力を保存し、ディレクトリ選択時は相対pathを保持する。

    Raises:
        InputError: `at most 100 registration files can be uploaded`、`registration uploads
            contain duplicate basenames`のいずれかと判定した場合。
    """

    if len(uploads) > 100:
        raise InputError("at most 100 registration files can be uploaded")
    names = [upload.name for upload in uploads]
    if len(names) != len({name.casefold() for name in names}):
        raise InputError("registration uploads contain duplicate basenames or paths")
    directory_upload = any("/" in name for name in names)
    values = []
    for index, upload in enumerate(uploads, 1):
        parts = upload.name.split("/")
        if directory_upload and len(parts) < 2:
            raise InputError("directory and individual file uploads cannot be mixed")
        for part in parts[:-1]:
            _safe_upload_name(part, {Path(part).suffix.casefold()})
        _safe_upload_name(parts[-1], _REGISTER_SUFFIXES)
        relative = Path("register") / (
            Path(*parts) if directory_upload else Path(f"{index:04d}") / parts[0]
        )
        values.append((upload, relative))
    output_name = (
        Path(uploads[0].name).parts[0]
        if directory_upload
        else (Path(uploads[0].name).stem if len(uploads) == 1 else "register")
    )
    staged = _stage_uploads(processing_id, values, output_name=output_name)
    if directory_upload:
        # Pipelineには元のroot directoryを渡し、同名の子fileも相対pathで区別する。
        root = (
            Path.cwd() / "outputs" / output_name / processing_id / "inputs" / "register"
        )
        return [
            root / name for name in sorted({value.split("/")[0] for value in names})
        ]
    return staged


def _stored_resume_paths(entry: HistoryEntry) -> list[Path] | None:
    """UI保存済み入力をrole順に取得し、最上位記録のhashと比較する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。

    Returns:
        list[Path] | None: UI保存済み入力をrole順に取得し、最上位記録のhashと比較する。
    """

    processing_id = entry.processing_id
    record = entry.record
    if processing_id is None or record is None:
        return None
    root = entry.record_path.parent
    if isinstance(record, TranslationRecord):
        paths = list((root / "inputs/translate").glob("*"))
        expected = [record.source]
    elif isinstance(record, ReviewRecord):
        paths = [
            *list((root / "inputs/review/source").glob("*")),
            *list((root / "inputs/review/translation").glob("*")),
        ]
        expected = [record.source, record.translation]
    elif isinstance(record, UpgradeRecord):
        paths = [
            *list((root / "inputs/upgrade/source-v1").glob("*")),
            *list((root / "inputs/upgrade/source-v2").glob("*")),
            *list((root / "inputs/upgrade/translation-v1").glob("*")),
        ]
        expected = [record.source_v1, record.source_v2, record.translation_v1]
    else:
        if any("/" in item.logical_path for item in record.inputs):
            register_root = root / "inputs/register"
            if any(
                not (path := register_root / item.logical_path).is_file()
                or not path.resolve().is_relative_to(register_root.resolve())
                or sha256_file(path) != item.sha256
                for item in record.inputs
            ):
                return None
            return [
                register_root / name
                for name in sorted(
                    {item.logical_path.split("/")[0] for item in record.inputs}
                )
            ]
        paths = sorted(
            (root / "inputs/register").glob("*/*"), key=lambda path: path.name
        )
        expected = sorted(record.inputs, key=lambda item: item.logical_path)
    if len(paths) != len(expected) or any(not path.is_file() for path in paths):
        return None
    actual = sorted(
        ((path.name, sha256_file(path)) for path in paths), key=lambda item: item[0]
    )
    wanted = sorted(
        ((item.logical_path, item.sha256) for item in expected),
        key=lambda item: item[0],
    )
    return paths if actual == wanted else None


def _stage_resume_uploads(
    entry: HistoryEntry, uploads: list[UploadedFile]
) -> list[Path]:
    """CLI処理の再uploadを保存済み入力情報と比較して保存する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。
        uploads (list[UploadedFile]): 保存または照合するUpload File一覧。

    Returns:
        list[Path]: CLI処理の再uploadを保存済み入力情報と比較して保存する。

    Raises:
        InputError: `processing record is unavailable`、`directory registration must be
            resumed from the CLI`、`resume uploads do not match the saved
            inputs`のいずれかと判定した場合。
    """

    record = entry.record
    processing_id = entry.processing_id
    if record is None or processing_id is None:
        raise InputError("processing record is unavailable")
    if isinstance(record, TranslationRecord):
        expected = [record.source]
        relative_paths = [Path("translate") / record.source.logical_path]
    elif isinstance(record, ReviewRecord):
        expected = [record.source, record.translation]
        relative_paths = [
            Path("review/source") / record.source.logical_path,
            Path("review/translation") / record.translation.logical_path,
        ]
    elif isinstance(record, UpgradeRecord):
        expected = [record.source_v1, record.source_v2, record.translation_v1]
        relative_paths = [
            Path("upgrade/source-v1") / record.source_v1.logical_path,
            Path("upgrade/source-v2") / record.source_v2.logical_path,
            Path("upgrade/translation-v1") / record.translation_v1.logical_path,
        ]
    else:
        if any("/" in item.logical_path for item in record.inputs):
            raise InputError("directory registration must be resumed from the CLI")
        expected = record.inputs
        relative_paths = [
            Path("register") / f"{index:04d}" / item.logical_path
            for index, item in enumerate(expected, 1)
        ]
    if len(uploads) != len(expected) or any(
        not _matches_input(upload, item.logical_path, item.sha256)
        for upload, item in zip(uploads, expected, strict=True)
    ):
        raise InputError("resume uploads do not match the saved inputs")
    return _stage_uploads(
        processing_id,
        list(zip(uploads, relative_paths, strict=True)),
        output_name=entry.record_path.parent.parent.name,
    )


def _stage_upgrade(
    source_v1: UploadedFile,
    source_v2: UploadedFile,
    translation_v1: UploadedFile,
    processing_id: str,
) -> tuple[Path, Path, Path]:
    """Upgrade三入力をrole別directoryへ保存する。

    Args:
        source_v1 (UploadedFile): 比較基準にする英文v1。
        source_v2 (UploadedFile): 変更を反映する英文v2。
        translation_v1 (UploadedFile): 比較基準にする日本語v1。
        processing_id (str): 新規処理またはResume対象の処理ID。

    Returns:
        tuple[Path, Path, Path]: Upgrade三入力をrole別directoryへ保存する。
    """

    values = [
        (
            source_v1,
            Path("upgrade/source-v1") / _safe_upload_name(source_v1.name, {".pdf"}),
        ),
        (
            source_v2,
            Path("upgrade/source-v2") / _safe_upload_name(source_v2.name, {".pdf"}),
        ),
        (
            translation_v1,
            Path("upgrade/translation-v1")
            / _safe_upload_name(translation_v1.name, {".pdf"}),
        ),
    ]
    staged = _stage_uploads(
        processing_id, values, output_name=Path(source_v2.name).stem
    )
    return staged[0], staged[1], staged[2]


def _matches_input(upload: UploadedFile, logical_path: str, sha256: str) -> bool:
    """uploadのbasenameとSHA-256が保存済み入力に一致するかを返す。

    Args:
        upload (UploadedFile): 保存または照合するUpload File。
        logical_path (str): 保存済み入力の論理Path。
        sha256 (str): 保存済み入力と照合するSHA-256 Hash。

    Returns:
        bool: uploadのbasenameとSHA-256が保存済み入力に一致するかを返す。
    """

    return (
        upload.name == logical_path
        and hashlib.sha256(upload.getvalue()).hexdigest() == sha256
    )
