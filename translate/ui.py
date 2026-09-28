"""Translate、Review、Registerを操作するStreamlit UI。"""

from __future__ import annotations

import hashlib
import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import streamlit as st
from pydantic import BaseModel, ConfigDict
from uuid_utils import uuid7

from translate.artifact_store import (
    ArtifactError,
    ProcessingInUseError,
    atomic_write_bytes,
    load_model,
    sha256_file,
)
from translate.common.config import ConfigError, load_config
from translate.models.artifacts import (
    ArtifactFile,
    LLMCallArtifact,
    RegistrationRecord,
    ReviewRecord,
    TaskName,
    TranslationRecord,
)
from translate.pipeline import InputError
from translate.pipeline.register import register_paths
from translate.pipeline.review import review_pdfs
from translate.pipeline.translate import translate_pdf

if TYPE_CHECKING:
    from collections.abc import Callable

    from streamlit.runtime.uploaded_file_manager import UploadedFile

ProcessingKind = Literal["translate", "review", "register"]
ProcessingRecord = TranslationRecord | ReviewRecord | RegistrationRecord

_REGISTER_SUFFIXES = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class HistoryEntry(BaseModel):
    """処理履歴の有効な記録または読込失敗を保持する。"""

    model_config = ConfigDict(extra="ignore")

    kind: ProcessingKind
    record_path: Path
    updated_at: datetime
    record: ProcessingRecord | None = None
    error: str | None = None

    @property
    def processing_id(self) -> str | None:
        """有効な最上位記録から処理IDを返す。"""

        if isinstance(self.record, TranslationRecord):
            return self.record.translation_id
        if isinstance(self.record, ReviewRecord):
            return self.record.review_id
        if isinstance(self.record, RegistrationRecord):
            return self.record.registration_id
        return None


class WorkerRegistry:
    """Streamlit process内で単一workerと処理IDのFutureを管理する。"""

    def __init__(self) -> None:
        """ローカルLLMを並列呼出ししない単一workerを作る。"""

        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui")
        self._futures: dict[str, Future[object]] = {}
        self._lock = Lock()

    def submit(self, processing_id: str, operation: Callable[[], object]) -> bool:
        """同じ処理IDが未完了でない場合だけworkerへ登録する。"""

        with self._lock:
            existing = self._futures.get(processing_id)
            if existing is not None and not existing.done():
                return False
            self._futures[processing_id] = self._executor.submit(operation)
            return True

    def future(self, processing_id: str) -> Future[object] | None:
        """処理IDに対応するFutureをthread-safeに取得する。"""

        with self._lock:
            return self._futures.get(processing_id)

    def active(self, processing_id: str) -> bool:
        """処理IDのFutureが待機中または実行中かを返す。"""

        future = self.future(processing_id)
        return future is not None and not future.done()


@st.cache_resource(show_spinner=False)
def worker_registry() -> WorkerRegistry:
    """Streamlitの再読込み間で共有するworker登録表を返す。"""

    return WorkerRegistry()


def _execute_translate(source: Path, backend: str, processing_id: str) -> object:
    """最新設定を読み、UI指定IDでTranslate Pipelineを実行する。"""

    return translate_pdf(
        source,
        load_config(),
        backend=backend,
        processing_id=processing_id,
    )


def _execute_review(source: Path, translation: Path, processing_id: str) -> object:
    """最新設定を読み、UI指定IDでReview Pipelineを実行する。"""

    return review_pdfs(
        source,
        translation,
        load_config(),
        processing_id=processing_id,
    )


def _execute_register(
    paths: list[Path], source_id: str | None, processing_id: str
) -> object:
    """最新設定を読み、UI指定IDでRegister Pipelineを実行する。"""

    return register_paths(
        paths,
        load_config(),
        source_id=source_id,
        processing_id=processing_id,
    )


