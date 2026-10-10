"""Streamlitの固定Task進捗を検証する。"""

import io
import zipfile
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from translate.adapters.docling import DoclingClient
from translate.adapters.llm import LLMOutputTokenExceededError
from translate.artifact_store import load_model, write_model
from translate.common.config import Config
from translate.models.artifacts import (
    ArtifactFile,
    CheckResult,
    DoclingProgress,
    InputFile,
    ProcessingError,
    SplitManifest,
    SplitPart,
    TaskName,
    TaskState,
    TranslationRecord,
)
from translate.tasks.converter.docling import convert
from translate.ui import (
    HistoryEntry,
    WorkerError,
    WorkerRegistry,
    _docling_progress,
    _render_future_error,
    _render_record_actions,
    _task_progress,
)


def _record() -> TranslationRecord:
    """進捗test用の最小Translate記録を返す。"""

    now = datetime.now(UTC)
    return TranslationRecord(
        translation_id="translation-id",
        status="processing",
        source=InputFile(
            role="source",
            logical_path="source.pdf",
            sha256="0" * 64,
            size_bytes=1,
        ),
        tasks=[
            TaskState(
                task=TaskName.SPLIT,
                status="succeeded",
                fingerprint="split",
                started_at=now,
                completed_at=now,
            ),
            TaskState(
                task=TaskName.CHECK,
                status="processing",
                fingerprint="final-check",
                started_at=now,
            ),
        ],
        created_at=now,
        updated_at=now,
    )


def test_translate_progress_counts_check_phases_from_valid_artifacts(
    tmp_path: Path,
) -> None:
    """同名CHECKの初回と最終をArtifactで別々に数える。"""

    check_dir = tmp_path / "review/check"
    write_model(check_dir / "findings.json", CheckResult(findings=[]))

    completed, total, active = _task_progress(tmp_path, _record())

    assert (completed, total) == (2, 17)
    assert active == "CHECK (最終)"

    write_model(check_dir / "final-findings.json", CheckResult(findings=[]))
    completed, total, active = _task_progress(tmp_path, _record())

    assert (completed, total) == (3, 17)
    assert active == "CHECK (最終)"


def test_ui_shows_llm_error_type_and_remedy(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM失敗の種類と対策をUIへ表示する。"""

    messages: list[str] = []
    monkeypatch.setattr("translate.ui.st.error", messages.append)
    future: Future[object] = Future()
    future.set_exception(
        LLMOutputTokenExceededError(
            "出力上限です。対策: TRANSLATE_OUTPUT_TOKENSを増やす。"
        )
    )

    _render_future_error(future)

    assert "LLMOutputTokenExceededError" in messages[0]
    assert "対策: TRANSLATE_OUTPUT_TOKENS" in messages[0]


def test_record_error_does_not_repeat_worker_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """記録にある具体的な対策を、汎用WorkerErrorで重複表示しない。"""

    record = _record().model_copy(
        update={
            "status": "failed",
            "error": ProcessingError(
                code="task_failed",
                message="出力上限です。対策: TRANSLATE_OUTPUT_TOKENSを増やす。",
                cause_type="LLMOutputTokenExceededError",
                retryable=True,
            ),
        }
    )
    entry = HistoryEntry(
        kind="translate",
        record_path=tmp_path / "translation.json",
        updated_at=record.updated_at,
        record=record,
    )
    future: Future[object] = Future()
    future.set_exception(WorkerError("LLMOutputTokenExceededError"))
    registry = WorkerRegistry()
    monkeypatch.setattr(registry, "future", lambda _: future)
    monkeypatch.setattr("translate.ui._render_resume", lambda *_: None)
    monkeypatch.setattr("translate.ui._render_history_delete", lambda *_: None)
    messages: list[str] = []
    monkeypatch.setattr("translate.ui.st.error", messages.append)

    _render_record_actions(entry, registry)

    assert len(messages) == 1
    assert "対策: TRANSLATE_OUTPUT_TOKENS" in messages[0]


def test_docling_progress_sums_pdfs_across_inputs(tmp_path: Path) -> None:
    """複数入力の分割PDF数を合算し、今回の完了件数だけ表示する。"""

    for role, count, completed in (("source", 2, 2), ("translation", 3, 1)):
        directory = tmp_path / "converter" / role
        write_model(
            directory / "split/manifest.json",
            SplitManifest(
                source_sha256="0" * 64,
                total_pages=count,
                parts=[
                    SplitPart(
                        number=index,
                        page_start=index,
                        page_end=index,
                        file=ArtifactFile(
                            relative_path=f"converter/{role}/split/part-{index}.pdf",
                            sha256="0" * 64,
                            size_bytes=1,
                        ),
                    )
                    for index in range(1, count + 1)
                ],
            ),
        )
        write_model(
            directory / "docling-progress.json",
            DoclingProgress(completed=completed, total=count),
        )

    future_start = datetime.now(UTC) + timedelta(seconds=1)
    assert _docling_progress(tmp_path, future_start) == (0, 5)
    assert _docling_progress(tmp_path, datetime.fromtimestamp(0, UTC)) == (3, 5)


def test_docling_conversion_publishes_progress_after_each_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docling処理中に0件から各PDF完了件数へ進捗が更新される。"""

    parts = [
        SplitPart(
            number=index,
            page_start=index,
            page_end=index,
            file=ArtifactFile(
                relative_path=f"converter/split/part-{index}.pdf",
                sha256="0" * 64,
                size_bytes=1,
            ),
        )
        for index in (1, 2)
    ]
    for part in parts:
        source = tmp_path / part.file.relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"pdf")
    manifest = SplitManifest(source_sha256="0" * 64, total_pages=2, parts=parts)
    progress_path = tmp_path / "converter/docling-progress.json"
    observed: list[tuple[int, int]] = []
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr("document.json", "{}")

    def fake_convert(
        _self: DoclingClient, source: Path, _poll_interval: float = 1.0
    ) -> tuple[bytes, str, int]:
        """実際の通信前に公開済み進捗を採取してZIPを返す。"""

        progress = load_model(progress_path, DoclingProgress)
        observed.append((progress.completed, progress.total))
        return archive.getvalue(), source.stem, 1

    monkeypatch.setattr(DoclingClient, "convert", fake_convert)
    convert(
        manifest,
        tmp_path / "converter/docling",
        tmp_path,
        Config(docling_server_url="http://localhost"),
    )

    assert observed == [(0, 2), (1, 2)]
    assert load_model(progress_path, DoclingProgress).completed == 2
