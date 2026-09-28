"""Streamlitの固定Task進捗を検証する。"""

from datetime import UTC, datetime
from pathlib import Path

from translate.artifact_store import write_model
from translate.models.artifacts import (
    CheckResult,
    InputFile,
    TaskName,
    TaskState,
    TranslationRecord,
)
from translate.ui import _task_progress


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