def _resume_translate(source: Path, backend: str, processing_id: str) -> object:
    """保存済みTranslate入力とIDでPipelineをResumeする。"""

    return translate_pdf(
        source,
        load_config(),
        backend=backend,
        resume_id=processing_id,
    )


def _resume_review(source: Path, translation: Path, processing_id: str) -> object:
    """保存済みReview入力とIDでPipelineをResumeする。"""

    return review_pdfs(
        source,
        translation,
        load_config(),
        resume_id=processing_id,
    )


def _resume_register(
    paths: list[Path], source_id: str | None, processing_id: str
) -> object:
    """保存済みRegister入力とIDでPipelineをResumeする。"""

    return register_paths(
        paths,
        load_config(),
        source_id=source_id,
        resume_id=processing_id,
    )


def _safe_upload_name(name: str, suffixes: set[str]) -> str:
    """upload名を安全な単一basenameと対応拡張子に限定する。"""

    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise InputError("upload name must be a safe file basename")
    if Path(name).suffix.casefold() not in suffixes:
        raise InputError("uploaded file extension is not supported")
    return name


def _stage_uploads(
    processing_id: str,
    uploads: list[tuple[UploadedFile, Path]],
    *,
    work_root: Path | None = None,
) -> list[Path]:
    """upload群を一時directoryで完成させてから原子的に公開する。"""

    root = (work_root or Path.cwd() / ".translate-ui").resolve()
    destination = root / processing_id
    if destination.exists():
        raise InputError("staged inputs already exist for processing ID")
    if any(path.is_absolute() or ".." in path.parts for _, path in uploads):
        raise InputError("staged upload path must be relative")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{processing_id}.{uuid4().hex}.tmp"
    temporary.mkdir()
    staged: list[Path] = []
    try:
        for uploaded, relative_path in uploads:
            target = temporary / relative_path
            atomic_write_bytes(target, uploaded.getvalue())
            staged.append(target)
        temporary.replace(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return [destination / path.relative_to(temporary) for path in staged]


def _stage_translate(upload: UploadedFile, processing_id: str) -> Path:
    """Translate用PDFを原のbasenameで保存する。"""

    name = _safe_upload_name(upload.name, {".pdf"})
    return _stage_uploads(processing_id, [(upload, Path("translate") / name)])[0]


def _stage_review(
    source: UploadedFile, translation: UploadedFile, processing_id: str
) -> tuple[Path, Path]:
    """Reviewの原文PDFと訳文PDFをrole別directoryへ保存する。"""

    source_name = _safe_upload_name(source.name, {".pdf"})
    translation_name = _safe_upload_name(translation.name, {".pdf"})
    staged = _stage_uploads(
        processing_id,
        [
            (source, Path("review/source") / source_name),
            (translation, Path("review/translation") / translation_name),
        ],
    )
    return staged[0], staged[1]


def _stage_register(uploads: list[UploadedFile], processing_id: str) -> list[Path]:
    """Register入力をupload順のdirectoryと原のbasenameで保存する。"""

    if len(uploads) > 100:
        raise InputError("at most 100 registration files can be uploaded")
    names = [_safe_upload_name(upload.name, _REGISTER_SUFFIXES) for upload in uploads]
    if len(names) != len(set(names)):
        raise InputError("registration uploads contain duplicate basenames")
    values = [
        (upload, Path("register") / f"{index:04d}" / name)
        for index, (upload, name) in enumerate(zip(uploads, names, strict=True), 1)
    ]
    return _stage_uploads(processing_id, values)


def _start_translate(
    upload: UploadedFile, backend: str, registry: WorkerRegistry
) -> str:
    """Translate入力を保存し、background workerへ登録する。"""

    processing_id = str(uuid7())
    source = _stage_translate(upload, processing_id)
    registry.submit(
        processing_id,
        partial(_execute_translate, source, backend, processing_id),
    )
    return processing_id


def _start_review(
    source_upload: UploadedFile,
    translation_upload: UploadedFile,
    registry: WorkerRegistry,
) -> str:
    """Review二入力を保存し、background workerへ登録する。"""

    processing_id = str(uuid7())
    source, translation = _stage_review(
        source_upload, translation_upload, processing_id
    )
    registry.submit(
        processing_id,
        partial(_execute_review, source, translation, processing_id),
    )
    return processing_id


def _start_register(
    uploads: list[UploadedFile],
    source_id: str | None,
    registry: WorkerRegistry,
) -> str:
    """Register入力を保存し、background workerへ登録する。"""

    if not uploads:
        raise InputError("at least one registration file is required")
    if len(uploads) > 1 and not source_id:
        raise InputError("source_id is required for multiple registration files")
    processing_id = str(uuid7())
    paths = _stage_register(uploads, processing_id)
    registry.submit(
        processing_id,
        partial(_execute_register, paths, source_id or None, processing_id),
    )
    return processing_id


def _history_entries(outputs: Path | None = None) -> list[HistoryEntry]:
    """outputs直下の新Schema処理記録を新しい順に100件返す。"""

    root = (outputs or Path.cwd() / "outputs").resolve()
    definitions: tuple[tuple[str, ProcessingKind, type[ProcessingRecord]], ...] = (
        ("translation.json", "translate", TranslationRecord),
        ("review.json", "review", ReviewRecord),
        ("registration.json", "register", RegistrationRecord),
    )
    entries: list[HistoryEntry] = []
    for filename, kind, model_type in definitions:
        for path in root.glob(f"*/*/{filename}"):
            try:
                record = load_model(path, model_type)
                entries.append(
                    HistoryEntry(
                        kind=kind,
                        record_path=path,
                        record=record,
                        updated_at=record.updated_at,
                    )
                )
            except ArtifactError:
                try:
                    modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                except OSError:
                    modified = datetime.min.replace(tzinfo=UTC)
                entries.append(
                    HistoryEntry(
                        kind=kind,
                        record_path=path,
                        updated_at=modified,
                        error="処理記録を読み込めません。",
                    )
                )
    return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)[:100]


