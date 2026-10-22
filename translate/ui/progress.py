"""Streamlit UI progress module."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import streamlit as st

from translate.adapters.artifact_store import (
    ArtifactError,
    load_model,
    sha256_file,
)
from translate.models.artifacts import (
    ArtifactFile,
    DoclingProgress,
    ReviewRecord,
    SplitManifest,
    TaskName,
    TaskState,
    TranslationRecord,
)
from translate.models.upgrade import (
    UpgradeRecord,
)

from .comparisons import (
    _llm_calls,
    _render_latest_comparison,
    _render_review_context,
    _render_upgrade_context,
)
from .history import HistoryEntry, _task_stages
from .types import _MARKDOWN_IMAGE_BLOCK


def _task_progress(
    root: Path,
    record: TranslationRecord | ReviewRecord | UpgradeRecord,
) -> tuple[int, int, str]:
    """固定Task列の完了数、総数、実行中表示名を返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        record (TranslationRecord | ReviewRecord | UpgradeRecord): 状態またはTask情報を更新する処理Record。

    Returns:
        tuple[int, int, str]: 固定Task列の完了数、総数、実行中表示名を返す。
    """

    stages = _task_stages(record)
    states = {state.task: state for state in record.tasks}
    completed = sum(
        states.get(task) is not None
        and states[task].status in {"succeeded", "skipped"}
        and all(
            _valid_artifact(root, item) is not None for item in states[task].artifacts
        )
        for _, task, _ in stages
    )
    active_state = next(
        (state for state in record.tasks if state.status == "processing"), None
    )
    active = "-"
    if active_state is not None:
        active = active_state.task.value.replace("_", "-")
        active = next(
            (label for label, task, _ in stages if task == active_state.task), active
        )
    return completed, len(stages), active


def _render_markdown_preview(markdown: Path, value: str) -> None:
    """Markdownの相対画像を安全なStreamlit画像へ置換してpreviewする。

    Args:
        markdown (Path): DOCX変換またはPreview対象のMarkdown Path。
        value (str): 相対画像Linkを置換して表示するMarkdown本文。
    """

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


def _render_task_progress(
    entry: HistoryEntry, record: TranslationRecord | ReviewRecord | UpgradeRecord
) -> None:
    """固定Task列のProgressBarとLLM Call数を表示する。

    Args:
        entry (HistoryEntry): 表示または操作対象の処理履歴。
        record (TranslationRecord | ReviewRecord | UpgradeRecord): 状態またはTask情報を更新する処理Record。
    """

    root = entry.record_path.parent
    completed, total, _active = _task_progress(root, record)
    if record.status == "succeeded" and not record.tasks:
        completed = total
    active_state = next(
        (task for task in record.tasks if task.status == "processing"), None
    )
    visible_state = active_state
    if visible_state is None and record.tasks:
        visible_state = record.tasks[-1]
    stages = _task_stages(record)
    stage = next(
        (
            (index, label)
            for index, (label, task, _) in enumerate(stages, 1)
            if visible_state is not None and task == visible_state.task
        ),
        (min(completed + 1, len(stages)), stages[min(completed, len(stages) - 1)][0]),
    )
    task_number, task_label = stage
    task_status = visible_state.status if visible_state is not None else record.status
    if task_status in {"succeeded", "skipped"}:
        task_status = "completed"
    if active_state is None and completed == 0 and not record.tasks:
        task_status = "pending"
    detail = f"{task_number} / {total} - {task_label} - {task_status}"
    st.progress(completed / total if total else 0.0, text=detail)
    active_task = active_state.task if active_state is not None else None
    _render_internal_progress(root, record, active_task, active_state)
    _render_latest_comparison(root)
    processing_id = entry.processing_id or entry.kind
    if isinstance(record, ReviewRecord):
        _render_review_context(root, processing_id)
    elif isinstance(record, UpgradeRecord):
        _render_upgrade_context(root, processing_id)


def _render_internal_progress(
    root: Path,
    record: TranslationRecord | ReviewRecord | UpgradeRecord,
    active_task: TaskName | None,
    active_state: TaskState | None,
) -> None:
    if active_task == TaskName.DOCLING and active_state is not None:
        pages_done, pages_total = _docling_progress(root, active_state.started_at)
        st.progress(
            pages_done / pages_total if pages_total else 0.0,
            text=f"{pages_done} / {pages_total} - {active_state.status}",
        )
    elif active_task in {
        TaskName.STRUCTURE,
        TaskName.TRANSLATE,
        TaskName.REVIEW,
        TaskName.DIFF,
    }:
        calls = _llm_calls(root, active_task)
        observed = len(calls)
        completed = sum(call.status in {"succeeded", "partial", "split"} for call in calls)
        progress = next((item for item in record.llm_progress if item.task == active_task), None)
        total = progress.planned_calls if progress is not None else observed
        done = progress.completed_calls if progress is not None else completed
        st.progress(
            min(done / total, 1.0) if total else 0.0,
            text=f"{done} / {total} - processing",
        )


def _render_api_call_counts(root: Path) -> None:
    tasks = (TaskName.STRUCTURE, TaskName.TRANSLATE, TaskName.REVIEW, TaskName.DIFF)
    openai_calls = sum(call.attempts for task in tasks for call in _llm_calls(root, task))
    log = root / "translation.log"
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.is_file() else []
    docling_calls = sum("docling.py:" in line and "convert: Docling started" in line for line in lines)
    qdrant_calls = sum(
        "qdrant.py:" in line
        and ("Qdrant registration started" in line or "Qdrant search completed" in line)
        for line in lines
    )
    st.caption(f"OpenAI 呼び出し: {openai_calls}")
    st.caption(f"Docling 呼び出し: {docling_calls}")
    st.caption(f"Qdrant 呼び出し: {qdrant_calls}")


def _valid_artifact(root: Path, artifact: ArtifactFile) -> Path | None:
    """Artifactが処理directory内でsizeとhashに一致する場合だけpathを返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        artifact (ArtifactFile): Path、SizeおよびHashを検証する成果物情報。

    Returns:
        Path | None: Artifactが処理directory内でsizeとhashに一致する場合だけpathを返す。
    """

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


def _docling_progress(root: Path, started_at: datetime) -> tuple[int, int]:
    """今回のDOCLING実行で処理したページ数と総ページ数を返す。"""

    completed = 0
    total = 0
    for path in (root / "tasks/00-split").glob("**/manifest.json"):
        try:
            manifest = load_model(path, SplitManifest)
        except ArtifactError:
            continue
        part_count = len(manifest.parts)
        total += manifest.total_pages
        role = path.parent.name
        progress_path = root / "tasks/01-docling" / role / "docling-progress.json"
        try:
            if progress_path.stat().st_mtime < started_at.timestamp():
                continue
        except OSError:
            continue
        try:
            progress = load_model(progress_path, DoclingProgress)
        except ArtifactError:
            continue
        if progress.total == part_count and progress.completed <= part_count:
            completed += sum(
                part.page_end - part.page_start + 1
                for part in manifest.parts[: progress.completed]
            )
    return completed, total


def _preview_image_path(markdown: Path, target: str) -> Path | None:
    """Markdown基準の相対画像をpreview directory内の実fileへ限定する。

    Args:
        markdown (Path): DOCX変換またはPreview対象のMarkdown Path。
        target (str): Markdown画像Linkから取得した相対Path。

    Returns:
        Path | None: Markdown基準の相対画像をpreview directory内の実fileへ限定する。
    """

    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    root = markdown.parent.resolve()
    path = (root / unquote(parsed.path)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path
