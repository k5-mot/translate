"""Taskの保存・再開と失敗状態を統合して検証する。"""

from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock

import pytest

from translate.adapters.artifact_store import ArtifactStore, load_model, write_model
from translate.adapters.llm import LLMInvalidResponseError
from translate.common.config import Config
from translate.models.artifacts import (
    InputFile,
    LLMCallArtifact,
    ProcessingError,
    TaskName,
    TranslationRecord,
)
from translate.models.document import Document, TextSpan
from translate.models.review import ReviewAssessment, ReviewResponse, ReviewTarget
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


def test_review_splits_target_after_invalid_llm_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeatedly invalid REVIEW output is retried on smaller source/span groups."""
    module = import_module("translate.tasks.41_review")
    task = module.ReviewTask(
        Config(openai_review_model="review-model"), tmp_path, "rules", ""
    )
    now = datetime.now(UTC)
    parent_id = "parent-call"

    def fixed_call_id(*_args: object, **_kwargs: object) -> str:
        return parent_id

    monkeypatch.setattr(module, "llm_call_id", fixed_call_id)
    parent_path = tmp_path / "calls" / parent_id / "call.json"
    write_model(
        parent_path,
        LLMCallArtifact(
            call_id=parent_id,
            task="REVIEW",
            operation="evaluate",
            status="failed",
            fingerprint="0" * 64,
            target_ids=["review:review/unit"],
            attempts=5,
            started_at=now,
            updated_at=now,
            error=ProcessingError(
                code="llm_call_failed", message="invalid response", retryable=True
            ),
        ),
    )
    targets = [
        ReviewTarget(
            id="review/unit",
            source="An English source sentence. " * 80,
            translation="",
            target_ids=["unit"],
            spans=[
                TextSpan(id=f"span-{index}", source=f"訳文断片 {index}。")
                for index in range(8)
            ],
        )
    ]
    calls = 0

    def request(*args: object) -> tuple[str, ReviewResponse]:
        nonlocal calls
        calls += 1
        if calls == 1:
            message = "invalid review response"
            raise LLMInvalidResponseError(message)
        payload = args[4]
        assert isinstance(payload, dict)
        selected = payload["targets"]
        assert isinstance(selected, list)
        response = ReviewResponse(
            assessments=[
                ReviewAssessment(
                    target_id=target["id"],
                    reason="問題なし",
                    verdict="correct",
                    edits=[],
                    category=None,
                    severity=None,
                )
                for target in selected
            ]
        )
        validate = args[8]
        assert callable(validate)
        validate(response)
        return f"child-{calls}", response

    monkeypatch.setattr(task.calls, "request", request)
    result = task.run(
        targets,
        tmp_path,
        client=Mock(),
        publish=False,
        span_owners={f"span-{index}": "unit" for index in range(8)},
    )

    assert calls > 2
    assert result.reviewed_target_ids == ["review/unit"]
    assert load_model(parent_path, LLMCallArtifact).status == "split"
