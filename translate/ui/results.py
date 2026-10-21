"""Streamlit UI results module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from translate.adapters.artifact_store import (
    ArtifactError,
    load_model,
)
from translate.models.artifacts import (
    RegistrationRecord,
    ReviewRecord,
    ReviewResult,
    TranslationRecord,
)
from translate.models.upgrade import (
    UpgradePlan,
    UpgradeRecord,
)
from translate.pipeline import InputError

from .comparisons import _load_first_document, _review_targets, _unit_text
from .history import HistoryEntry
from .inputs import _stage_resume_uploads
from .progress import (
    _render_markdown_preview,
    _render_task_progress,
    _valid_artifact,
)


def _review_rows(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Review成果を一覧表示用に整形する。

    REVIEWの成果物を読み、指摘行と修正候補行へ分ける。

    Args:
        root (Path): 処理成果物のルートディレクトリ。

    Returns:
        tuple[list[dict[str, str]], list[dict[str, str]]]: 指摘行と修正候補行。
    """

    try:
        reviewed = load_model(root / "tasks/41-review/review.json", ReviewResult)
    except ArtifactError:
        return [], []

    targets = _review_targets(root)

    def target_text(target_ids: list[str], index: int) -> str:
        """対象ID群の本文を連結する。

        Args:
            target_ids (list[str]): LLM Call対象の安定識別ID列。
            index (int): 対象要素の読み順Index。

        Returns:
            str: 対象ID群の本文を連結する。
        """

        return " / ".join(
            value[index]
            for target_id in target_ids
            if (value := targets.get(target_id)) is not None and value[index]
        )

    findings = reviewed.findings
    severity_labels = {"error": "エラー", "warning": "警告", "info": "情報"}
    finding_rows = [
        {
            "重要度": severity_labels.get(finding.severity, finding.severity),
            "カテゴリ": finding.category,
            "対象": ", ".join(finding.target_ids) or "-",
            "原文": target_text(finding.target_ids, 0),
            "現在の訳": target_text(finding.target_ids, 1),
            "内容": finding.message,
        }
        for finding in findings
    ]

    revisions = reviewed.revisions
    revision_rows = [
        {
            "候補ID": revision.id,
            "対象": revision.target_id,
            "現在の訳": target_text([revision.target_id], 1) or "不明",
            "提案訳": " / ".join(edit.text for edit in revision.edits) or "変更なし",
        }
        for revision in revisions
    ]
    return finding_rows, revision_rows


def _render_translation_outputs(entry: HistoryEntry, record: TranslationRecord) -> None:
    """hash検証済みMarkdownとDOCXのpreview・downloadを表示する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。
        record (TranslationRecord): 状態またはTask情報を更新する処理Record。
    """

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
    download_columns = st.columns(2, vertical_alignment="center")
    if markdown is not None:
        with download_columns[0]:
            st.download_button(
                "Markdownをdownload",
                markdown[1],
                file_name=markdown[0].name,
                mime="text/markdown",
            )
    if docx is not None:
        with download_columns[1]:
            st.download_button(
                "DOCXをdownload",
                docx[1],
                file_name=docx[0].name,
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )


def _render_registration_result(
    entry: HistoryEntry, record: RegistrationRecord
) -> None:
    """Registerのcollection、各資料状態と処理記録downloadを表示する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。
        record (RegistrationRecord): 状態またはTask情報を更新する処理Record。
    """

    if record.result is not None:
        st.write(f"collection: {record.result.collection}")
        st.write(f"Embedding model: {record.result.embedding_model}")
        st.write(f"Point合計: {record.result.total_points}")
        st.dataframe(
            [source.model_dump(mode="json") for source in record.result.sources],
            width="stretch",
        )
    st.download_button(
        "Register記録をdownload",
        entry.record_path.read_bytes(),
        file_name="registration.json",
        mime="application/json",
    )