def _entry_by_id(processing_id: str) -> HistoryEntry | None:
    """最新の履歴列挙から指定処理IDを探す。"""

    return next(
        (entry for entry in _history_entries() if entry.processing_id == processing_id),
        None,
    )


def _entry_label(entry: HistoryEntry) -> str:
    """処理履歴の選択欄に種類、入力、状態とIDを表示する。"""

    record = entry.record
    if isinstance(record, TranslationRecord):
        source = record.source.logical_path
    elif isinstance(record, ReviewRecord):
        source = record.translation.logical_path
    elif isinstance(record, RegistrationRecord):
        source = record.source_id or record.inputs[0].logical_path
    else:
        source = entry.record_path.parent.name
    status = record.status if record is not None else "読込不可"
    return f"{entry.kind} | {source} | {status} | {entry.processing_id or '-'}"


def _selected_processing_id() -> str | None:
    """URL query parameterから選択中の処理IDを取得する。"""

    value = st.query_params.get("processing")
    return value if isinstance(value, str) and value else None


def _select_processing(processing_id: str) -> None:
    """選択処理IDをURLへ保存し、全体を再読込みする。"""

    st.query_params["processing"] = processing_id
    st.rerun()


def _render_translate_form(registry: WorkerRegistry) -> None:
    """Translateのuploadとbackend選択を表示する。"""

    upload = st.file_uploader("英語PDF", type=["pdf"], key="translate-source")
    backend = st.selectbox("翻訳backend", ["llm", "libretranslate"])
    submitted = st.button(
        "翻訳を開始",
        disabled=upload is None,
        type="primary",
        key="start-translate",
    )
    if submitted and upload is not None:
        try:
            _select_processing(_start_translate(upload, backend, registry))
        except (InputError, OSError) as error:
            st.error(str(error))


