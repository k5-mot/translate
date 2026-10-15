"""Taskの保存・再開と失敗状態を統合して検証する。"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from translate.adapters.artifact_store import ArtifactStore, load_model
from translate.common.config import Config
from translate.models.artifacts import InputFile, TaskName, TranslationRecord
from translate.models.document import Document
from translate.pipeline import PipelineRun


def test_task_reuses_matching_input_and_rebuilds_corrupt_artifact(
    tmp_path: Path,
) -> None:
    """入れ子Model入力をhash化し、入力変更・成果物破損だけで再実行する。"""
    now = datetime.now(UTC)
    record = TranslationRecord(
        translation_id="test",
        status="processing",
        source=InputFile(
            role="source", logical_path="source.pdf", sha256="0" * 64, size_bytes=0
        ),
        created_at=now,
        updated_at=now,
    )
    record_path = tmp_path / "translation.json"
    directory = tmp_path / "task"
    output = directory / "result.txt"
    calls = []

    def produce() -> None:
        """公開される成果物を生成し、実行回数を記録する。"""
        calls.append(1)
        directory.mkdir(exist_ok=True)
        output.write_text("complete", encoding="utf-8")

    document = Document()
    execution = PipelineRun(ArtifactStore(record, record_path), Config())
    inputs = {"document": document}
    assert not execution.perform_task(TaskName.LOAD, inputs, [(directory, produce)])
    assert execution.perform_task(TaskName.LOAD, inputs, [(directory, produce)])
    output.write_text("corrupt", encoding="utf-8")
    assert not execution.perform_task(TaskName.LOAD, inputs, [(directory, produce)])
    document.metadata["input-change"] = True
    assert not execution.perform_task(TaskName.LOAD, inputs, [(directory, produce)])
    assert len(calls) == 3
    saved = load_model(record_path, TranslationRecord)
    assert saved.tasks[0].status == "succeeded"

    failure = Mock(side_effect=ValueError("private input"))
    with pytest.raises(ValueError, match="private input"):
        execution.perform_task(
            TaskName.LOAD, {"changed": document}, [(directory, failure)]
        )
    saved = load_model(record_path, TranslationRecord)
    assert saved.status == saved.tasks[0].status == "failed"
    assert "private input" not in record_path.read_text(encoding="utf-8")
