"""Streamlit UI app module."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile
from uuid_utils import uuid7

from translate.adapters.artifact_store import (
    ArtifactError,
    ArtifactStore,
    load_model,
    write_model,
)
from translate.models.artifacts import (
    RegistrationRecord,
    ReviewRecord,
    TranslationRecord,
)
from translate.models.upgrade import (
    UpgradeRecord,
)
from translate.pipeline import InputError

from .history import (
    HistoryEntry,
    _clear_processing_selection,
    _entry_by_id,
    _entry_label,
    _history_entries,
    _render_history_sidebar,
    _select_processing,
    _selected_processing_id,
)
from .inputs import (
    _stage_register,
    _stage_review,
    _stage_translate,
    _stage_upgrade,
    _stored_resume_paths,
)
from .results import (
    _render_record,
    _render_registration_result,
    _render_resume_uploads,
    _render_review_outputs,
    _render_translation_outputs,
    _render_upgrade_output,
)
from .runtime import (
    PipelineJob,
    WorkerRegistry,
    _render_future_error,
    worker_registry,
)
from .types import _TERMINAL_STATUSES


class TranslationApp:
    """worker登録表を共有し、入力・実行・再開・履歴操作と画面表示を制御する。"""

    def __init__(self, registry: WorkerRegistry) -> None:
        """Streamlitの再実行をまたいで存続するworker登録表を受け取る。

        Args:
            registry: 新規実行・再開・停止の対象workerを管理する登録表。
        """
        self.registry = registry

    def _start_translate(self, upload: UploadedFile) -> str:
        """Translate入力を保存し、background workerへ登録する。

        Args:
            upload (UploadedFile): 保存または照合するUpload File。

        Returns:
            str: Translate入力を保存し、background workerへ登録する。
        """

        processing_id = str(uuid7())
        source = _stage_translate(upload, processing_id)
        self.registry.submit(
            processing_id,
            PipelineJob("translate", (source,), processing_id),
        )
        return processing_id

    def _start_review(
        self, source_upload: UploadedFile, translation_upload: UploadedFile
    ) -> str:
        """Review二入力を保存し、background workerへ登録する。

        Args:
            source_upload (UploadedFile): Review原文のUpload File。
            translation_upload (UploadedFile): Review訳文のUpload File。

        Returns:
            str: Review二入力を保存し、background workerへ登録する。
        """

        processing_id = str(uuid7())
        source, translation = _stage_review(
            source_upload, translation_upload, processing_id
        )
        self.registry.submit(
            processing_id,
            PipelineJob("review", (source, translation), processing_id),
        )
        return processing_id

    def _start_register(self, uploads: list[UploadedFile]) -> str:
        """Register入力を保存し、background workerへ登録する。

        Args:
            uploads (list[UploadedFile]): 保存または照合するUpload File一覧。

        Returns:
            str: Register入力を保存し、background workerへ登録する。

        Raises:
            InputError: `at least one registration file is required`と判定した場合。
        """

        if not uploads:
            raise InputError("at least one registration file is required")
        processing_id = str(uuid7())
        paths = _stage_register(uploads, processing_id)
        self.registry.submit(
            processing_id,
            PipelineJob("register", tuple(paths), processing_id),
        )
        return processing_id

    def _start_upgrade(
        self,
        source_v1: UploadedFile,
        source_v2: UploadedFile,
        translation_v1: UploadedFile,
    ) -> str:
        """Upgrade三入力を保存し、background workerへ登録する。

        Args:
            source_v1 (UploadedFile): 比較基準にする英文v1。
            source_v2 (UploadedFile): 変更を反映する英文v2。
            translation_v1 (UploadedFile): 比較基準にする日本語v1。

        Returns:
            str: Upgrade三入力を保存し、background workerへ登録する。
        """

        processing_id = str(uuid7())
        paths = _stage_upgrade(source_v1, source_v2, translation_v1, processing_id)
        self.registry.submit(
            processing_id,
            PipelineJob("upgrade", paths, processing_id),
        )
        return processing_id

    def _render_translate_form(
        self,
        *,
        busy: bool = False,
    ) -> None:
        """Translateの英語PDF入力を表示する。

        Args:
        """

        upload = st.file_uploader("英語PDF", type=["pdf"], key="translate-source")
        submitted = st.button(
            "Start",
            icon=":material/translate:",
            disabled=upload is None or busy,
            type="primary",
            key="start-translate",
        )
        if submitted and upload is not None:
            try:
                _select_processing(self._start_translate(upload))
            except (InputError, OSError) as error:
                st.error(str(error))

    def _render_review_form(
        self,
        *,
        busy: bool = False,
    ) -> None:
        """Reviewの英語原文PDFと日本語訳文PDF入力を表示する。

        Args:
        """

        source = st.file_uploader("英語原文PDF", type=["pdf"], key="review-source")
        translation = st.file_uploader(
            "日本語訳文PDF", type=["pdf"], key="review-translation"
        )
        submitted = st.button(
            "Start",
            icon=":material/rate_review:",
            disabled=source is None or translation is None or busy,
            type="primary",
            key="start-review",
        )
        if submitted and source is not None and translation is not None:
            try:
                _select_processing(self._start_review(source, translation))
            except (InputError, OSError) as error:
                st.error(str(error))

    def _render_register_form(
        self,
        *,
        busy: bool = False,
    ) -> None:
        """RegisterのPDFまたはディレクトリ入力を表示する。

        Args:
        """

        mode = st.segmented_control(
            "登録する入力",
            ["ファイル", "ディレクトリ"],
            default="ファイル",
            key="register-input-mode",
        )
        uploads = st.file_uploader(
            "参照資料",
            type=["pdf"],
            accept_multiple_files="directory" if mode == "ディレクトリ" else True,
            key="register-sources",
        )
        submitted = st.button(
            "Start",
            icon=":material/library_add:",
            disabled=not uploads or len(uploads) > 100 or busy,
            type="primary",
            key="start-register",
        )
        if len(uploads) > 100:
            st.caption("一度に登録できるfileは100件までです。")
        if submitted:
            try:
                _select_processing(self._start_register(uploads))
            except (InputError, OSError) as error:
                st.error(str(error))

    def _render_upgrade_form(
        self,
        *,
        busy: bool = False,
    ) -> None:
        """Upgradeの英文二版と日本語旧版のPDF入力を表示する。

        Args:
        """

        source_v1 = st.file_uploader(
            "英文v1 PDF", type=["pdf"], key="upgrade-source-v1"
        )
        source_v2 = st.file_uploader(
            "英文v2 PDF", type=["pdf"], key="upgrade-source-v2"
        )
        translation_v1 = st.file_uploader(
            "日本語v1 PDF", type=["pdf"], key="upgrade-translation-v1"
        )
        ready = all(
            value is not None for value in (source_v1, source_v2, translation_v1)
        )
        submitted = st.button(
            "Start",
            icon=":material/upgrade:",
            disabled=not ready or busy,
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
                    self._start_upgrade(source_v1, source_v2, translation_v1)
                )
            except (InputError, OSError) as error:
                st.error(str(error))

    def _render_future_state(self, processing_id: str) -> None:
        """Artifact公開前の待機・準備状態またはworker失敗を表示する。

        Args:
            processing_id (str): 新規処理またはResume対象の処理ID。
        """

        future = self.registry.future(processing_id)
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

    def _resume_entry(self, entry: HistoryEntry, paths: list[Path]) -> bool:
        """検証済み入力を使って処理種類別のResumeを登録する。

        Args:
            entry (HistoryEntry): 表示または操作対象の処理履歴。
            paths (list[Path]): 列挙された入力Path。

        Returns:
            bool: 検証済み入力を使って処理種類別のResumeを登録する。
        """

        processing_id = entry.processing_id
        record = entry.record
        if processing_id is None or record is None:
            return False
        return self.registry.submit(
            processing_id,
            PipelineJob(
                entry.kind,
                tuple(paths),
                processing_id,
                record.source_id if isinstance(record, RegistrationRecord) else None,
                resuming=True,
            ),
        )

    def _render_resume(self, entry: HistoryEntry) -> None:
        """終端失敗またはworker不明のprocessing記録にResume確認を表示する。

        Args:
            entry (HistoryEntry): 表示または操作対象の処理履歴。
        """

        record = entry.record
        processing_id = entry.processing_id
        if (
            record is None
            or processing_id is None
            or record.status == "succeeded"
            or self.registry.active(processing_id)
        ):
            return
        paths = _stored_resume_paths(entry)
        if paths is None:
            st.info(
                "Resume用の保存済み入力がありません。同じ入力を再uploadしてください。"
            )
            paths = _render_resume_uploads(entry)
            if paths is not None and self._resume_entry(entry, paths):
                st.rerun()
            return
        submitted = st.button(
            "Resume",
            key=f"resume-submit-{processing_id}",
        )
        if submitted and self._resume_entry(entry, paths):
            st.rerun()

    def _render_record_actions(self, entry: HistoryEntry) -> None:
        """エラー、成果物およびResume操作を進捗Collapseの外へ表示する。

        Args:
            entry (HistoryEntry): 表示または操作対象の処理履歴。
        """

        record = entry.record
        if record is None:
            return
        processing_id = entry.processing_id or "-"
        if record.error is not None:
            st.error(
                f"{record.error.message} "
                f"({record.error.cause_type or 'unknown'}, retryable={record.error.retryable})"
            )
        future = self.registry.future(processing_id)
        if future is not None and future.done() and record.error is None:
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

    def stop(self, entry: HistoryEntry) -> bool:
        """UI所有workerを停止し、残った処理記録をcancelledへ確定する。

        Args:
            entry: 停止対象の処理履歴。

        Returns:
            所有する実行中workerを停止した場合はTrue。
        """

        processing_id = entry.processing_id
        record = entry.record
        if (
            processing_id is None
            or record is None
            or record.status != "processing"
            or not self.registry.stop(processing_id)
        ):
            return False
        try:
            current = load_model(entry.record_path, type(record))
        except ArtifactError:
            return True
        if current.status == "processing":
            if isinstance(current, RegistrationRecord):
                current.status = "cancelled"
                current.updated_at = datetime.now(UTC)
                write_model(entry.record_path, current)
            else:
                ArtifactStore(current, entry.record_path).cancel_processing()
        return True

    def _render_history_delete(self, entry: HistoryEntry) -> None:
        """終了済みの選択履歴だけを確認操作付きで削除する。

        Args:
            entry (HistoryEntry): 表示または操作対象の処理履歴。
        """

        record = entry.record
        processing_id = entry.processing_id
        if (
            record is None
            or processing_id is None
            or record.status == "processing"
            or self.registry.active(processing_id)
        ):
            return
        with st.expander("履歴を削除", expanded=True, icon=":material/delete:"):
            st.caption(_entry_label(entry))
            confirmed = st.checkbox(
                "成果物と保存済み入力を削除する",
                key=f"confirm-delete-{processing_id}",
            )
            if st.button(
                "削除",
                key=f"delete-{processing_id}",
                disabled=not confirmed,
                type="secondary",
            ):
                try:
                    self.delete_history(entry)
                except (InputError, OSError) as error:
                    st.error(str(error))
                else:
                    st.session_state.pop("pending-delete", None)
                    if _selected_processing_id() == processing_id:
                        st.session_state.pop("selected-processing", None)
                        st.query_params.clear()
                    st.rerun()

    def delete_history(
        self,
        entry: HistoryEntry,
        *,
        outputs_root: Path | None = None,
    ) -> None:
        """終了済み記録の正確な処理directoryと保存入力だけを削除する。

        Args:
            entry (HistoryEntry): 表示または操作対象の処理履歴。
            outputs_root (Path | None): 成果物Root Directory。
            work_root (Path | None): Uploadの一時保存Root Directory。

        Raises:
            InputError: `valid processing history is required`、`active processing history cannot
                be deleted`、`history path is outside the outputs directory`、`saved input path is
                outside the UI work directory`のいずれかと判定した場合。
        """

        processing_id = entry.processing_id
        record = entry.record
        if processing_id is None or record is None:
            raise InputError("valid processing history is required")
        if record.status == "processing" or self.registry.active(processing_id):
            raise InputError("active processing history cannot be deleted")
        outputs = (outputs_root or Path.cwd() / "outputs").resolve()
        processing_directory = entry.record_path.parent.resolve()
        if (
            processing_directory.name != processing_id
            or processing_directory.parent.parent != outputs
        ):
            raise InputError("history path is outside the outputs directory")
        shutil.rmtree(processing_directory)

    def _render_selected(self, processing_id: str) -> None:
        """選択処理をArtifactから再読込みして表示する。

        Args:
            processing_id (str): 新規処理またはResume対象の処理ID。
        """

        entry = _entry_by_id(processing_id)
        if entry is None:
            self._render_future_state(processing_id)
            return
        _render_record(entry)

    def _render_processing_panel(
        self, processing_id: str, entries: list[HistoryEntry] | None = None
    ) -> None:
        """進捗と比較を折り畳み、成果物操作をその外側へ表示する。

        Args:
            processing_id (str): 新規処理またはResume対象の処理ID。
            entries (list[HistoryEntry] | None): 表示対象の処理履歴一覧。
        """

        entries = entries if entries is not None else _history_entries()
        current = next(
            (entry for entry in entries if entry.processing_id == processing_id), None
        )
        processing = (
            current is not None
            and current.record is not None
            and (current.record.status == "processing")
        )
        active = processing or self.registry.active(processing_id)
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

                self._render_selected(processing_id)
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
            refreshed = _entry_by_id(processing_id)
            if refreshed is not None:
                if (
                    refreshed.record is not None
                    and refreshed.record.status == "processing"
                ):
                    if st.button(
                        "Stop",
                        key=f"stop-{processing_id}",
                        icon=":material/stop_circle:",
                        disabled=not self.registry.active(processing_id),
                    ):
                        if self.stop(refreshed):
                            st.rerun()
                        st.error("処理を停止できませんでした。")
                else:
                    self._render_resume(refreshed)
        progress_panel.update(expanded=True, state=status)
        refreshed = _entry_by_id(processing_id)
        if refreshed is not None:
            self._render_record_actions(refreshed)

    def run(self) -> None:
        """折り畳み可能なStreamlitの4操作と共通処理履歴を表示する。"""

        st.set_page_config(
            page_title="Translate",
            layout="wide",
        )
        home_url = urlsplit(st.context.url or "http://localhost/")
        st.logo(
            "🌐",
            size="large",
            link=home_url._replace(path="/", query="", fragment="").geturl(),
        )
        entries = _history_entries()
        selected_id = _render_history_sidebar(entries)
        pending_delete = st.session_state.get("pending-delete")
        candidate = next(
            (entry for entry in entries if entry.processing_id == pending_delete), None
        )
        if candidate is not None:
            self._render_history_delete(candidate)
        expander_key = selected_id or "new"
        busy = any(
            self.registry.active(processing_id)
            for processing_id in {
                *(entry.processing_id for entry in entries if entry.processing_id),
                selected_id,
            }
            if processing_id is not None
        )
        session_page = None

        def render_workflows() -> None:
            """4種類の処理フォームを入力ページに表示する。"""

            if selected_id is not None:
                if st.query_params.get("processing") and session_page is not None:
                    st.switch_page(
                        session_page,
                        query_params={"processing": selected_id},
                    )
                _clear_processing_selection()
                st.rerun()
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
                    st.caption(
                        "英語PDFから文書構造を抽出し、日本語へ翻訳します。結果を確認してMarkdownとWordを出力します。"
                    )
                    self._render_translate_form(busy=busy)
                with review_tab:
                    st.caption(
                        "英語原文と日本語訳文を照合します。変更箇所、指摘、修正案を一覧で出力します。"
                    )
                    self._render_review_form(busy=busy)
                with upgrade_tab:
                    st.caption(
                        "英文の旧版・新版と日本語旧訳を比較します。変更箇所と修正案を一覧で出力します。"
                    )
                    self._render_upgrade_form(busy=busy)
                with register_tab:
                    st.caption(
                        "PDF資料をQdrantへ登録し、TranslateやReviewで参照できるようにします。"
                    )
                    self._render_register_form(busy=busy)

        def render_session() -> None:
            """選択中セッションの進捗と成果物を表示する。"""

            if selected_id is not None:
                self._render_processing_panel(selected_id, entries)

        workflow_page = st.Page(
            render_workflows,
            title="新規処理",
            url_path="translate",
            default=selected_id is None,
        )
        pages = [workflow_page]
        if selected_id is not None:
            session_page = st.Page(
                render_session,
                title=f"Session · {selected_id}",
                url_path="session",
            )
            pages.append(session_page)
        cast(Any, st.navigation)(pages, position="top").run()


def main() -> None:
    """Streamlitの実行ごとにControllerを作り、共有workerで画面を表示する。"""
    TranslationApp(worker_registry()).run()