def _render_review_form(registry: WorkerRegistry) -> None:
    """Reviewの英語原文PDFと日本語訳文PDF入力を表示する。"""

    source = st.file_uploader("英語原文PDF", type=["pdf"], key="review-source")
    translation = st.file_uploader(
        "日本語訳文PDF", type=["pdf"], key="review-translation"
    )
    submitted = st.button(
        "レビューを開始",
        disabled=source is None or translation is None,
        type="primary",
        key="start-review",
    )
    if submitted and source is not None and translation is not None:
        try:
            _select_processing(_start_review(source, translation, registry))
        except (InputError, OSError) as error:
            st.error(str(error))


def _render_register_form(registry: WorkerRegistry) -> None:
    """Registerの複数fileとsource_id入力を表示する。"""

    uploads = st.file_uploader(
        "参照資料",
        type=["pdf", "docx", "pptx", "md", "markdown", "txt"],
        accept_multiple_files=True,
        key="register-sources",
    )
    source_id = st.text_input("source_id")
    needs_source_id = len(uploads) > 1 and not source_id.strip()
    submitted = st.button(
        "登録を開始",
        disabled=not uploads or needs_source_id or len(uploads) > 100,
        type="primary",
        key="start-register",
    )
    if needs_source_id:
        st.caption("複数fileの登録ではsource_idが必要です。")
    if len(uploads) > 100:
        st.caption("一度に登録できるfileは100件までです。")
    if submitted:
        try:
            _select_processing(
                _start_register(uploads, source_id.strip() or None, registry)
            )
        except (InputError, OSError) as error:
            st.error(str(error))


def _render_history_selector(entries: list[HistoryEntry]) -> str | None:
    """履歴選択と読込不可記録を表示し、選択IDを返す。"""

    valid_entries = [entry for entry in entries if entry.processing_id is not None]
    invalid_entries = [entry for entry in entries if entry.error is not None]
    selected_id = _selected_processing_id()
    ids = [entry.processing_id for entry in valid_entries]
    current_index = ids.index(selected_id) if selected_id in ids else None
    selected = st.selectbox(
        "処理履歴",
        options=ids,
        index=current_index,
        format_func=lambda value: _entry_label(
            next(entry for entry in valid_entries if entry.processing_id == value)
        ),
        placeholder="処理を選択してください",
    )
    if selected is not None and selected != selected_id:
        st.query_params["processing"] = selected
        selected_id = selected
    for entry in invalid_entries:
        st.warning(f"{entry.error} {entry.record_path}")
    return selected_id


def _render_future_state(processing_id: str, registry: WorkerRegistry) -> None:
    """Artifact公開前の待機・準備状態またはworker失敗を表示する。"""

    future = registry.future(processing_id)
    st.code(processing_id)
    if future is None:
        st.info("処理記録が見つかりません。")
    elif not future.running() and not future.done():
        st.info("待機中")
    elif not future.done():
        st.info("準備中")
    else:
        _render_future_error(future)


def _render_future_error(future: Future[object]) -> None:
    """完了済みFutureの例外を回収し、利用者向けに表示する。"""

    try:
        future.result()
    except (ConfigError, InputError, ProcessingInUseError) as error:
        st.error(str(error))
    except Exception as error:  # noqa: BLE001 - 予期外失敗は型名だけを表示する。
        st.error(f"処理に失敗しました: {type(error).__name__}")


def _live_call_counts(root: Path, task: TaskName) -> tuple[int, int, int]:
    """実行中LLM TaskのCall Artifactから観測数、完了数、失敗数を返す。"""

    directories = {
        TaskName.STRUCTURE: root / "preprocess/structure/calls",
        TaskName.TRANSLATE: root / "translation/translate/calls",
        TaskName.REVIEW: root / "review/review/calls",
    }
    directory = directories.get(task)
    if directory is None:
        return 0, 0, 0
    calls: list[LLMCallArtifact] = []
    for path in directory.glob("*/call.json"):
        try:
            calls.append(load_model(path, LLMCallArtifact))
        except ArtifactError:
            continue
    completed = sum(call.status in {"succeeded", "partial", "split"} for call in calls)
    failed = sum(call.status == "failed" for call in calls)
    return len(calls), completed, failed


