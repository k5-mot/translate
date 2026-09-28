"""Translate、Review、Register、Upgradeを操作するStreamlit UI。"""

from __future__ import annotations

import difflib
import hashlib
import html
import re
import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Literal
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import streamlit as st
from pydantic import BaseModel, ConfigDict
from uuid_utils import uuid7

from translate.artifact_store import (
    ArtifactError,
    ProcessingInUseError,
    atomic_write_bytes,
    load_model,
    replace_path,
    sha256_file,
)
from translate.common.config import ConfigError, load_config
from translate.models.artifacts import (
    AlignmentResult,
    ArtifactFile,
    CheckResult,
    FixResult,
    LLMCallArtifact,
    RegistrationRecord,
    ReviewRecord,
    ReviewResult,
    TaskName,
    TranslationRecord,
)
from translate.models.document import (
    Document,
    TextLayer,
    TextUnit,
    iter_text_units,
    text_unit_index,
)
from translate.models.review import ReviewResponse
from translate.models.upgrade import UpgradePlan, UpgradeRecord
from translate.pipeline import InputError
from translate.pipeline.register import register_paths
from translate.pipeline.review import review_pdfs
from translate.pipeline.translate import translate_pdf
from translate.pipeline.upgrade import upgrade_pdfs
from translate.tasks.preprocess.structure import StructureResponse
from translate.tasks.review.check import targets_from_document
from translate.tasks.translation.translate import TranslationResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    from streamlit.runtime.uploaded_file_manager import UploadedFile

ProcessingKind = Literal["translate", "review", "register", "upgrade"]
ProcessingRecord = TranslationRecord | ReviewRecord | RegistrationRecord | UpgradeRecord
TaskStage = tuple[str, TaskName, str | None]

_REGISTER_SUFFIXES = {".pdf", ".docx", ".pptx", ".md", ".markdown", ".txt"}
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
_LOGO_PATH = Path(__file__).with_name("assets") / "translate-logo.svg"
_MARKDOWN_IMAGE_BLOCK = re.compile(
    r"(?m)^!\[(?P<caption>(?:\\.|[^\]])*)\]"
    r"\((?P<target>[^)]+)\)(?:\{[^\n]*\})?[ \t\r]*$"
)


def _task_stages(
    record: TranslationRecord | ReviewRecord | UpgradeRecord,
) -> tuple[TaskStage, ...]:
    """処理種類とbackendに対応する固定Task列を返す。"""

    common: tuple[TaskStage, ...] = (
        ("SPLIT", TaskName.SPLIT, None),
        ("DOCLING", TaskName.DOCLING, None),
        ("UNPACK", TaskName.UNPACK, None),
        ("MERGE", TaskName.MERGE, None),
        ("POSITION", TaskName.POSITION, None),
        ("NORMALIZE", TaskName.NORMALIZE, None),
        ("LOAD", TaskName.LOAD, None),
    )
    if isinstance(record, ReviewRecord):
        return (
            *common,
            ("ALIGN", TaskName.ALIGN, None),
            ("CHECK", TaskName.CHECK, "review/check/findings.json"),
            ("REVIEW", TaskName.REVIEW, None),
            ("REPORT", TaskName.REPORT, None),
        )
    translation_task = (
        TaskName.TRANSLATE if record.backend == "llm" else TaskName.TRANSLATE_LITE
    )
    translation_label = translation_task.value.replace("_", "-")
    review_and_publish: tuple[TaskStage, ...] = (
        (translation_label, translation_task, None),
        ("CHECK (初回)", TaskName.CHECK, "review/check/findings.json"),
        ("REVIEW", TaskName.REVIEW, None),
        ("FIX", TaskName.FIX, None),
        ("CHECK (最終)", TaskName.CHECK, "review/check/final-findings.json"),
        ("LINT", TaskName.LINT, None),
        ("COVER", TaskName.COVER, None),
        ("MARKDOWN", TaskName.MARKDOWN, None),
        ("DOCX", TaskName.DOCX, None),
    )
    if isinstance(record, UpgradeRecord):
        return (
            *common,
            ("STRUCTURE", TaskName.STRUCTURE, None),
            ("ALIGN", TaskName.ALIGN, None),
            ("DIFF", TaskName.DIFF, None),
            ("REUSE", TaskName.REUSE, None),
            *review_and_publish,
        )
    return (
        *common,
        ("STRUCTURE", TaskName.STRUCTURE, None),
        *review_and_publish,
    )


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
        if isinstance(self.record, UpgradeRecord):
            return self.record.upgrade_id
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


