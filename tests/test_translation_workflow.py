"""翻訳Workflowの分岐、skip、COVER合流およびResumeを検証する。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from translate.common.progress import bind_task_status
from translate.common.workspace import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)
from translate.document import Document, Finding, Page
from translate.workflows import translation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from translate.common.progress import ProgressEvent, TaskStatusEvent
    from translate.common.settings import Settings


EXPECTED_NODES = {
    "split",
    "docling",
    "unpack",
    "merge",
    "position",
    "normalize",
    "load",
    "structure",
    "translate",
    "translate_lite",
    "check",
    "review",
    "fix",
    "verify",
    "cover",
    "validate",
    "markdown",
    "docx",
}


def test_translation_graph_exposes_each_task_node(
    settings_factory: Callable[..., Settings],
) -> None:
    """Backendを含むTaskが独立nodeである。"""

    assert set(translation.build_graph(settings_factory()).nodes) == EXPECTED_NODES


def test_failed_status_copies_safe_structure_diagnostics() -> None:
    """例外に付けた位置・stage・cause・出力切断理由・usageが失敗Eventへ移る。"""

    error = RuntimeError("raw response")
    error.page = 7  # type: ignore[attr-defined]
    error.target_id = "page/7"  # type: ignore[attr-defined]
    error.stage = "vision-invoke"  # type: ignore[attr-defined]
    error.cause_type = "TypeError"  # type: ignore[attr-defined]
    error.failure_kind = "output-truncated"  # type: ignore[attr-defined]
    error.finish_reason = "length"  # type: ignore[attr-defined]
    error.input_tokens = 10  # type: ignore[attr-defined]
    error.output_tokens = 20  # type: ignore[attr-defined]
    error.total_tokens = 30  # type: ignore[attr-defined]

    status = translation._failed_status("STRUCTURE", error)  # noqa: SLF001

    assert status.page == 7
    assert status.target_id == "page/7"
    assert status.stage == "vision-invoke"
    assert status.cause_type == "TypeError"
    assert status.failure_kind == "output-truncated"
    assert status.finish_reason == "length"
    assert status.input_tokens == 10
    assert status.output_tokens == 20
    assert status.total_tokens == 30


@pytest.mark.parametrize("legacy_checkpoint", [False, True])
@pytest.mark.parametrize("reasoning_mode", ["task-default", "off"])
def test_translation_branches_skip_and_resume_from_cover(  # noqa: C901, PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    reasoning_mode: str,
    *,
    legacy_checkpoint: bool,
) -> None:
    """両Backend、Finding分岐、COVER失敗からのResumeを一貫して処理する。"""

    counts: Counter[str] = Counter()
    llm_events: list[ProgressEvent] = []
    libre_events: list[ProgressEvent] = []
    statuses: list[TaskStatusEvent] = []
    observations: list[tuple[str, bool]] = []
    cover_failed = False
    document = Document(pages=[Page(number=2)])

    @contextmanager
    def fake_observe(
        _settings: Settings,
        name: str,
        *,
        detached: bool = False,
        **_kwargs: object,
    ) -> Iterator[None]:
        """
        実SDKの代わりに観測名とdetached指定を記録し、WorkflowとTaskの観測境界を検証する
        。
        """

        observations.append((name, detached))
        yield

    def fake_split(
        _source: Path, output_dir: Path, _pages: int, *, role: str
    ) -> dict[str, list[dict[str, str]]]:
        """入力roleとbackend別の分割回数を記録し、後続nodeへダミーpartを渡す。"""

        assert role == "source"
        counts[f"{output_dir.parents[1].name}_split"] += 1
        part = output_dir / "part.pdf"
        atomic_write_bytes(part, b"part")
        return {"parts": [{"path": str(part)}]}

    def fake_docling(
        _parts: list[Path], output_dir: Path, _settings: object
    ) -> list[Path]:
        """外部送信をせず応答ZIPの代替Fileを作り、翻訳Graphの接続を検証可能にする。"""

        archive = output_dir / "result.zip"
        atomic_write_bytes(archive, b"archive")
        return [archive]

    def fake_unpack(archives: list[Path]) -> list[Path]:
        """ZIP解析なしで文書JSONを用意し、Taskの実行順の検証に必要なpathを返す。"""

        path = archives[0].parent / "document.json"
        atomic_write_json(path, {})
        return [path]

    def fake_merge(_documents: list[Path], _source: Path, output_dir: Path) -> Path:
        """統合結果の代替JSONを保存し、下流のnodeが参照できるpathを返す。"""

        path = output_dir / "document.json"
        atomic_write_json(path, {})
        return path

    def passthrough(_source: Path, output_dir: Path) -> Path:
        """
        POSITIONとNORMALIZEの代わりにJSONを保存し、分岐・再開Testを文書内容から独立させ
        る。
        """

        path = output_dir / "document.json"
        atomic_write_json(path, {})
        return path

    def fake_load(_source: Path, output_dir: Path) -> Document:
        """後続nodeが読める共通文書Artifactを作り、同じ文書Modelを返す。"""

        atomic_write_json(
            output_dir / "document.json", document.model_dump(mode="json")
        )
        return document

    def fake_structure(
        value: Document,
        _source: Path,
        _rules: str,
        _settings: Settings,
        output_dir: Path,
    ) -> Document:
        """構造推定の呼出数を数え、入力文書を保存して再開後の重複実行を検出する。"""

        counts["structure"] += 1
        atomic_write_json(output_dir / "document.json", value.model_dump(mode="json"))
        return value

    def fake_translate(value: Document, *_args: object) -> Document:
        """
        文書を変更せずLLM翻訳の呼出数だけ数え、backend選択と再開による再実行を検証する。
        """

        counts["llm"] += 1
        return value

    def fake_translate_lite(value: Document, *_args: object) -> Document:
        """
        文書を変更せずLibreTranslateの呼出数だけ数え、排他的なbackend選択を検証する。
        """

        counts["libretranslate"] += 1
        return value

    def fake_check(*_args: object) -> dict[int, list[Finding]]:
        """決定的検査の指摘を0件に固定し、Review結果による分岐だけを試験対象とする。"""

        return {}

    def fake_review(
        _document: Document,
        _checks: object,
        _rules: str,
        _glossary: object,
        _settings: object,
        output_dir: Path,
    ) -> dict[int, list[Finding]]:
        """LLM側だけ指摘を返し、FIX・VERIFY実行と指摘なしskipの両方を検証する。"""

        if output_dir.parents[1].name == "llm":
            return {2: [Finding(kind="test", message="finding")]}
        return {}

    def fake_fix(value: Document, *_args: object) -> Document:
        """
        文書を変更せず修正Taskの呼出数を数え、指摘がある場合だけ実行されるか調べる。
        """

        counts["fix"] += 1
        return value

    def fake_verify(value: Document, *_args: object) -> Document:
        """文書を変更せず修正検証の呼出数を数え、分岐とResumeによる重複実行を調べる。"""

        counts["verify"] += 1
        return value

    def fake_cover(_source: Path, output: Path) -> Path:
        """LLM側の初回COVERだけ失敗させ、再開時とLibre側では代替画像を保存する。"""

        nonlocal cover_failed
        mode = output.parents[2].name
        counts[f"{mode}_cover"] += 1
        if mode == "llm" and not cover_failed:
            cover_failed = True
            msg = "injected COVER failure"
            raise RuntimeError(msg)
        atomic_write_bytes(output, b"png")
        return output

    def fake_validate(value: Document, _assets: Path, output: Path) -> Document:
        """検証成功のreportを保存して文書を返し、Graph終端まで進める。"""

        atomic_write_json(output, {"valid": True})
        return value

    def fake_markdown(_document: Document, output: Path, *_args: object) -> Path:
        """公開直前のMarkdownの代替Fileを保存し、後続DOCX nodeへpathを返す。"""

        atomic_write_text(output, "markdown")
        return output

    def fake_docx(_markdown: Path, output: Path, _template: Path) -> Path:
        """
        固定byte列のDOCX代替成果物を保存し、Workflow完了とResume結果を確認可能にする。
        """

        atomic_write_bytes(output, b"docx")
        return output

    monkeypatch.setattr(translation.split, "run", fake_split)
    monkeypatch.setattr(translation, "observe", fake_observe)
    monkeypatch.setattr(translation.docling, "run", fake_docling)
    monkeypatch.setattr(translation.unpack, "run", fake_unpack)
    monkeypatch.setattr(translation.merge, "run", fake_merge)
    monkeypatch.setattr(translation.position, "run", passthrough)
    monkeypatch.setattr(translation.normalize, "run", passthrough)
    monkeypatch.setattr(translation.load, "run", fake_load)
    monkeypatch.setattr(translation.structure, "run", fake_structure)
    monkeypatch.setattr(translation.translate, "run", fake_translate)
    monkeypatch.setattr(translation.translate_lite, "run", fake_translate_lite)
    monkeypatch.setattr(translation.check, "run", fake_check)
    monkeypatch.setattr(translation.check, "read_glossary", lambda _path: [])
    monkeypatch.setattr(translation.review, "run", fake_review)
    monkeypatch.setattr(translation.fix, "run", fake_fix)
    monkeypatch.setattr(translation.verify, "run", fake_verify)
    monkeypatch.setattr(translation.cover, "run", fake_cover)
    monkeypatch.setattr(translation.validate, "run", fake_validate)
    monkeypatch.setattr(translation.markdown, "run", fake_markdown)
    monkeypatch.setattr(translation.docx, "run", fake_docx)

    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("structure", "translation", "review"):
        (templates / f"{name}-rules.md").write_text("rules", encoding="utf-8")
    settings: Settings = settings_factory(
        templates_dir=templates, reasoning_mode=reasoning_mode
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")

    with bind_task_status(statuses.append):
        # 初回だけ標準serializerを選び、修正前DBも新しい保存境界から再開できるか調べる。
        with monkeypatch.context() as initial_patch:
            if legacy_checkpoint:
                initial_patch.setattr(
                    translation, "open_checkpoint", SqliteSaver.from_conn_string
                )
            with pytest.raises(RuntimeError, match="COVER"):
                translation.run(
                    source, tmp_path / "llm", "llm", settings, llm_events.append
                )
        llm_result = translation.run(
            source, tmp_path / "llm", "llm", settings, llm_events.append
        )
    metadata = json.loads((tmp_path / "llm/.workspace/workflow.json").read_text())
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
    libre_result = translation.run(
        source,
        tmp_path / "libre",
        "libretranslate",
        settings,
        libre_events.append,
    )

    assert llm_result.is_file()
    assert libre_result.is_file()
    assert (tmp_path / "llm" / ".workspace" / "workflow.json").is_file()
    assert not (tmp_path / "llm" / ".workspace" / "run.json").exists()
    assert counts["llm"] == 1
    assert counts["libretranslate"] == 1
    assert counts["fix"] == 1
    assert counts["verify"] == 1
    assert counts["llm_cover"] == 2
    assert counts["libre_cover"] == 1
    assert counts["llm_split"] == 1
    assert any(event.task == "COVER" and event.phase == "failed" for event in statuses)
    assert (
        sum(event.task == "SPLIT" and event.phase == "started" for event in statuses)
        == 1
    )
    assert (
        sum(event.task == "COVER" and event.phase == "started" for event in statuses)
        == 2
    )
    assert [event.current for event in llm_events] == sorted(
        event.current for event in llm_events
    )
    assert llm_events[-1].current == llm_events[-1].total == 17
    assert libre_events[-1].current == libre_events[-1].total == 17
    assert {event.task for event in libre_events if event.level == "skipped"} == {
        "TRANSLATE",
        "FIX",
        "VERIFY",
    }
    assert {name for name, _detached in observations} >= {
        "workflow.pdf-translation",
        "task.structure",
        "task.docx",
    }
    assert all(detached for _name, detached in observations)