def _render_task_progress(
    entry: HistoryEntry, record: TranslationRecord | ReviewRecord
) -> None:
    """Task状態とLLM Call数を虚偽の百分率なしで表示する。"""

    completed = sum(task.status in {"succeeded", "skipped"} for task in record.tasks)
    active = next(
        (task.task.value for task in record.tasks if task.status == "processing"),
        "-",
    )
    st.write(f"完了Task: {completed} / 開始済み {len(record.tasks)}")
    st.write(f"現在のTask: {active}")
    for progress in record.llm_progress:
        st.write(
            f"{progress.task}: {progress.completed_calls} / "
            f"{progress.planned_calls} calls "
            f"(再利用 {progress.reused_calls}, 失敗 {progress.failed_calls})"
        )
    active_task = next(
        (task.task for task in record.tasks if task.status == "processing"), None
    )
    if active_task in {TaskName.STRUCTURE, TaskName.TRANSLATE, TaskName.REVIEW}:
        observed, live_completed, failed = _live_call_counts(
            entry.record_path.parent,
            active_task,
        )
        st.write(
            f"{active_task.value} 実行中: {live_completed} / "
            f"観測済み {observed} calls (失敗 {failed})"
        )


def _valid_artifact(root: Path, artifact: ArtifactFile) -> Path | None:
    """Artifactが処理directory内でsizeとhashに一致する場合だけpathを返す。"""

    resolved_root = root.resolve()
    path = (root / artifact.relative_path).resolve()
    if (
        not path.is_relative_to(resolved_root)
        or not path.is_file()
        or path.stat().st_size != artifact.size_bytes
        or sha256_file(path) != artifact.sha256
    ):
        return None
    return path


def _render_translation_outputs(entry: HistoryEntry, record: TranslationRecord) -> None:
    """hash検証済みMarkdownとDOCXのpreview・downloadを表示する。"""

    for artifact in record.outputs:
        path = _valid_artifact(entry.record_path.parent, artifact)
        if path is None:
            st.error("成果物が欠落または変更されています。")
            continue
        if path.suffix.casefold() == ".md":
            value = path.read_bytes()
            with st.expander("Markdown preview"):
                st.markdown(value.decode("utf-8"), unsafe_allow_html=False)
            st.download_button(
                "Markdownをdownload",
                value,
                file_name=path.name,
                mime="text/markdown",
            )
        elif path.suffix.casefold() == ".docx":
            st.download_button(
                "DOCXをdownload",
                path.read_bytes(),
                file_name=path.name,
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )


def _render_review_outputs(entry: HistoryEntry, record: ReviewRecord) -> None:
    """hash検証済みReview reportのpreviewとdownloadを表示する。"""

    for artifact in record.outputs:
        path = _valid_artifact(entry.record_path.parent, artifact)
        if path is None:
            st.error("成果物が欠落または変更されています。")
            continue
        value = path.read_bytes()
        st.markdown(value.decode("utf-8"), unsafe_allow_html=False)
        st.download_button(
            "Review reportをdownload",
            value,
            file_name=path.name,
            mime="text/markdown",
        )


def _render_registration_result(
    entry: HistoryEntry, record: RegistrationRecord
) -> None:
    """Registerのcollection、各資料状態と処理記録downloadを表示する。"""

    if record.result is not None:
        st.write(f"collection: {record.result.collection}")
        st.write(f"Embedding model: {record.result.embedding_model}")
        st.write(f"Point合計: {record.result.total_points}")
        st.dataframe(
            [source.model_dump(mode="json") for source in record.result.sources],
            use_container_width=True,
        )
    st.download_button(
        "Register記録をdownload",
        entry.record_path.read_bytes(),
        file_name="registration.json",
        mime="application/json",
    )