def _render_review_outputs(entry: HistoryEntry, record: ReviewRecord) -> None:
    """Review成果物を表示する。

    変更箇所・指摘・修正提案の全件と結果JSONのdownloadを描画する。

    Args:
        entry (HistoryEntry): 表示対象の履歴項目。
        record (ReviewRecord): 成功したReviewの最上位記録。
    """

    if not record.outputs or any(
        _valid_artifact(entry.record_path.parent, artifact) is None
        for artifact in record.outputs
    ):
        st.error("成果物が欠落または変更されています。")
        return
    finding_rows, revision_rows = _review_rows(entry.record_path.parent)
    error_count = sum(row["重要度"] == "エラー" for row in finding_rows)
    warning_count = sum(row["重要度"] == "警告" for row in finding_rows)
    columns = st.columns(4)
    with columns[0]:
        st.metric("指摘", len(finding_rows))
    with columns[1]:
        st.metric("エラー", error_count)
    with columns[2]:
        st.metric("警告", warning_count)
    with columns[3]:
        st.metric("修正候補", len(revision_rows))

    with st.expander(f"指摘一覧 ({len(finding_rows)})", expanded=True):
        if finding_rows:
            st.dataframe(
                finding_rows,
                column_config={
                    "重要度": st.column_config.TextColumn("重要度", width="small"),
                    "カテゴリ": st.column_config.TextColumn("カテゴリ", width="medium"),
                    "対象": st.column_config.TextColumn("対象", width="medium"),
                    "原文": st.column_config.TextColumn("原文", width="large"),
                    "内容": st.column_config.TextColumn("内容", width="large"),
                },
                hide_index=True,
                height=min(460, max(150, 38 + len(finding_rows) * 35)),
            )
        else:
            st.success("指摘はありません。")

    with st.expander(f"修正候補一覧 ({len(revision_rows)})", expanded=True):
        if revision_rows:
            st.dataframe(
                revision_rows,
                column_config={
                    "候補ID": st.column_config.TextColumn("候補ID", width="medium"),
                    "対象": st.column_config.TextColumn("対象", width="medium"),
                    "現在の訳": st.column_config.TextColumn("現在の訳", width="large"),
                    "提案訳": st.column_config.TextColumn("提案訳", width="large"),
                },
                hide_index=True,
                height=min(460, max(150, 38 + len(revision_rows) * 35)),
            )
        else:
            st.caption("修正候補はありません。")
    for artifact in record.outputs:
        path = _valid_artifact(entry.record_path.parent, artifact)
        if path is None:
            st.error("成果物が欠落または変更されています。")
            continue
        value = path.read_bytes()
        reviewed = load_model(path, ReviewResult)
        unmatched = [
            {
                "原文ID": ", ".join(group.source_ids),
                "訳文ID": ", ".join(group.translation_ids),
                "状態": group.kind,
                "理由": group.reason or "",
            }
            for group in reviewed.groups
            if group.kind != "matched"
        ]
        if unmatched:
            st.subheader("未対応箇所")
            st.dataframe(unmatched, hide_index=True)
        st.download_button(
            "Review結果JSONをdownload",
            value,
            file_name=path.name,
            mime="application/json",
        )


def _render_upgrade_output(entry: HistoryEntry, record: UpgradeRecord) -> None:
    """検証済み変更箇所・修正提案の全件と結果JSONを表示する。

    Args:
        entry: 表示する処理履歴。
        record: 成果物hashを持つ成功記録。
    """
    root = entry.record_path.parent
    documents = {
        role: _load_first_document(
            root, [f"tasks/12-load/{role.replace('_', '-')}/document.json"]
        )
        for role in ("source_v1", "source_v2", "translation_v1")
    }
    indices = {
        role: document.unit_index() if document else {}
        for role, document in documents.items()
    }
    for artifact in record.outputs:
        path = _valid_artifact(root, artifact)
        if path is None:
            st.error("成果物が欠落または変更されています。")
            continue
        plan = load_model(path, UpgradePlan)
        rows = [
            {
                "変更ID": item.id,
                "種類": item.kind,
                "英語旧版": _unit_text(
                    item.source_v1_ids, indices["source_v1"], "source"
                )
                or "該当なし",
                "日本語旧訳": _unit_text(
                    item.translation_v1_ids, indices["translation_v1"], "source"
                )
                or "対応訳なし",
                "英語新版": _unit_text(
                    item.source_v2_ids, indices["source_v2"], "source"
                )
                or "該当なし",
                "変更概要": item.summary,
                "修正提案": item.suggested_translation or item.summary,
            }
            for item in plan.changes
        ]
        if rows:
            st.dataframe(rows, hide_index=True)
        else:
            st.success("変更箇所なし")
        st.download_button(
            "Upgrade結果JSONをdownload",
            path.read_bytes(),
            file_name=path.name,
            mime="application/json",
        )


def _render_resume_uploads(entry: HistoryEntry) -> list[Path] | None:
    """保存済み入力がない処理に種類別の再upload formを表示する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。

    Returns:
        list[Path] | None: 保存済み入力がない処理に種類別の再upload formを表示する。
    """

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
            type=["pdf"],
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


def _render_record(entry: HistoryEntry) -> None:
    """最上位記録のProgressBar、詳細および比較TextAreaを表示する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。
    """

    record = entry.record
    if record is None:
        st.error(entry.error or "処理記録を読み込めません。")
        return
    started = record.created_at
    ended = record.updated_at if record.status != "processing" else datetime.now(UTC)
    elapsed = max(int((ended - started).total_seconds()), 0)
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    left, right = st.columns(2)
    left.metric("開始時刻", started.astimezone().strftime("%Y-%m-%d %H:%M:%S"))
    right.metric("実行時間", f"{hours:02}:{minutes:02}:{seconds:02}")
    if isinstance(record, (TranslationRecord, ReviewRecord, UpgradeRecord)):
        _render_task_progress(entry, record)
    else:
        completed = int(record.status == "succeeded")
        status = "completed" if completed else record.status
        st.progress(
            float(completed),
            text=f"1 / 1 - REGISTER - {status}",
        )
        with st.expander("進捗詳細", expanded=False, icon=":material/analytics:"):
            st.caption("LLM進捗はありません。")
