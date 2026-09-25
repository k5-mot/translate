"""比較WorkflowのTask node分割とResumeを検証する。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START

from translate.common.progress import bind_task_status
from translate.common.workspace import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)
from translate.document import Document, Page
from translate.workflows import comparison_review

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
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
    """左右7 Taskと後続4 Taskのnode集合および左右を逐次処理する接続を検査する。"""

    graph = comparison_review.build_graph(settings_factory())

    assert set(graph.nodes) == EXPECTED_NODES
    assert (START, "source_split") in graph.edges
    assert (START, "target_split") not in graph.edges
    assert ("source_split", "target_split") in graph.edges
    assert ("target_split", "source_docling") in graph.edges
    assert ("source_load", "target_docling") in graph.edges
    assert ("target_load", "align") in graph.edges
    assert not graph.waiting_edges


@pytest.mark.parametrize(
    ("failed_role", "failed_task"),
    [("source_en", "SOURCE-SPLIT"), ("translation_ja", "TARGET-SPLIT")],
)
def test_comparison_split_failure_defaults_to_its_input_role(
    failed_role: str,
    failed_task: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """下位Errorに対象がなくてもSPLITは対応する入力roleへ帰属する。"""

    statuses: list[TaskStatusEvent] = []

    def fake_split(
        _source: Path, output_dir: Path, _pages: int, *, role: str
    ) -> dict[str, list[dict[str, str]]]:
        """
        指定roleのSPLITだけを対象情報なしで失敗させ、他方はpartを保存して失敗帰属を検証
        する。
        """

        if role == failed_role:
            message = "private input body"
            raise RuntimeError(message)
        part = output_dir / "part.pdf"
        atomic_write_bytes(part, b"part")
        return {"parts": [{"path": str(part)}]}

    monkeypatch.setattr(comparison_review.split, "run", fake_split)
    source = tmp_path / "source.pdf"
    target = tmp_path / "target.pdf"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "review-rules.md").write_text("rules", encoding="utf-8")

    with bind_task_status(statuses.append), pytest.raises(RuntimeError):
        comparison_review.run(
            source,
            target,
            tmp_path / "review.md",
            settings_factory(templates_dir=templates),
        )

    failed = [event for event in statuses if event.phase == "failed"]
    assert [(event.task, event.target_id) for event in failed] == [
        (failed_task, failed_role)
    ]


@pytest.mark.parametrize("legacy_checkpoint", [False, True])
@pytest.mark.parametrize("reasoning_mode", ["task-default", "off"])
def test_comparison_resumes_only_failed_side_task(  # noqa: C901, PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    reasoning_mode: str,
    *,
    legacy_checkpoint: bool,
) -> None:
    """片側POSITION失敗後は成功済み反対側Taskを再実行しない。"""

    counts: Counter[str] = Counter()
    events: list[ProgressEvent] = []
    statuses: list[TaskStatusEvent] = []
    observations: list[tuple[str, bool]] = []
    failed_once = False

    @contextmanager
    def fake_observe(
        _settings: Settings,
        name: str,
        *,
        detached: bool = False,
        **_kwargs: object,
    ) -> Iterator[None]:
        """
        観測名とdetached指定を記録し、実SDKを使わずWorkflowとTaskの観測境界を調べる。
        """

        observations.append((name, detached))
        yield

    def side(path: Path) -> str:
        """中間成果物のpathから原文側か訳文側かを判別し、Task呼出数を分けて集計する。"""

        return "source" if "source" in path.parts else "target"

    def fake_split(
        source: Path, output_dir: Path, _pages: int, *, role: str
    ) -> dict[str, list[dict[str, str]]]:
        """入力roleを確認して分割回数を数え、後続nodeへ渡すpartのダミーを保存する。"""

        name = source.stem
        assert role in {"source_en", "translation_ja"}
        counts[f"{name}_split"] += 1
        part = output_dir / "part.pdf"
        atomic_write_bytes(part, b"part")
        return {"parts": [{"path": str(part)}]}

    def fake_docling(
        _parts: list[Path], output_dir: Path, _settings: object
    ) -> list[Path]:
        """側別にDocling呼出数を数え、外部送信なしで応答ZIPの代替Fileを作る。"""

        branch = side(output_dir)
        counts[f"{branch}_docling"] += 1
        archive = output_dir / "result.zip"
        atomic_write_bytes(archive, b"archive")
        return [archive]

    def fake_unpack(archives: list[Path]) -> list[Path]:
        """側別に展開回数を数え、応答ZIPの隣へ文書JSONの代替Fileを作る。"""

        branch = side(archives[0])
        counts[f"{branch}_unpack"] += 1
        document = archives[0].parent / "document.json"
        atomic_write_json(document, {})
        return [document]

    def passthrough(name: str) -> Callable[..., Path]:
        """Task名に応じた呼出数の記録と一度だけのPOSITION障害を持つdoubleを返す。"""

        def task(_source: Path, output_dir: Path, *_args: object) -> Path:
            """
            訳文側POSITIONの初回だけ失敗し、再開時はJSONを返して再実行範囲を検証する。
            """

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
        """側別に統合回数を数え、内容抽出に依存しない文書JSONを保存する。"""

        branch = side(output_dir)
        counts[f"{branch}_merge"] += 1
        result = output_dir / "document.json"
        atomic_write_json(result, {})
        return result

    def fake_load(_source: Path, output_dir: Path) -> Document:
        """側別にLOAD回数を数え、後続Graphが読める共通文書Artifactを保存する。"""

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
        """対応付けの呼出数を数え、空のGroup Artifactでreportまで接続する。"""

        counts["align"] += 1
        atomic_write_json(output_dir / "alignment.json", [])
        return []

    def fake_check(
        _document: object, _glossary: object, _output_dir: Path
    ) -> dict[int, list[object]]:
        """決定的検査の呼出数を数え、外部要因のない指摘0件を返す。"""

        counts["check"] += 1
        return {}

    def fake_review(*_args: object) -> dict[int, list[object]]:
        """モデルを呼ばずReviewの実行数を数え、指摘0件を返す。"""

        counts["review"] += 1
        return {}

    def fake_report(
        _groups: object,
        _checks: object,
        _reviews: object,
        output: Path,
        _work: Path,
    ) -> Path:
        """
        公開reportの出力回数を数え、再開後に生成を確認できる固定Markdownを保存する。
        """

        counts["report"] += 1
        atomic_write_text(output, "# report\n")
        return output

    monkeypatch.setattr(comparison_review.split, "run", fake_split)
    monkeypatch.setattr(comparison_review, "observe", fake_observe)
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
    settings: Settings = settings_factory(
        templates_dir=templates, reasoning_mode=reasoning_mode
    )
    source = tmp_path / "source.pdf"
    target = tmp_path / "target.pdf"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    output = tmp_path / "review.md"

    with bind_task_status(statuses.append):
        # 既存serializerのDBと新しいDBの両方を、再接続した製品入口からResumeする。
        with monkeypatch.context() as initial_patch:
            if legacy_checkpoint:
                initial_patch.setattr(
                    comparison_review, "open_checkpoint", SqliteSaver.from_conn_string
                )
            with pytest.raises(RuntimeError, match="POSITION"):
                comparison_review.run(source, target, output, settings, events.append)
        result = comparison_review.run(source, target, output, settings, events.append)
    metadata = json.loads((tmp_path / ".workspace/workflow.json").read_text())
    thread_id = metadata.pop("thread_id")
    assert (
        thread_id
        == hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    )
    assert metadata.pop("llm_reasoning_mode", "task-default") == reasoning_mode
    legacy_id = hashlib.sha256(
        json.dumps(metadata, sort_keys=True).encode()
    ).hexdigest()
    assert (thread_id == legacy_id) == (reasoning_mode == "task-default")

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
    assert {name for name, _detached in observations} >= {
        "workflow.comparison-review",
        "task.source-split",
        "task.report",
    }
    assert all(detached for _name, detached in observations)
