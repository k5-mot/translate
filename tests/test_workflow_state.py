"""最小GraphでWorkflowのstate型・path保存とcheckpoint失敗時のArtifactを検査する。"""

from __future__ import annotations

import json
from functools import partial
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from typer.testing import CliRunner

import cli_v1
from translate_v1.common.lifecycle import load_failure
from translate_v1.common.runs import RunRepository
from translate_v1.common.workspace import atomic_directory, atomic_write_bytes
from translate_v1.workflows import comparison_review, translation
from translate_v1.workflows.comparison_review import ComparisonState
from translate_v1.workflows.translation import TranslationState

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate_v1.common.settings import Settings


def _checkpoint(
    state_type: type[TranslationState | ComparisonState],
    initial: dict[str, object],
    database: Path,
) -> bytes:
    """
    指定stateを持つ最小GraphをSQLiteへ保存し、本文混入を調べるためdatabaseのbyte列を返す
    。
    """

    graph = StateGraph(state_type)
    graph.add_node("finish", lambda _state: {"current_task": "TEST"})
    graph.add_edge(START, "finish")
    graph.add_edge("finish", END)
    with SqliteSaver.from_conn_string(str(database)) as saver:
        compiled = graph.compile(checkpointer=saver)
        compiled.invoke(initial, {"configurable": {"thread_id": "test-thread"}})
    return database.read_bytes()


def test_translation_checkpoint_contains_paths_not_document_bodies(
    tmp_path: Path,
) -> None:
    """翻訳state型の本文field不在と、pathを渡した最小GraphのDBに本文がないか検査する。"""

    document = tmp_path / "document.json"
    findings = tmp_path / "findings.json"
    document.write_text("DOCUMENT-BODY-SENTINEL", encoding="utf-8")
    findings.write_text("FINDING-BODY-SENTINEL", encoding="utf-8")
    database = tmp_path / "translation.sqlite"

    raw = _checkpoint(
        TranslationState,
        {
            "source": str(tmp_path / "source.pdf"),
            "output_dir": str(tmp_path),
            "backend": "llm",
            "document_path": str(document),
            "checks_path": str(findings),
            "reviews_path": str(findings),
        },
        database,
    )

    assert b"DOCUMENT-BODY-SENTINEL" not in raw
    assert b"FINDING-BODY-SENTINEL" not in raw
    assert (
        not {"document", "checks", "reviews"} & TranslationState.__annotations__.keys()
    )


@pytest.mark.parametrize("workflow", ["translation", "comparison"])
@pytest.mark.parametrize("saved_mode", ["task-default", "off"])
def test_direct_workflow_rejects_changed_reasoning_before_touching_artifacts(
    tmp_path: Path,
    settings_factory: Callable[..., Settings],
    workflow: str,
    saved_mode: str,
) -> None:
    """直接Workflow呼出しでも、旧cacheやCheckpointに触る前に設定不一致を拒否する。"""

    work = tmp_path / ".workspace"
    work.mkdir()
    saved = {} if saved_mode == "task-default" else {"llm_reasoning_mode": "off"}
    (work / "workflow.json").write_text(json.dumps(saved), encoding="utf-8")
    (work / "checkpoints.sqlite").write_bytes(b"checkpoint sentinel")
    (work / "review.chunks").mkdir()
    (work / "review.chunks/chunk.json").write_bytes(b"chunk sentinel")
    before = {path: path.read_bytes() for path in work.rglob("*") if path.is_file()}
    settings = settings_factory(
        reasoning_mode="off" if saved_mode == "task-default" else "task-default"
    )
    if workflow == "translation":
        with pytest.raises(ValueError, match="LLM_REASONING_MODE"):
            translation.run(tmp_path / "source.pdf", tmp_path, "llm", settings)
    else:
        with pytest.raises(ValueError, match="LLM_REASONING_MODE"):
            comparison_review.run(
                tmp_path / "source.pdf",
                tmp_path / "target.pdf",
                tmp_path / "review.md",
                settings,
            )
    after = {path: path.read_bytes() for path in work.rglob("*") if path.is_file()}
    assert before == after


