"""比較WorkflowのTask node分割とResumeを検証する。"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pytest

from translate.common.progress import bind_task_status
from translate.common.workspace import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)
from translate.document import Document, Page
from translate.workflows import comparison_review

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.progress import ProgressEvent, TaskStatusEvent
    from translate.common.settings import Settings


EXPECTED_NODES = {
    f"{side}_{task}"
    for side in ("source", "target")
    for task in ("split", "docling", "unpack", "merge", "position", "normalize", "load")
} | {"align", "check", "review", "report"}


def test_comparison_graph_has_independent_branch_nodes(
    settings_factory: Callable[..., Settings],
) -> None:
    """左右7 Taskとjoin後4 Taskを独立nodeとして公開する。"""

    graph = comparison_review.build_graph(settings_factory())

    assert set(graph.nodes) == EXPECTED_NODES


def test_comparison_resumes_only_failed_side_task(  # noqa: C901, PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """片側POSITION失敗後は成功済み反対側Taskを再実行しない。"""

    counts: Counter[str] = Counter()
    events: list[ProgressEvent] = []
    statuses: list[TaskStatusEvent] = []
    failed_once = False

    def side(path: Path) -> str:
        return "source" if "source" in path.parts else "target"

    def fake_split(
        source: Path, output_dir: Path, _pages: int, *, role: str
    ) -> dict[str, list[dict[str, str]]]:
        name = source.stem
        assert role in {"source_en", "translation_ja"}
        counts[f"{name}_split"] += 1
        part = output_dir / "part.pdf"
        atomic_write_bytes(part, b"part")
        return {"parts": [{"path": str(part)}]}

    def fake_docling(
        _parts: list[Path], output_dir: Path, _settings: object
    ) -> list[Path]:
        branch = side(output_dir)
        counts[f"{branch}_docling"] += 1
        archive = output_dir / "result.zip"
        atomic_write_bytes(archive, b"archive")
        return [archive]

    def fake_unpack(archives: list[Path]) -> list[Path]:
        branch = side(archives[0])
        counts[f"{branch}_unpack"] += 1
        document = archives[0].parent / "document.json"
        atomic_write_json(document, {})
        return [document]

    def passthrough(name: str) -> Callable[..., Path]:
        def task(_source: Path, output_dir: Path, *_args: object) -> Path:
            nonlocal failed_once
            branch = side(output_dir)
            counts[f"{branch}_{name}"] += 1
            if branch == "target" and name == "position" and not failed_once:
                failed_once = True
                msg = "injected target POSITION failure"
                raise RuntimeError(msg)
            result = output_dir / "document.json"
            atomic_write_json(result, {})
            return result

        return task

    def fake_merge(_documents: list[Path], _source: Path, output_dir: Path) -> Path:
        branch = side(output_dir)
        counts[f"{branch}_merge"] += 1
        result = output_dir / "document.json"
        atomic_write_json(result, {})
        return result

    def fake_load(_source: Path, output_dir: Path) -> Document:
        branch = side(output_dir)
        counts[f"{branch}_load"] += 1
        document = Document(pages=[Page(number=2)])
        atomic_write_json(
            output_dir / "document.json", document.model_dump(mode="json")
        )
        return document

    def fake_align(
        _source: object, _target: object, output_dir: Path, _settings: object
    ) -> list[object]:
        counts["align"] += 1
        atomic_write_json(output_dir / "alignment.json", [])
        return []

    def fake_check(
        _document: object, _glossary: object, _output_dir: Path
    ) -> dict[int, list[object]]:
        counts["check"] += 1
        return {}

    def fake_review(*_args: object) -> dict[int, list[object]]:
        counts["review"] += 1
        return {}

    def fake_report(
        _groups: object,
        _checks: object,
        _reviews: object,
        output: Path,
        _work: Path,
    ) -> Path:
        counts["report"] += 1
        atomic_write_text(output, "# report\n")
        return output

    monkeypatch.setattr(comparison_review.split, "run", fake_split)
    monkeypatch.setattr(comparison_review.docling, "run", fake_docling)
    monkeypatch.setattr(comparison_review.unpack, "run", fake_unpack)
    monkeypatch.setattr(comparison_review.merge, "run", fake_merge)
    monkeypatch.setattr(comparison_review.position, "run", passthrough("position"))
    monkeypatch.setattr(comparison_review.normalize, "run", passthrough("normalize"))
    monkeypatch.setattr(comparison_review.load, "run", fake_load)
    monkeypatch.setattr(comparison_review.align, "run", fake_align)
    monkeypatch.setattr(comparison_review.check, "run", fake_check)
    monkeypatch.setattr(comparison_review.check, "read_glossary", lambda _path: [])
    monkeypatch.setattr(comparison_review.review, "run", fake_review)
    monkeypatch.setattr(comparison_review.report, "run", fake_report)

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "review-rules.md").write_text("rules", encoding="utf-8")
    settings: Settings = settings_factory(templates_dir=templates)
    source = tmp_path / "source.pdf"
    target = tmp_path / "target.pdf"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    output = tmp_path / "review.md"

    with bind_task_status(statuses.append):
        with pytest.raises(RuntimeError, match="POSITION"):
            comparison_review.run(source, target, output, settings, events.append)
        result = comparison_review.run(source, target, output, settings, events.append)

    assert result == output
    assert output.is_file()
    assert (tmp_path / ".workspace" / "workflow.json").is_file()
    assert not (tmp_path / ".workspace" / "run.json").exists()
    assert counts["source_position"] == 1
    assert counts["target_position"] == 2
    assert counts["source_load"] == 1
    assert counts["align"] == 1
    assert any(
        event.task == "TARGET-POSITION" and event.phase == "failed"
        for event in statuses
    )
    assert (
        sum(
            event.task == "SOURCE-POSITION" and event.phase == "started"
            for event in statuses
        )
        == 1
    )
    assert (
        sum(
            event.task == "TARGET-POSITION" and event.phase == "started"
            for event in statuses
        )
        == 2
    )
    assert [event.current for event in events] == sorted(
        event.current for event in events
    )
    assert events[-1].current == events[-1].total == 18