def _stored_resume_paths(entry: HistoryEntry) -> list[Path] | None:
    """UI保存済み入力をrole順に取得し、最上位記録のhashと比較する。"""

    processing_id = entry.processing_id
    record = entry.record
    if processing_id is None or record is None:
        return None
    root = Path.cwd() / ".translate-ui" / processing_id
    if isinstance(record, TranslationRecord):
        paths = list((root / "translate").glob("*"))
        expected = [record.source]
    elif isinstance(record, ReviewRecord):
        paths = [
            *list((root / "review/source").glob("*")),
            *list((root / "review/translation").glob("*")),
        ]
        expected = [record.source, record.translation]
    else:
        paths = sorted((root / "register").glob("*/*"), key=lambda path: path.name)
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


def _resume_entry(
    entry: HistoryEntry, paths: list[Path], registry: WorkerRegistry
) -> bool:
    """検証済み入力を使って処理種類別のResumeを登録する。"""

    processing_id = entry.processing_id
    record = entry.record
    if processing_id is None or record is None:
        return False
    if isinstance(record, TranslationRecord):
        operation = partial(_resume_translate, paths[0], record.backend, processing_id)
    elif isinstance(record, ReviewRecord):
        operation = partial(_resume_review, paths[0], paths[1], processing_id)
    else:
        operation = partial(_resume_register, paths, record.source_id, processing_id)
    return registry.submit(processing_id, operation)


def _matches_input(upload: UploadedFile, logical_path: str, sha256: str) -> bool:
    """uploadのbasenameとSHA-256が保存済み入力に一致するかを返す。"""

    return (
        upload.name == logical_path
        and hashlib.sha256(upload.getvalue()).hexdigest() == sha256
    )


def _stage_resume_uploads(
    entry: HistoryEntry, uploads: list[UploadedFile]
) -> list[Path]:
    """CLI処理の再uploadを保存済み入力情報と比較して保存する。"""

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
    )


def _render_resume_uploads(entry: HistoryEntry) -> list[Path] | None:
    """保存済み入力がない処理に種類別の再upload formを表示する。"""

    record = entry.record
    processing_id = entry.processing_id
    if record is None or processing_id is None:
        return None
    if isinstance(record, RegistrationRecord) and any(
        "/" in item.logical_path for item in record.inputs
    ):
        st.info("directory入力のRegisterはCLIからResumeしてください。")
        return None
    if isinstance(record, TranslationRecord):
        upload = st.file_uploader(
            "Resume用の英語PDF",
            type=["pdf"],
            key=f"resume-translate-{processing_id}",
        )
        uploads = [upload] if upload is not None else []
    elif isinstance(record, ReviewRecord):
        source = st.file_uploader(
            "Resume用の英語原文PDF",
            type=["pdf"],
            key=f"resume-review-source-{processing_id}",
        )
        translation = st.file_uploader(
            "Resume用の日本語訳文PDF",
            type=["pdf"],
            key=f"resume-review-translation-{processing_id}",
        )
        uploads = (
            [source, translation]
            if source is not None and translation is not None
            else []
        )
    else:
        uploads = st.file_uploader(
            "Resume用の参照資料",
            type=["pdf", "docx", "pptx", "md", "markdown", "txt"],
            accept_multiple_files=True,
            key=f"resume-register-{processing_id}",
        )
    confirmed = st.checkbox(
        "完了済みTaskとLLM Callを再利用し、未完了箇所から再開する",
        key=f"resume-upload-confirm-{processing_id}",
    )
    submitted = st.button(
        "入力を検証してResume",
        disabled=not uploads or not confirmed,
        key=f"resume-upload-submit-{processing_id}",
    )
    if not submitted:
        return None
    try:
        return _stage_resume_uploads(entry, uploads)
    except (InputError, OSError) as error:
        st.error(str(error))
        return None


