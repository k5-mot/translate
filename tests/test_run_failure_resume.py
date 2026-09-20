"""外部障害後のRun状態、Qdrant変更許容およびResumeを検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from translate.common.lifecycle import execute_run, prepare_run
from translate.common.progress import ProgressEvent
from translate.common.runs import RunRepository
from translate.common.workspace import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.progress import ProgressCallback
    from translate.common.settings import Backend, Settings


def _templates(root: Path) -> Path:
    root.mkdir()
    for name in ("structure", "translation", "review"):
        (root / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (root / "glossary.csv").write_text(
        "english-short,japanese-short\n", encoding="utf-8"
    )
    (root / "template.docx").write_bytes(b"template")
    return root


@pytest.mark.integration
def test_external_failure_stops_run_and_resumes_after_qdrant_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """検索失敗をfailedで保持し、Qdrant変更後も同じArtifactから再開する。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="revision-a",
        embedding_model="embedding",
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings, "llm")
    attempts = 0

    def workflow(
        _source: Path,
        output_dir: Path,
        _backend: Backend,
        _settings: Settings,
        callback: ProgressCallback | None,
        workspace_dir: Path | None,
    ) -> Path:
        nonlocal attempts
        attempts += 1
        assert workspace_dir is not None
        completed = workspace_dir / "review" / "complete.json"
        if not completed.exists():
            atomic_write_bytes(completed, b"complete task artifact")
        if callback is not None:
            callback(ProgressEvent("REVIEW", 11, 17, "REVIEW 完了"))
        if attempts == 1:
            message = "Qdrant search exhausted"
            raise OSError(message)
        result = output_dir / "document.ja.docx"
        atomic_write_bytes(result, completed.read_bytes())
        if callback is not None:
            callback(ProgressEvent("DOCX", 17, 17, "DOCX 完了"))
        return result

    monkeypatch.setattr("translate.common.lifecycle.run_translation", workflow)

    with pytest.raises(OSError, match="Qdrant"):
        execute_run(repository, prepared, settings)

    failed = repository.load(prepared.record.run_id)
    assert failed.status == "failed"
    assert failed.last_task == "REVIEW"
    assert (
        repository.paths(failed.run_id)
        .workspace.joinpath("review", "complete.json")
        .is_file()
    )

    changed = settings.model_copy(update={"qdrant_collection": "revision-b"})
    resumed = prepare_run(
        repository,
        "translate",
        {"source": source},
        changed,
        "llm",
        failed.run_id,
    )
    events: list[ProgressEvent] = []
    completed, outputs = execute_run(
        repository, resumed, changed, callback=events.append
    )

    assert completed.status == "completed"
    assert completed.run_id == failed.run_id
    assert outputs[0].read_bytes() == b"complete task artifact"
    assert [event.current for event in events] == [11, 17]
    assert attempts == 2