def _execute_upgrade(
    source_v1: Path,
    source_v2: Path,
    translation_v1: Path,
    backend: str,
    processing_id: str,
) -> object:
    """最新設定を読み、UI指定IDでUpgrade Pipelineを実行する。"""

    return upgrade_pdfs(
        source_v1,
        source_v2,
        translation_v1,
        load_config(),
        backend=backend,
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


def _resume_upgrade(
    source_v1: Path,
    source_v2: Path,
    translation_v1: Path,
    backend: str,
    processing_id: str,
) -> object:
    """保存済みUpgrade入力とIDでPipelineをResumeする。"""

    return upgrade_pdfs(
        source_v1,
        source_v2,
        translation_v1,
        load_config(),
        backend=backend,
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
        replace_path(temporary, destination)
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


def _stage_upgrade(
    source_v1: UploadedFile,
    source_v2: UploadedFile,
    translation_v1: UploadedFile,
    processing_id: str,
) -> tuple[Path, Path, Path]:
    """Upgrade三入力をrole別directoryへ保存する。"""

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
    staged = _stage_uploads(processing_id, values)
    return staged[0], staged[1], staged[2]


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


def _start_upgrade(
    source_v1: UploadedFile,
    source_v2: UploadedFile,
    translation_v1: UploadedFile,
    backend: str,
    registry: WorkerRegistry,
) -> str:
    """Upgrade三入力を保存し、background workerへ登録する。"""

    processing_id = str(uuid7())
    paths = _stage_upgrade(source_v1, source_v2, translation_v1, processing_id)
    registry.submit(
        processing_id,
        partial(_execute_upgrade, *paths, backend, processing_id),
    )
    return processing_id


def _history_entries(outputs: Path | None = None) -> list[HistoryEntry]:
    """outputs直下の新Schema処理記録を新しい順に100件返す。"""

    root = (outputs or Path.cwd() / "outputs").resolve()
    definitions: tuple[tuple[str, ProcessingKind, type[ProcessingRecord]], ...] = (
        ("translation.json", "translate", TranslationRecord),
        ("review.json", "review", ReviewRecord),
        ("registration.json", "register", RegistrationRecord),
        ("upgrade.json", "upgrade", UpgradeRecord),
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
    elif isinstance(record, UpgradeRecord):
        source = record.source_v2.logical_path
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


def _render_upgrade_form(registry: WorkerRegistry) -> None:
    """Upgradeの英文二版、日本語旧版およびbackend選択を表示する。"""

    source_v1 = st.file_uploader("英文v1 PDF", type=["pdf"], key="upgrade-source-v1")
    source_v2 = st.file_uploader("英文v2 PDF", type=["pdf"], key="upgrade-source-v2")
    translation_v1 = st.file_uploader(
        "日本語v1 PDF", type=["pdf"], key="upgrade-translation-v1"
    )
    backend = st.selectbox(
        "Upgrade翻訳backend",
        ["llm", "libretranslate"],
        key="upgrade-backend",
    )
    ready = all(value is not None for value in (source_v1, source_v2, translation_v1))
    submitted = st.button(
        "Upgradeを開始",
        disabled=not ready,
        type="primary",
        key="start-upgrade",
    )
    if (
        submitted
        and source_v1 is not None
        and source_v2 is not None
        and translation_v1 is not None
    ):
        try:
            _select_processing(
                _start_upgrade(
                    source_v1,
                    source_v2,
                    translation_v1,
                    backend,
                    registry,
                )
            )
        except (InputError, OSError) as error:
            st.error(str(error))


def _render_history_sidebar(entries: list[HistoryEntry]) -> str | None:
    """左sidebarの縦並び一覧から処理を選択し、選択IDを返す。"""

    valid_entries = [entry for entry in entries if entry.processing_id is not None]
    invalid_entries = [entry for entry in entries if entry.error is not None]
    selected_id = _selected_processing_id()
    with st.sidebar:
        st.subheader("処理履歴", icon=":material/history:")
        if not valid_entries and not invalid_entries:
            st.caption("処理履歴はありません。")
        for entry in valid_entries:
            processing_id = entry.processing_id
            if processing_id is not None and st.button(
                _entry_label(entry),
                key=f"history-{processing_id}",
                type="primary" if processing_id == selected_id else "tertiary",
                width="stretch",
            ):
                _select_processing(processing_id)
        for entry in invalid_entries:
            st.warning(f"{entry.error} {entry.record_path}")
    return selected_id


def _render_future_state(processing_id: str, registry: WorkerRegistry) -> None:
    """Artifact公開前の待機・準備状態またはworker失敗を表示する。"""

    future = registry.future(processing_id)
    st.progress(0.0, text="0 / ? Task — 準備 — preparing")
    if future is None:
        current = "処理記録の公開待ち"
    elif not future.running() and not future.done():
        current = "workerの開始待ち"
    elif not future.done():
        current = "Pipelineを準備中"
    else:
        current = "workerの結果を確認中"
    with st.expander("進捗詳細", expanded=False, icon=":material/analytics:"):
        st.write("更新時刻: -")
        st.caption("LLM進捗はまだありません。")
    st.caption(current)
    if future is None:
        st.info("処理記録が見つかりません。")
    elif future.done():
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

    calls = _llm_calls(root, task)
    completed = sum(call.status in {"succeeded", "partial", "split"} for call in calls)
    failed = sum(call.status == "failed" for call in calls)
    return len(calls), completed, failed


def _llm_call_directory(root: Path, task: TaskName) -> Path | None:
    """処理種類によるSTRUCTURE配置差を吸収してCall directoryを返す。"""

    candidates = {
        TaskName.STRUCTURE: [
            root / "preprocess/source-v2/structure/calls",
            root / "preprocess/structure/calls",
        ],
        TaskName.TRANSLATE: [root / "translation/translate/calls"],
        TaskName.REVIEW: [root / "review/review/calls"],
    }.get(task, [])
    return next((directory for directory in candidates if directory.is_dir()), None)


def _llm_calls(root: Path, task: TaskName) -> list[LLMCallArtifact]:
    """一階層のCall記録だけを読み、壊れた途中fileを無視する。"""

    directory = _llm_call_directory(root, task)
    if directory is None:
        return []
    calls: list[LLMCallArtifact] = []
    for path in directory.glob("*/call.json"):
        try:
            calls.append(load_model(path, LLMCallArtifact))
        except ArtifactError:
            continue
    return calls


def _preview(value: str) -> str:
    """文書由来textを一行240文字以内のplain textへ省略する。"""

    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 240 else f"{normalized[:239]}…"


def _load_first_document(root: Path, candidates: list[str]) -> Document | None:
    """候補から最初に存在する検証済みDocumentを読む。"""

    for relative in candidates:
        path = root / relative
        if not path.is_file():
            continue
        try:
            return load_model(path, Document)
        except ArtifactError:
            continue
    return None


def _verified_response(
    root: Path, task: TaskName, call: LLMCallArtifact
) -> StructureResponse | TranslationResponse | ReviewResponse | None:
    """確定状態、hashおよびSchemaを検証したLLM応答だけを返す。"""

    if call.status not in {"succeeded", "partial"} or call.response_sha256 is None:
        return None
    directory = _llm_call_directory(root, task)
    if directory is None:
        return None
    path = directory / call.call_id / "response.json"
    models = {
        TaskName.STRUCTURE: StructureResponse,
        TaskName.TRANSLATE: TranslationResponse,
        TaskName.REVIEW: ReviewResponse,
    }
    model = models.get(task)
    try:
        if (
            model is None
            or not path.is_file()
            or sha256_file(path) != call.response_sha256
        ):
            return None
        return load_model(path, model)
    except (ArtifactError, OSError):
        return None


def _latest_call(root: Path, task: TaskName, status: str) -> LLMCallArtifact | None:
    """指定状態で更新時刻が最も新しいLLM Callを返す。"""

    calls = [call for call in _llm_calls(root, task) if call.status == status]
    return max(calls, key=lambda item: item.updated_at) if calls else None


def _latest_verified_call(root: Path, task: TaskName) -> LLMCallArtifact | None:
    """hashとSchemaを検証できる最新の確定済みLLM Callを返す。"""

    calls = sorted(
        _llm_calls(root, task), key=lambda item: item.updated_at, reverse=True
    )
    return next(
        (call for call in calls if _verified_response(root, task, call) is not None),
        None,
    )


def _comparison_text(rows: list[tuple[str, str]], empty: str = "") -> str:
    """同じ対象順の最大3件をTextArea用plain textへ整形する。"""

    if not rows:
        return empty
    return "\n\n".join(
        f"[{target_id}]\n{_preview(value) if value else '空'}"
        for target_id, value in rows[:3]
    )


def _render_text_areas(
    labels: tuple[str, ...], values: tuple[str, ...], key: str
) -> None:
    """同じ件数の読取専用TextAreaを横並びで表示する。"""

    columns = st.columns(len(labels))
    for index, (column, label, value) in enumerate(
        zip(columns, labels, values, strict=True)
    ):
        with column:
            widget_key = f"{key}-{index}"
            st.session_state[widget_key] = value
            st.text_area(
                label,
                height=180,
                disabled=True,
                key=widget_key,
            )


def _diff_text(before: str, after: str, before_label: str, after_label: str) -> str:
    """二つの表示textから行単位のunified diffを作る。"""

    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=before_label,
            tofile=after_label,
            lineterm="",
        )
    )


def _render_diff(before: str, after: str, before_label: str, after_label: str) -> None:
    """TextAreaの下へ追加・削除行を強調する差分Collapseを表示する。"""

    with st.expander("差分を表示", expanded=False):
        diff = _diff_text(before, after, before_label, after_label)
        if diff:
            st.code(diff, language="diff")
        else:
            st.caption("差分はありません。")


def _translation_comparison(root: Path) -> tuple[str, str] | None:
    """直近の同一TRANSLATE Callから英語と検証済み日本語を返す。"""

    document = _load_first_document(
        root,
        ["upgrade/reuse/document.json", "preprocess/structure/document.json"],
    )
    if document is None:
        return None
    sources = {
        span.id: span.source
        for _, unit in iter_text_units(document)
        for span in unit.spans
    }
    confirmed = _latest_verified_call(root, TaskName.TRANSLATE)
    if confirmed is not None:
        response = _verified_response(root, TaskName.TRANSLATE, confirmed)
        if not isinstance(response, TranslationResponse):
            return None
        translated = {item.span_id: item.text for item in response.translations}
        target_ids = [
            target_id
            for target_id in confirmed.target_ids
            if target_id in sources and target_id in translated
        ]
        return (
            _comparison_text([(item, sources[item]) for item in target_ids]),
            _comparison_text([(item, translated[item]) for item in target_ids]),
        )
    active = _latest_call(root, TaskName.TRANSLATE, "processing")
    if active is None:
        return None
    target_ids = [item for item in active.target_ids if item in sources]
    return (
        _comparison_text([(item, sources[item]) for item in target_ids]),
        "処理中 (確定結果なし)",
    )


def _review_targets(root: Path) -> dict[str, tuple[str, str]]:
    """検証済みALIGNまたはDocumentからReview対象をIDで返す。"""

    values: dict[str, tuple[str, str]] = {}
    for relative in ("review/align/alignment.json", "upgrade/align/result.json"):
        path = root / relative
        if not path.is_file():
            continue
        try:
            alignment = load_model(path, AlignmentResult)
        except ArtifactError:
            continue
        values.update(
            {
                target.id: (target.source, target.translation)
                for target in alignment.targets
            }
        )
    document = _load_first_document(
        root,
        [
            "review/fix/document.json",
            "translation/translate/document.json",
            "translation/translate-lite/document.json",
            "upgrade/reuse/document.json",
        ],
    )
    if document is not None:
        values.update(
            {
                target.id: (target.source, target.translation)
                for target in targets_from_document(document)
            }
        )
    return values


def _review_comparison(root: Path) -> tuple[str, str] | None:
    """直近の同一REVIEW Callから現在訳と修正候補を返す。"""

    targets = _review_targets(root)
    confirmed = _latest_verified_call(root, TaskName.REVIEW)
    if confirmed is not None:
        response = _verified_response(root, TaskName.REVIEW, confirmed)
        if not isinstance(response, ReviewResponse):
            return None
        revisions = {item.target_id: item for item in response.revisions}
        target_ids = [item for item in confirmed.target_ids if item in targets]
        before = [(item, targets[item][1]) for item in target_ids]
        after = [
            (
                item,
                " / ".join(edit.text for edit in revisions[item].edits)
                if item in revisions
                else "修正候補なし",
            )
            for item in target_ids
        ]
        return _comparison_text(before), _comparison_text(after)
    active = _latest_call(root, TaskName.REVIEW, "processing")
    if active is None:
        return None
    target_ids = [item for item in active.target_ids if item in targets]
    return (
        _comparison_text([(item, targets[item][1]) for item in target_ids]),
        "処理中 (確定結果なし)",
    )


def _fix_comparison(root: Path) -> tuple[str, str] | None:
    """適用済みRevision対象のFIX前後を同じTextUnit IDで返す。"""

    outcomes_path = root / "review/fix/outcomes.json"
    review_path = root / "review/review/review.json"
    before = _load_first_document(
        root,
        [
            "translation/translate/document.json",
            "translation/translate-lite/document.json",
            "upgrade/reuse/document.json",
        ],
    )
    if not outcomes_path.is_file() or not review_path.is_file() or before is None:
        return None
    try:
        fixed = load_model(outcomes_path, FixResult)
        review = load_model(review_path, ReviewResult)
    except ArtifactError:
        return None
    applied = {
        outcome.revision_id for outcome in fixed.outcomes if outcome.status == "applied"
    }
    target_ids = [item.target_id for item in review.revisions if item.id in applied]
    before_units = text_unit_index(before)
    after_units = text_unit_index(fixed.document)
    target_ids = [
        item for item in target_ids if item in before_units and item in after_units
    ]
    if not target_ids:
        return None
    return (
        _comparison_text(
            [(item, before_units[item].text("revised")) for item in target_ids]
        ),
        _comparison_text(
            [(item, after_units[item].text("revised")) for item in target_ids]
        ),
    )


def _fix_rejections(root: Path) -> list[tuple[str, str]]:
    """FIXが拒否したRevision IDと理由codeの組を返す。"""

    path = root / "review/fix/outcomes.json"
    if not path.is_file():
        return []
    try:
        result = load_model(path, FixResult)
    except ArtifactError:
        return []
    return [
        (item.revision_id, item.reason_code)
        for item in result.outcomes
        if item.status == "rejected"
    ]


def _markdown_code(value: str) -> str:
    """Artifact由来textを安全な一つのMarkdown inline codeへ変換する。"""

    normalized = " ".join(value.split())
    longest = max((len(item) for item in re.findall(r"`+", normalized)), default=0)
    fence = "`" * (longest + 1)
    return f"{fence}{normalized}{fence}"


def _render_latest_comparison(root: Path) -> None:
    """既存Artifactから最新の処理前後比較を表示する。"""

    fixed = _fix_comparison(root)
    reviewed = _review_comparison(root)
    translated = _translation_comparison(root)
    if fixed is not None:
        st.subheader("FIXの処理前・処理後")
        _render_text_areas(("修正前", "修正後"), fixed, "fix-comparison")
        _render_diff(fixed[0], fixed[1], "修正前", "修正後")
        rejected = _fix_rejections(root)
        if rejected:
            with st.expander(f"拒否された修正候補 ({len(rejected)})", expanded=False):
                for revision_id, reason_code in rejected:
                    st.markdown(
                        f"- **Revision ID:** {_markdown_code(revision_id)}  \n"
                        f"  **拒否理由:** {_markdown_code(reason_code)}"
                    )
    elif reviewed is not None:
        st.subheader("REVIEWの処理前・処理後")
        _render_text_areas(("修正前", "修正候補"), reviewed, "review-comparison")
        _render_diff(reviewed[0], reviewed[1], "修正前", "修正候補")
    elif translated is not None:
        st.subheader("TRANSLATEの処理前・処理後")
        _render_text_areas(
            ("翻訳前 (英語)", "翻訳後 (日本語)"),
            translated,
            "translate-comparison",
        )
        _render_diff(translated[0], translated[1], "翻訳前", "翻訳後")


def _review_context(root: Path) -> tuple[str, str] | None:
    """同一ReviewTargetの英語原文と日本語訳を返す。"""

    path = root / "review/align/alignment.json"
    if not path.is_file():
        return None
    try:
        alignment = load_model(path, AlignmentResult)
    except ArtifactError:
        return None
    by_id = {target.id: target for target in alignment.targets}
    call = _latest_call(root, TaskName.REVIEW, "processing") or _latest_call(
        root, TaskName.REVIEW, "succeeded"
    )
    target_ids = call.target_ids if call is not None else list(by_id)[:3]
    target_ids = [item for item in target_ids if item in by_id]
    if not target_ids:
        return None
    return (
        _comparison_text([(item, by_id[item].source) for item in target_ids]),
        _comparison_text([(item, by_id[item].translation) for item in target_ids]),
    )


def _call_v2_unit_ids(root: Path, document: Document) -> list[str]:
    """Upgradeの実行中または直近Call対象を英文v2 TextUnit IDへ解決する。"""

    calls = [
        (task, call)
        for task in (TaskName.TRANSLATE, TaskName.REVIEW)
        for call in _llm_calls(root, task)
    ]
    active = [(task, call) for task, call in calls if call.status == "processing"]
    succeeded = [(task, call) for task, call in calls if call.status == "succeeded"]
    selected = max(
        active or succeeded, key=lambda item: item[1].updated_at, default=None
    )
    if selected is None:
        return []
    task, call = selected
    if task == TaskName.REVIEW:
        return [target_id.removeprefix("translate/") for target_id in call.target_ids]
    span_to_unit = {
        span.id: unit.id for _, unit in iter_text_units(document) for span in unit.spans
    }
    return [
        span_to_unit[target_id]
        for target_id in call.target_ids
        if target_id in span_to_unit
    ]


def _unit_text(
    unit_ids: list[str], units: dict[str, TextUnit], layer: TextLayer
) -> str | None:
    """複数TextUnit IDを検証済み索引から一つの表示textへ解決する。"""

    if not unit_ids or any(unit_id not in units for unit_id in unit_ids):
        return None
    return "\n".join(units[unit_id].text(layer) for unit_id in unit_ids)


def _upgrade_context(root: Path) -> tuple[str, str, str] | None:
    """同一VersionChangeの英文v1、日本語v1、英文v2を返す。"""

    plan_path = root / "upgrade/diff/plan.json"
    source_v1 = _load_first_document(root, ["preprocess/source-v1/load/document.json"])
    source_v2 = _load_first_document(root, ["preprocess/source-v2/load/document.json"])
    translation_v1 = _load_first_document(
        root, ["preprocess/translation-v1/load/document.json"]
    )
    if (
        not plan_path.is_file()
        or source_v1 is None
        or source_v2 is None
        or translation_v1 is None
    ):
        return None
    try:
        plan = load_model(plan_path, UpgradePlan)
    except ArtifactError:
        return None
    requested = set(_call_v2_unit_ids(root, source_v2))
    changes = (
        [
            change
            for change in plan.changes
            if requested.intersection(change.source_v2_ids)
        ]
        if requested
        else plan.changes[:3]
    )
    if not changes:
        return None
    source_v1_units = text_unit_index(source_v1)
    source_v2_units = text_unit_index(source_v2)
    translation_v1_units = text_unit_index(translation_v1)
    rows: list[tuple[str, str, str, str]] = []
    for change in changes[:3]:
        value_v1 = _unit_text(change.source_v1_ids, source_v1_units, "source")
        value_v2 = _unit_text(change.source_v2_ids, source_v2_units, "source")
        value_ja = _unit_text(
            change.translation_v1_ids, translation_v1_units, "revised"
        )
        if change.kind == "added":
            value_v1 = "該当なし"
            value_ja = "該当なし"
        elif value_ja is None:
            value_ja = "対応訳なし"
        if change.kind == "deleted":
            value_v2 = "該当なし"
        if value_v1 is None or value_v2 is None:
            return None
        rows.append((change.id, value_v1, value_ja, value_v2))
    return (
        _comparison_text([(item[0], item[1]) for item in rows]),
        _comparison_text([(item[0], item[2]) for item in rows]),
        _comparison_text([(item[0], item[3]) for item in rows]),
    )


def _render_review_context(root: Path, processing_id: str) -> None:
    """Review tabへ英語原文と日本語訳の対応表示を描画する。"""

    values = _review_context(root)
    if values is None:
        st.caption("ALIGN完了後に表示")
        return
    st.subheader("レビュー対象")
    _render_text_areas(
        ("英語原文", "日本語訳"), values, f"review-context-{processing_id}"
    )


def _render_upgrade_context(root: Path, processing_id: str) -> None:
    """Upgrade tabへ三版の対応表示を描画する。"""

    values = _upgrade_context(root)
    if values is None:
        st.caption("DIFF完了後に表示")
        return
    st.subheader("版間の対応")
    _render_text_areas(
        ("英語v1", "日本語v1", "英語v2"),
        values,
        f"upgrade-context-{processing_id}",
    )
    _render_diff(values[0], values[2], "英語v1", "英語v2")


def _render_llm_progress(
    root: Path,
    record: TranslationRecord | ReviewRecord | UpgradeRecord,
    active_task: TaskName | None,
) -> None:
    """現在時刻とSTRUCTURE・TRANSLATE・REVIEWのCall内訳だけを表示する。"""

    st.write(f"更新時刻: {record.updated_at.isoformat()}")
    shown = False
    for progress in record.llm_progress:
        shown = True
        st.write(
            f"{progress.task}: {progress.completed_calls} / "
            f"{progress.planned_calls} calls "
            f"(再利用 {progress.reused_calls}, 失敗 {progress.failed_calls})"
        )
    if active_task in {TaskName.STRUCTURE, TaskName.TRANSLATE, TaskName.REVIEW}:
        shown = True
        observed, completed, failed = _live_call_counts(root, active_task)
        st.write(
            f"{active_task.value}: {completed} / 観測済み {observed} calls "
            f"(失敗 {failed})"
        )
    if not shown:
        st.caption("LLM進捗はありません。")


def _valid_check_artifact(root: Path, relative_path: str) -> bool:
    """CHECK Artifactが存在しSchema検証に成功した場合だけ真を返す。"""

    path = root / relative_path
    if not path.is_file():
        return False
    try:
        load_model(path, CheckResult)
    except ArtifactError:
        return False
    return True


def _task_progress(
    root: Path,
    record: TranslationRecord | ReviewRecord | UpgradeRecord,
) -> tuple[int, int, str]:
    """固定Task列の完了数、総数、実行中表示名を返す。"""

    stages = _task_stages(record)
    states = {state.task: state for state in record.tasks}
    completed = sum(
        _valid_check_artifact(root, artifact)
        if artifact is not None
        else states.get(task) is not None
        and states[task].status in {"succeeded", "skipped"}
        for _, task, artifact in stages
    )
    active_state = next(
        (state for state in record.tasks if state.status == "processing"), None
    )
    active = "-"
    if active_state is not None:
        active = active_state.task.value.replace("_", "-")
        if active_state.task == TaskName.CHECK:
            initial_done = _valid_check_artifact(root, "review/check/findings.json")
            active = "CHECK (最終)" if initial_done else "CHECK (初回)"
    return completed, len(stages), active


def _render_task_progress(
    entry: HistoryEntry, record: TranslationRecord | ReviewRecord | UpgradeRecord
) -> None:
    """固定Task列のProgressBarとLLM Call数を表示する。"""

    root = entry.record_path.parent
    completed, total, active = _task_progress(root, record)
    active_state = next(
        (task for task in record.tasks if task.status == "processing"), None
    )
    visible_state = active_state
    if visible_state is None and record.tasks:
        visible_state = record.tasks[-1]
    task_label = (
        visible_state.task.value.replace("_", "-")
        if visible_state is not None
        else active
    )
    task_status = visible_state.status if visible_state is not None else record.status
    detail = f"{completed} / {total} Task — {task_label} — {task_status}"
    st.progress(completed / total if total else 0.0, text=detail)
    active_task = active_state.task if active_state is not None else None
    with st.expander("進捗詳細", expanded=False, icon=":material/analytics:"):
        _render_llm_progress(root, record, active_task)
    _render_latest_comparison(root)
    processing_id = entry.processing_id or entry.kind
    if isinstance(record, ReviewRecord):
        _render_review_context(root, processing_id)
    elif isinstance(record, UpgradeRecord):
        _render_upgrade_context(root, processing_id)


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


def _preview_image_path(markdown: Path, target: str) -> Path | None:
    """Markdown基準の相対画像をpreview directory内の実fileへ限定する。"""

    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    root = markdown.parent.resolve()
    path = (root / unquote(parsed.path)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def _render_markdown_preview(markdown: Path, value: str) -> None:
    """Markdownの相対画像を安全なStreamlit画像へ置換してpreviewする。"""

    cursor = 0
    for match in _MARKDOWN_IMAGE_BLOCK.finditer(value):
        prefix = value[cursor : match.start()]
        if prefix.strip():
            st.markdown(prefix, unsafe_allow_html=False)
        target = match.group("target")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            st.markdown(match.group(0), unsafe_allow_html=False)
        elif image := _preview_image_path(markdown, target):
            st.image(image, caption=match.group("caption") or None)
        else:
            st.warning("Preview画像が欠落または参照範囲外です。")
        cursor = match.end()
    suffix = value[cursor:]
    if suffix.strip():
        st.markdown(suffix, unsafe_allow_html=False)


def _render_translation_outputs(entry: HistoryEntry, record: TranslationRecord) -> None:
    """hash検証済みMarkdownとDOCXのpreview・downloadを表示する。"""

    markdown: tuple[Path, bytes] | None = None
    docx: tuple[Path, bytes] | None = None
    for artifact in record.outputs:
        path = _valid_artifact(entry.record_path.parent, artifact)
        if path is None:
            st.error("成果物が欠落または変更されています。")
            continue
        if path.suffix.casefold() == ".md":
            value = path.read_bytes()
            markdown = path, value
        elif path.suffix.casefold() == ".docx":
            docx = path, path.read_bytes()
    if markdown is not None:
        with st.expander("Markdown preview"):
            _render_markdown_preview(markdown[0], markdown[1].decode("utf-8"))
    with st.container(horizontal=True, wrap=False):
        if markdown is not None:
            st.download_button(
                "Markdownをdownload",
                markdown[1],
                file_name=markdown[0].name,
                mime="text/markdown",
            )
        if docx is not None:
            st.download_button(
                "DOCXをdownload",
                docx[1],
                file_name=docx[0].name,
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


def _render_upgrade_output(entry: HistoryEntry, record: UpgradeRecord) -> None:
    """hash検証済みの日本語v2 DOCXをdownload対象として表示する。"""

    for artifact in record.outputs:
        path = _valid_artifact(entry.record_path.parent, artifact)
        if path is None:
            st.error("成果物が欠落または変更されています。")
            continue
        st.download_button(
            "日本語v2 DOCXをdownload",
            path.read_bytes(),
            file_name=path.name,
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
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
    elif isinstance(record, UpgradeRecord):
        paths = [
            *list((root / "upgrade/source-v1").glob("*")),
            *list((root / "upgrade/source-v2").glob("*")),
            *list((root / "upgrade/translation-v1").glob("*")),
        ]
        expected = [record.source_v1, record.source_v2, record.translation_v1]
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
    elif isinstance(record, UpgradeRecord):
        operation = partial(
            _resume_upgrade,
            paths[0],
            paths[1],
            paths[2],
            record.backend,
            processing_id,
        )
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
    elif isinstance(record, UpgradeRecord):
        source_v1 = st.file_uploader(
            "Resume用の英文v1 PDF",
            type=["pdf"],
            key=f"resume-upgrade-source-v1-{processing_id}",
        )
        source_v2 = st.file_uploader(
            "Resume用の英文v2 PDF",
            type=["pdf"],
            key=f"resume-upgrade-source-v2-{processing_id}",
        )
        translation_v1 = st.file_uploader(
            "Resume用の日本語v1 PDF",
            type=["pdf"],
            key=f"resume-upgrade-translation-v1-{processing_id}",
        )
        uploads = (
            [source_v1, source_v2, translation_v1]
            if all(
                value is not None for value in (source_v1, source_v2, translation_v1)
            )
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


def _render_record(entry: HistoryEntry) -> None:
    """最上位記録のProgressBar、詳細および比較TextAreaを表示する。"""

    record = entry.record
    if record is None:
        st.error(entry.error or "処理記録を読み込めません。")
        return
    if isinstance(record, (TranslationRecord, ReviewRecord, UpgradeRecord)):
        _render_task_progress(entry, record)
    else:
        completed = int(record.status == "succeeded")
        st.progress(
            float(completed),
            text=f"{completed} / 1 Task — REGISTER — {record.status}",
        )
        with st.expander("進捗詳細", expanded=False, icon=":material/analytics:"):
            st.write(f"更新時刻: {record.updated_at.isoformat()}")
            st.caption("LLM進捗はありません。")


def _render_record_actions(entry: HistoryEntry, registry: WorkerRegistry) -> None:
    """エラー、成果物およびResume操作を進捗Collapseの外へ表示する。"""

    record = entry.record
    if record is None:
        return
    processing_id = entry.processing_id or "-"
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
        elif isinstance(record, UpgradeRecord):
            _render_upgrade_output(entry, record)
        else:
            _render_registration_result(entry, record)
    _render_resume(entry, registry)


def _render_selected(processing_id: str, registry: WorkerRegistry) -> None:
    """選択処理をArtifactから再読込みして表示する。"""

    entry = _entry_by_id(processing_id)
    if entry is None:
        _render_future_state(processing_id, registry)
        return
    _render_record(entry)


def _render_processing_panel(
    processing_id: str,
    registry: WorkerRegistry,
    entries: list[HistoryEntry] | None = None,
) -> None:
    """進捗と比較を折り畳み、成果物操作をその外側へ表示する。"""

    entries = entries if entries is not None else _history_entries()
    current = next(
        (entry for entry in entries if entry.processing_id == processing_id), None
    )
    processing = (
        current is not None
        and current.record is not None
        and (current.record.status == "processing")
    )
    active = processing or registry.active(processing_id)
    status = "running"
    if current is not None and current.record is not None:
        if current.record.status == "succeeded":
            status = "complete"
        elif current.record.status in {"failed", "cancelled"}:
            status = "error"

    progress_panel = st.status(
        "進捗と処理内容",
        expanded=True,
        state=status,
    )
    with progress_panel:

        @st.fragment(run_every="1s" if active else None)
        def render_progress() -> None:
            """実行中だけ1秒ごとにArtifactを再読込みする。"""

            _render_selected(processing_id, registry)
            refreshed = _entry_by_id(processing_id)
            if refreshed is not None and (
                current is None
                or (
                    active
                    and refreshed.record is not None
                    and refreshed.record.status in _TERMINAL_STATUSES
                )
            ):
                st.rerun(scope="app")

        render_progress()
    progress_panel.update(expanded=True, state=status)
    refreshed = _entry_by_id(processing_id)
    if refreshed is not None:
        _render_record_actions(refreshed, registry)


def _render_session_title(processing_id: str | None) -> None:
    """Session IDをStreamlit AppBarと同じ高さへ表示する。"""

    title = html.escape(processing_id or "新規セッション")
    st.html(
        f"""
        <style>
        #translate-session-title {{
            position: fixed;
            top: 0;
            left: 22rem;
            z-index: 999990;
            height: 3.75rem;
            max-width: calc(100vw - 40rem);
            display: flex;
            align-items: center;
            overflow: hidden;
            color: inherit;
            font-size: 0.875rem;
            font-weight: 600;
            text-overflow: ellipsis;
            white-space: nowrap;
            pointer-events: none;
        }}
        @media (max-width: 768px) {{
            #translate-session-title {{ left: 5rem; max-width: calc(100vw - 15rem); }}
        }}
        </style>
        <div id="translate-session-title" aria-label="Session ID">{title}</div>
        """
    )


def main() -> None:
    """折り畳み可能なStreamlitの4操作と共通処理履歴を表示する。"""

    st.set_page_config(
        page_title="Translate",
        page_icon=":material/translate:",
        layout="wide",
    )
    st.logo(_LOGO_PATH, size="large")
    registry = worker_registry()
    entries = _history_entries()
    selected_id = _render_history_sidebar(entries)
    _render_session_title(selected_id)
    expander_key = selected_id or "new"
    with st.expander(
        "入力と設定",
        expanded=selected_id is None,
        key=f"pipeline-setup-{expander_key}",
        icon=":material/tune:",
    ):
        translate_tab, review_tab, upgrade_tab, register_tab = st.tabs(
            ["Translate", "Review", "Upgrade", "Register"]
        )
        with translate_tab:
            _render_translate_form(registry)
        with review_tab:
            _render_review_form(registry)
        with upgrade_tab:
            _render_upgrade_form(registry)
        with register_tab:
            _render_register_form(registry)
    if selected_id is not None:
        _render_processing_panel(selected_id, registry, entries)