def test_comparison_checkpoint_contains_paths_not_alignment_or_documents(
    tmp_path: Path,
) -> None:
    """比較state型の本文field不在と、pathを渡した最小GraphのDBに本文がないか検査する。"""

    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b"ALIGNMENT-AND-IMAGE-BINARY-SENTINEL")
    database = tmp_path / "comparison.sqlite"

    raw = _checkpoint(
        ComparisonState,
        {
            "source": str(tmp_path / "source.pdf"),
            "target": str(tmp_path / "target.pdf"),
            "output": str(tmp_path / "review.md"),
            "source_document_path": str(artifact),
            "target_document_path": str(artifact),
            "groups_path": str(artifact),
            "comparison_path": str(artifact),
        },
        database,
    )

    assert b"ALIGNMENT-AND-IMAGE-BINARY-SENTINEL" not in raw
    forbidden = {
        "source_document",
        "target_document",
        "groups",
        "comparison",
        "checks",
        "reviews",
    }
    assert not forbidden & ComparisonState.__annotations__.keys()


def test_checkpoint_commit_failure_keeps_single_task_result_without_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """checkpoint保存失敗時の単一invokeで、Taskが一度だけ実行され完全版が残る。"""

    database = tmp_path / "failure.sqlite"
    output = tmp_path / "artifact"
    task_calls = 0

    def task(_state: TranslationState) -> dict[str, object]:
        """
        完全なTask成果物を公開して呼出数を数え、直後のcheckpoint保存失敗の影響を調べる。
        """

        nonlocal task_calls
        task_calls += 1
        with atomic_directory(output) as temporary:
            atomic_write_bytes(temporary / "result.bin", b"complete")
        return {"current_task": "STRUCTURE"}

    graph = StateGraph(TranslationState)
    graph.add_node("structure", task)
    graph.add_edge(START, "structure")
    graph.add_edge("structure", END)

    class CheckpointCommitError(OSError):
        pass

    with SqliteSaver.from_conn_string(str(database)) as saver:
        real_put = saver.put
        put_calls = 0

        def fail_after_task(*args: object, **kwargs: object) -> object:
            """
            二回目のcheckpoint書込みだけ失敗させ、同一invoke内の再実行と部分公開を検査す
            る。
            """

            nonlocal put_calls
            put_calls += 1
            if put_calls == 2:
                raise CheckpointCommitError
            return real_put(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(saver, "put", fail_after_task)
        compiled = graph.compile(checkpointer=saver)
        with pytest.raises(CheckpointCommitError):
            compiled.invoke(
                {"source": "source.pdf"},
                {"configurable": {"thread_id": "checkpoint-failure"}},
            )

    assert task_calls == 1
    assert (output / "result.bin").read_bytes() == b"complete"
    assert not list(tmp_path.glob(".artifact.*"))


@pytest.mark.parametrize("operation", ["translate", "review"])
def test_workflow_failure_checkpoint_omits_exception_body(
    operation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """実WorkflowのSPLIT障害を通し、再読込した失敗情報とDBから機密本文を除外する。"""

    markers = ("CHECKPOINT-BODY", "CHECKPOINT-CREDENTIAL", "CHECKPOINT-BINARY")
    error = ValueError(" ".join(markers))

    def fail_split(*_args: object, **_kwargs: object) -> None:
        """最初のTaskだけを失敗させ、製品Graphと保存境界を実際に通す。"""

        raise error

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(translation.split, "run", fail_split)
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("structure", "translation", "review"):
        (templates / f"{name}-rules.md").write_text("rules", encoding="utf-8")
    settings = settings_factory(templates_dir=templates)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"input fixture")
    workspace = tmp_path / "workspace"

    invocation = (
        partial(translation.run, source, tmp_path / "output", "llm", settings)
        if operation == "translate"
        else partial(
            comparison_review.run, source, source, tmp_path / "review.md", settings
        )
    )
    with pytest.raises(ValueError, match="CHECKPOINT-BODY") as captured:
        invocation(workspace_dir=workspace)
    assert captured.value is error
    metadata = json.loads((workspace / "workflow.json").read_text(encoding="utf-8"))
    config = {"configurable": {"thread_id": metadata["thread_id"]}}
    database = workspace / "checkpoints.sqlite"
    workflow = translation if operation == "translate" else comparison_review
    with SqliteSaver.from_conn_string(str(database)) as saver:
        compiled = workflow.build_graph(settings).compile(checkpointer=saver)
        snapshot = compiled.get_state(config)
        saved = saver.get_tuple(config)
        assert saved is not None
        errors = [
            value
            for _task, channel, value in saved.pending_writes or []
            if channel == "__error__"
        ]
        assert errors
        # SQLite/WALと復元値の両方を検査し、表示だけのmaskで合格しない。
        persisted = repr((saved, snapshot)).encode() + b"".join(
            path.read_bytes() for path in workspace.glob("checkpoints.sqlite*")
        )
        for marker in markers:
            assert marker.encode() not in persisted
        assert errors == ["TaskError"]
        assert snapshot.next == (
            "split" if operation == "translate" else "source_split",
        )
        assert snapshot.tasks[0].error == "TaskError"


@pytest.mark.parametrize("operation", ["translate", "review"])
def test_cli_real_graph_preserves_diagnostics_without_persisting_body(  # noqa: PLR0915
    operation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """CLIから実Graphへ到達し、機密を除いた位置・LLM診断を失わず失敗する。"""

    markers = ("PRIVATE-BODY-MARKER", "PRIVATE-KEY-MARKER", "PRIVATE-BINARY-MARKER")

    class DiagnosticError(ValueError):
        """診断fieldと秘密本文が共存する障害を最初のTaskから注入する。"""

        page = 3
        group = "group-2"
        stage = "text-output"
        cause_type = "LLMOutputTruncatedError"
        failure_kind = "output-truncated"
        finish_reason = "length"
        input_tokens = 100
        output_tokens = 200
        total_tokens = 300

    def fail_split(*_args: object, role: str, **_kwargs: object) -> None:
        """Service/Taskの代替例外だけを投げ、公開入口・通知・Graph保存は置換しない。"""

        error = DiagnosticError(" ".join(markers))
        error.target_id = role
        raise error

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(translation.split, "run", fail_split)
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("structure", "translation", "review"):
        (templates / f"{name}-rules.md").write_text("rules", encoding="utf-8")
    (templates / "glossary.csv").write_text("english,japanese\n", encoding="utf-8")
    (templates / "template.docx").write_bytes(b"unused template")
    settings = settings_factory(
        templates_dir=templates, runs_dir=tmp_path / "runs", openai_api_key=markers[1]
    )
    # 環境値だけをTestへ固定し、Run準備・実行・公開Error処理は実装を使う。
    monkeypatch.setattr(cli_v1, "load_settings", lambda *_args: settings)
    source = tmp_path / "source.pdf"
    source.write_text(markers[0], encoding="utf-8")
    target = tmp_path / "target.pdf"
    target.write_text("target fixture", encoding="utf-8")
    arguments = (
        ["translate", str(source), "--output-dir", str(tmp_path / "output")]
        if operation == "translate"
        else [
            "review",
            str(source),
            str(target),
            "--output",
            str(tmp_path / "review.md"),
        ]
    )

    result = CliRunner().invoke(cli_v1.app, arguments)

    assert result.exit_code == 1
    repository = RunRepository(settings.runs_dir)
    records = repository.list_runs().records
    assert len(records) == 1
    record = records[0]
    assert record.status == "failed"
    failure = load_failure(repository, record.run_id)
    assert failure is not None
    assert failure.task == ("SPLIT" if operation == "translate" else "SOURCE-SPLIT")
    assert (failure.page, failure.group) == (3, "group-2")
    assert failure.target_id == ("source" if operation == "translate" else "source_en")
    assert failure.stage == "text-output"
    assert failure.cause_type == "LLMOutputTruncatedError"
    assert failure.error_type == "DiagnosticError"
    assert failure.failure_kind == "output-truncated"
    assert failure.finish_reason == "length"
    assert (failure.input_tokens, failure.output_tokens, failure.total_tokens) == (
        100,
        200,
        300,
    )
    assert "Traceback" not in result.output
    assert "page=3" in result.output
    assert "stage=text-output" in result.output
    paths = repository.paths(record.run_id)
    # 入力copyは本文を保持すべきArtifactなので診断対象に含めない。
    persisted = (
        result.output.encode()
        + b"".join(
            path.read_bytes() for path in paths.workspace.rglob("*") if path.is_file()
        )
        + (paths.root / "run.json").read_bytes()
    )
    for marker in markers:
        assert marker.encode() not in persisted
    assert not list(paths.outputs.iterdir())
