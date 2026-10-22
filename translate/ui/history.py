"""Streamlit UI history module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import streamlit as st
from pydantic import BaseModel, ConfigDict

from translate.adapters.artifact_store import (
    ArtifactError,
    load_model,
)
from translate.models.artifacts import (
    RegistrationRecord,
    ReviewRecord,
    TaskName,
    TranslationRecord,
)
from translate.models.upgrade import (
    UpgradeRecord,
)

from .types import ProcessingKind, ProcessingRecord, TaskStage


def _entry_label(entry: HistoryEntry) -> str:
    """処理履歴の選択欄に種類、入力、状態を一行で表示する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。

    Returns:
        str: 処理履歴の選択欄に種類、入力、状態とIDを表示する。
    """

    record = entry.record
    if isinstance(record, TranslationRecord):
        source = record.source.logical_path
    elif isinstance(record, ReviewRecord):
        source = record.translation.logical_path
    elif isinstance(record, RegistrationRecord):
        source = record.inputs[0].logical_path if record.inputs else "-"
    elif isinstance(record, UpgradeRecord):
        source = record.source_v2.logical_path
    else:
        source = entry.record_path.parent.name
    labels = {
        "translate": "Translate",
        "review": "Review",
        "register": "Register",
        "upgrade": "Upgrade",
    }
    status = (
        {
            "processing": "処理中",
            "succeeded": "成功",
            "failed": "失敗",
            "cancelled": "停止",
        }.get(record.status, record.status)
        if record is not None
        else "読込不可"
    )
    return f"{labels.get(entry.kind, entry.kind)} | {Path(source).name} | {status}"


def _entry_date(entry: HistoryEntry) -> str:
    updated_at = entry.record.updated_at if entry.record is not None else None
    return updated_at.astimezone().strftime("%Y-%m-%d %H:%M") if updated_at else "-"


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
        """有効な最上位記録から処理IDを返す。

        Returns:
            str | None: 有効な最上位記録から処理IDを返す。
        """

        if isinstance(self.record, TranslationRecord):
            return self.record.translation_id
        if isinstance(self.record, ReviewRecord):
            return self.record.review_id
        if isinstance(self.record, RegistrationRecord):
            return self.record.registration_id
        if isinstance(self.record, UpgradeRecord):
            return self.record.upgrade_id
        return None


def _select_processing(processing_id: str) -> None:
    """選択処理IDをURLへ保存し、全体を再読込みする。

    Args:
        processing_id (str): 新規処理またはResume対象の処理ID。
    """

    st.query_params["processing"] = processing_id
    st.rerun()


def _clear_processing_selection() -> None:
    """選択中の処理IDを画面状態とURLから消去する。"""

    st.session_state.pop("selected-processing", None)
    st.query_params.clear()


def _selected_processing_id() -> str | None:
    """URL query parameterから選択中の処理IDを取得する。

    Returns:
        str | None: URL query parameterから選択中の処理IDを取得する。
    """

    value = st.query_params.get("processing")
    if isinstance(value, str) and value:
        st.session_state["selected-processing"] = value
        return value
    return st.session_state.get("selected-processing")


def _task_stages(
    record: TranslationRecord | ReviewRecord | UpgradeRecord,
) -> tuple[TaskStage, ...]:
    """処理種類に対応する表示stage列を返す。

    Args:
        record (TranslationRecord | ReviewRecord | UpgradeRecord): 状態またはTask情報を更新する処理Record。

    Returns:
        tuple[TaskStage, ...]: 処理種類に対応する表示stage列を返す。
    """

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
        return (*common, ("Review Agent", TaskName.REVIEW, None))
    if isinstance(record, UpgradeRecord):
        return (*common, ("Upgrade Agent", TaskName.DIFF, None))
    return (
        *common,
        ("STRUCTURE", TaskName.STRUCTURE, None),
        ("TRANSLATE", TaskName.TRANSLATE, None),
        ("REVIEW", TaskName.REVIEW, None),
        ("FIX", TaskName.FIX, None),
        ("LINT", TaskName.LINT, None),
        ("COVER", TaskName.COVER, None),
        ("MARKDOWN", TaskName.MARKDOWN, None),
        ("PANDOC", TaskName.PANDOC, None),
        ("OOXML", TaskName.OOXML, None),
    )


def _entry_by_id(processing_id: str) -> HistoryEntry | None:
    """最新の履歴列挙から指定処理IDを探す。

    Args:
        processing_id (str): 新規処理またはResume対象の処理ID。

    Returns:
        HistoryEntry | None: 最新の履歴列挙から指定処理IDを探す。
    """

    return next(
        (entry for entry in _history_entries() if entry.processing_id == processing_id),
        None,
    )


def _history_entries(outputs: Path | None = None) -> list[HistoryEntry]:
    """outputs直下の新Schema処理記録を新しい順に100件返す。

    Args:
        outputs (Path | None): 成果物Root Directory。

    Returns:
        list[HistoryEntry]: outputs直下の新Schema処理記録を新しい順に100件返す。
    """

    root = (outputs or Path.cwd() / "outputs").resolve()
    definitions: tuple[tuple[str, ProcessingKind, type[ProcessingRecord]], ...] = (
        ("state-translation.json", "translate", TranslationRecord),
        ("state-review.json", "review", ReviewRecord),
        ("state-registration.json", "register", RegistrationRecord),
        ("state-upgrade.json", "upgrade", UpgradeRecord),
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


def _render_history_sidebar(entries: list[HistoryEntry]) -> str | None:
    """左sidebarの縦並び一覧から処理を選択し、選択IDを返す。

    Args:
        entries (list[HistoryEntry]): 表示対象の処理履歴一覧。

    Returns:
        str | None: 左sidebarの縦並び一覧から処理を選択し、選択IDを返す。
    """

    valid_entries = [entry for entry in entries if entry.processing_id is not None]
    invalid_entries = [entry for entry in entries if entry.error is not None]
    selected_id = _selected_processing_id()
    with st.sidebar:
        if st.button("新規", key="home", icon=":material/add:"):
            _clear_processing_selection()
            st.rerun()
        st.subheader("処理履歴", icon=":material/history:")
        if not valid_entries and not invalid_entries:
            st.caption("処理履歴はありません。")
        for entry in valid_entries:
            processing_id = entry.processing_id
            if processing_id is None:
                continue
            select_column, actions_column = st.columns([10, 1])
            with select_column:
                if st.button(
                    f"{_entry_label(entry)}  \n{_entry_date(entry)}",
                    key=f"history-{processing_id}",
                    type="tertiary",
                    width="stretch",
                    wrap=True,
                ):
                    _select_processing(processing_id)
            active = entry.record is not None and entry.record.status == "processing"
            with actions_column.popover(
                "操作",
                icon=":material/more_vert:",
                key=f"history-actions-{processing_id}",
                help="処理履歴の操作",
            ):
                if st.button(
                    "削除",
                    key=f"history-delete-{processing_id}",
                    icon=":material/delete:",
                    disabled=active,
                ):
                    st.session_state["pending-delete"] = processing_id
        for entry in invalid_entries:
            st.warning(f"{entry.error} {entry.record_path}")
    return selected_id