def _render_resume(entry: HistoryEntry, registry: WorkerRegistry) -> None:
    """終端失敗またはworker不明のprocessing記録にResume確認を表示する。"""

    record = entry.record
    processing_id = entry.processing_id
    if (
        record is None
        or processing_id is None
        or record.status == "succeeded"
        or registry.active(processing_id)
    ):
        return
    paths = _stored_resume_paths(entry)
    if paths is None:
        st.info("Resume用の保存済み入力がありません。同じ入力を再uploadしてください。")
        paths = _render_resume_uploads(entry)
        if paths is not None and _resume_entry(entry, paths, registry):
            st.rerun()
        return
    confirmed = st.checkbox(
        "完了済みTaskとLLM Callを再利用し、未完了箇所から再開する",
        key=f"resume-confirm-{processing_id}",
    )
    submitted = st.button(
        "Resume",
        disabled=not confirmed,
        key=f"resume-submit-{processing_id}",
    )
    if submitted and confirmed and _resume_entry(entry, paths, registry):
        st.rerun()


def _render_record(entry: HistoryEntry, registry: WorkerRegistry) -> None:
    """最上位記録の状態、進捗、エラー、成果物とResumeを表示する。"""

    record = entry.record
    if record is None:
        st.error(entry.error or "処理記録を読み込めません。")
        return
    processing_id = entry.processing_id or "-"
    st.code(processing_id)
    st.write(f"状態: {record.status}")
    st.write(f"更新時刻: {record.updated_at.isoformat()}")
    if isinstance(record, (TranslationRecord, ReviewRecord)):
        _render_task_progress(entry, record)
    elif record.result is not None:
        st.write(f"Register進捗: {len(record.result.sources)} / {len(record.inputs)}")
    if record.error is not None:
        st.error(
            f"{record.error.message} "
            f"({record.error.cause_type or 'unknown'}, retryable={record.error.retryable})"
        )
    future = registry.future(processing_id)
    if future is not None and future.done():
        _render_future_error(future)
    if record.status == "succeeded":
        if isinstance(record, TranslationRecord):
            _render_translation_outputs(entry, record)
        elif isinstance(record, ReviewRecord):
            _render_review_outputs(entry, record)
        else:
            _render_registration_result(entry, record)
    _render_resume(entry, registry)


def _render_selected(processing_id: str, registry: WorkerRegistry) -> None:
    """選択処理をArtifactから再読込みして表示する。"""

    entry = _entry_by_id(processing_id)
    if entry is None:
        _render_future_state(processing_id, registry)
        return
    _render_record(entry, registry)


def _render_processing_panel(registry: WorkerRegistry) -> None:
    """処理履歴と選択中の進捗・成果物領域を表示する。"""

    st.header("🕒 処理履歴")
    entries = _history_entries()
    processing_id = _render_history_selector(entries)
    if processing_id is None:
        return
    current = next(
        (entry for entry in entries if entry.processing_id == processing_id), None
    )
    processing = (
        current is not None
        and current.record is not None
        and (current.record.status == "processing")
    )
    active = processing or registry.active(processing_id)

    @st.fragment(run_every="1s" if active else None)
    def render_progress() -> None:
        """実行中だけ1秒ごとにArtifactを再読込みする。"""

        _render_selected(processing_id, registry)
        refreshed = _entry_by_id(processing_id)
        if (
            active
            and refreshed is not None
            and refreshed.record is not None
            and refreshed.record.status in _TERMINAL_STATUSES
        ):
            st.rerun()

    render_progress()


def main() -> None:
    """Streamlitの3操作と共通処理履歴を表示する。"""

    st.set_page_config(page_title="Translate", page_icon="🌐", layout="wide")
    st.title("🌐 Translate")
    st.caption("英語文書の日本語翻訳、比較Review、参照資料登録")
    registry = worker_registry()
    translate_tab, review_tab, register_tab = st.tabs(
        ["Translate", "Review", "Register"]
    )
    with translate_tab:
        _render_translate_form(registry)
    with review_tab:
        _render_review_form(registry)
    with register_tab:
        _render_register_form(registry)
    _render_processing_panel(registry)
