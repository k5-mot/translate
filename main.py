"""translate utilityのStreamlit UI。"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import streamlit as st

from translate.common.lifecycle import (
    PublicRunError,
    ResumeRejectedError,
    candidates_for,
    execute_public_run,
    export_run,
    prepare_run,
    run_size,
)
from translate.common.redaction import safe_error, safe_failure_reason
from translate.common.runs import Operation, RunRepository
from translate.common.settings import Backend, Settings, load_settings
from translate.common.workspace import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable

    from streamlit.runtime.uploaded_file_manager import UploadedFile

    from translate.common.progress import ProgressCallback, ProgressEvent
    from translate.common.runs import RunRecord


def _save(upload: UploadedFile, directory: Path) -> Path:
    """Upload名の末尾要素だけを一時保存先に使い、受信済みbyte列を原子的に保存する。"""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / Path(upload.name).name
    atomic_write_bytes(path, upload.getvalue())
    return path


def _progress_callback() -> Callable[[ProgressEvent], None]:
    """Streamlitの進捗表示を作り、同じ表示部品を更新する通知関数を返す。"""

    bar = st.progress(0.0)
    status = st.empty()

    def callback(event: ProgressEvent) -> None:
        """通知された完了数と総数を進捗率に変換し、Taskとメッセージを画面へ反映する。"""

        bar.progress(event.current / event.total)
        status.write(f"[{event.current}/{event.total}] {event.task}: {event.message}")

    return callback


def _resume_choice(  # noqa: PLR0913, PLR0917
    repository: RunRepository,
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend,
    key: str,
    source_id: str | None = None,
) -> str | None:
    """新規を既定値に同一入力候補と互換性差分を表示し、選択された既存IDまたはNoneを返す。"""

    candidates = candidates_for(
        repository, operation, inputs, settings, backend, source_id
    )
    choices = ["新規Run", *(candidate.record.run_id for candidate in candidates)]
    choice = st.selectbox("実行方法", choices, key=f"{key}-run-choice")
    for candidate in candidates:
        state = "互換・Resume可能" if candidate.compatibility.compatible else "非互換"
        st.caption(
            f"{candidate.record.run_id} | {candidate.record.status} | {state} | "
            f"{candidate.record.updated_at.isoformat()}"
        )
        for reason in candidate.compatibility.reasons:
            st.caption(f"差分: {reason}")
    if choice == "新規Run":
        return None
    return str(choice)


def _execute_ui(  # noqa: PLR0913, PLR0917
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend,
    key: str,
    source_id: str | None = None,
) -> tuple[str, tuple[Path, ...]] | None:
    """開始操作とResume確認を受けて共通処理を実行し、失敗は画面表示、成功は成果物を返す。"""

    repository = RunRepository(settings.runs_dir)
    resume_id = _resume_choice(
        repository, operation, inputs, settings, backend, key, source_id
    )
    confirmed = resume_id is None or st.checkbox(
        f"Run {resume_id} のResumeを確認しました",
        key=f"{key}-resume-confirm",
    )
    if not st.button(
        "処理を開始",
        type="primary",
        disabled=not confirmed,
        key=f"{key}-start",
    ):
        return None
    try:
        record, outputs = _run_selected(
            operation,
            inputs,
            settings,
            backend,
            resume_id,
            _progress_callback(),
            source_id,
        )
    except ResumeRejectedError as error:
        st.error(str(error))
        return None
    except PublicRunError as error:
        st.error(str(error))
        return None
    except Exception as error:  # noqa: BLE001
        st.error(safe_failure_reason(error))
        return None
    st.success(f"完了: {record.run_id}")
    st.session_state["last_run_id"] = record.run_id
    return record.run_id, outputs


def _run_selected(  # noqa: PLR0913, PLR0917
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend,
    resume_id: str | None,
    callback: ProgressCallback | None = None,
    source_id: str | None = None,
) -> tuple[RunRecord, tuple[Path, ...]]:
    """UIで確定した新規/Resume選択を共通Lifecycleへ委譲する。"""

    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(
        repository,
        operation,
        inputs,
        settings,
        backend,
        resume_id,
        source_id,
    )
    return execute_public_run(repository, prepared, settings, backend, callback)


def _downloads(outputs: tuple[Path, ...], key: str) -> None:
    """成果物のbyte列を読込み、各Fileに重複しないkeyのダウンロードボタンを設ける。"""

    for index, output in enumerate(outputs):
        st.download_button(
            f"{output.name} をダウンロード",
            output.read_bytes(),
            file_name=output.name,
            key=f"{key}-download-{index}",
        )


def _translation() -> None:
    """PDFと翻訳backendを受け取り、一時入力を介して共有保存先で翻訳し成果物を提供する。"""

    source = st.file_uploader("英語PDF", type=["pdf"], key="translate-source")
    backend = cast(
        "Backend",
        st.segmented_control(
            "翻訳バックエンド",
            ["llm", "libretranslate"],
            default="llm",
            key="translate-backend",
        ),
    )
    if source is None:
        return
    try:
        settings = load_settings("translate", backend)
    except ValueError as error:
        st.error(safe_error(error))
        return
    with tempfile.TemporaryDirectory(prefix="translate-ui-") as temporary:
        source_path = _save(source, Path(temporary))
        result = _execute_ui(
            "translate", {"source": source_path}, settings, backend, "translate"
        )
        if result is not None:
            _downloads(result[1], "translate")


def _review() -> None:
    """原文と訳文のPDFを別の一時directoryに保存し、比較処理と成果物の取得画面を提供する。"""

    source = st.file_uploader("英語PDF", type=["pdf"], key="review-source")
    target = st.file_uploader("日本語PDF", type=["pdf"], key="review-target")
    if source is None or target is None:
        return
    try:
        settings = load_settings("review")
    except ValueError as error:
        st.error(safe_error(error))
        return
    with tempfile.TemporaryDirectory(prefix="review-ui-") as temporary:
        root = Path(temporary)
        inputs = {
            "source_en": _save(source, root / "source"),
            "translation_ja": _save(target, root / "target"),
        }
        result = _execute_ui("review", inputs, settings, "llm", "review")
        if result is not None:
            _downloads(result[1], "review")


def _register() -> None:
    """参照文書と登録元IDの置換確認を受け取り、共通の登録処理へ渡す。"""

    uploads = st.file_uploader(
        "参照文書",
        type=["pdf", "docx", "pptx", "md", "markdown", "txt"],
        accept_multiple_files=True,
        key="register-sources",
    )
    if not uploads:
        return
    default_source_id = ",".join(sorted(upload.name for upload in uploads))
    source_id = st.text_input(
        "登録元ID",
        value=default_source_id,
        key="register-source-id",
        help="同じIDで再登録すると旧revisionを置換します。",
    ).strip()
    confirmed = st.checkbox(
        f"登録元ID {source_id or '(未指定)'} の登録・置換を確認しました",
        key="register-source-confirm",
    )
    if not source_id or not confirmed:
        return
    try:
        settings = load_settings("register")
    except ValueError as error:
        st.error(safe_error(error))
        return
    with tempfile.TemporaryDirectory(prefix="register-ui-") as temporary:
        root = Path(temporary)
        inputs = {
            f"reference-{index:04d}": _save(upload, root)
            for index, upload in enumerate(uploads, 1)
        }
        result = _execute_ui("register", inputs, settings, "llm", "register", source_id)
        if result is not None:
            _downloads(result[1], "register")


def _convert() -> None:
    """Markdownと任意の参照DOCXを別々の一時directoryへ保存し、共通変換処理へ渡す。"""

    source = st.file_uploader("Markdown", type=["md"], key="convert-source")
    reference_doc = st.file_uploader(
        "参照DOCX(省略時は同梱template)",
        type=["docx"],
        key="convert-reference-doc",
    )
    if source is None:
        return
    settings = load_settings("convert")
    with tempfile.TemporaryDirectory(prefix="convert-ui-") as temporary:
        root = Path(temporary)
        source_path = _save(source, root / "source")
        inputs = {"source": source_path}
        if reference_doc is not None:
            inputs["reference_doc"] = _save(reference_doc, root / "template")
        result = _execute_ui("convert", inputs, settings, "llm", "convert")
        if result is not None:
            _downloads(result[1], "convert")


def _run_management() -> None:  # noqa: C901, PLR0912
    """保存済みRunの状態と成果物を表示し、明示されたexport・確認済み削除を実行する。"""

    settings = load_settings("convert")
    repository = RunRepository(settings.runs_dir)
    scan = repository.list_runs()
    with st.expander("Run管理", expanded=True):
        for warning in scan.warnings:
            st.warning(warning)
        if not scan.records:
            st.caption("保存済みRunはありません")
            return
        record_by_id = {record.run_id: record for record in scan.records}
        selected = st.selectbox(
            "Run一覧",
            list(record_by_id),
            format_func=lambda run_id: (
                f"{run_id} | {record_by_id[run_id].status} | "
                f"{record_by_id[run_id].operation}"
            ),
            key="manage-run",
        )
        record = record_by_id[selected]
        st.write(
            {
                "status": record.status,
                "operation": record.operation,
                "inputs": [item.name for item in record.inputs],
                "updated_at": record.updated_at.isoformat(),
                "last_task": record.last_task,
                "fingerprint": record.fingerprint,
                "size": run_size(repository, selected),
            }
        )
        for index, output in enumerate(
            path
            for path in repository.paths(selected).outputs.rglob("*")
            if path.is_file()
        ):
            st.download_button(
                f"{output.name} をダウンロード",
                output.read_bytes(),
                file_name=output.name,
                key=f"manage-download-{selected}-{index}",
            )
        export_path = st.text_input("Server上のexport先", key="manage-export-path")
        if st.button(
            "成果物をexport",
            disabled=record.status != "completed" or not export_path,
            key="manage-export",
        ):
            try:
                exported = export_run(repository, selected, Path(export_path))
            except Exception as error:  # noqa: BLE001
                st.error(safe_error(error))
            else:
                st.success(f"{len(exported)} file(s) exported")
        confirmed = st.checkbox(
            f"Run {selected} の削除を確認しました",
            key=f"manage-delete-confirm-{selected}",
        )
        if st.button(
            "Runを削除",
            disabled=not confirmed or record.status == "running",
            key=f"manage-delete-{selected}",
        ):
            try:
                repository.delete(selected)
            except Exception as error:  # noqa: BLE001
                st.error(safe_error(error))
            else:
                st.success(f"削除しました: {selected}")


def main() -> None:
    """選択された操作と共有Run管理を描画する。"""

    st.set_page_config(page_title="PDF翻訳", page_icon="📘")
    st.title("PDF翻訳ユーティリティ")
    _run_management()
    operation = st.selectbox(
        "操作",
        ["PDF翻訳", "英日PDF比較レビュー", "Qdrant参照文書登録", "Markdown→DOCX"],
        key="operation",
    )
    {
        "PDF翻訳": _translation,
        "英日PDF比較レビュー": _review,
        "Qdrant参照文書登録": _register,
        "Markdown→DOCX": _convert,
    }[operation]()


if __name__ == "__main__":
    start = time.perf_counter()
    try:
        main()
    finally:
        end = time.perf_counter()
        print(f"[TIME] TOTAL: {end - start:.3f} s")  # noqa: T201
