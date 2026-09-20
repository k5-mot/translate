"""Workflow checkpointがArtifact pathだけを保持することを検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from translate.workflows.comparison_review import ComparisonState
from translate.workflows.translation import TranslationState

if TYPE_CHECKING:
    from pathlib import Path


def _checkpoint(
    state_type: type[TranslationState | ComparisonState],
    initial: dict[str, object],
    database: Path,
) -> bytes:
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
    """翻訳stateからInternal DocumentとFinding本文を排除する。"""

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


def test_comparison_checkpoint_contains_paths_not_alignment_or_documents(
    tmp_path: Path,
) -> None:
    """比較stateから両文書、AlignmentおよびFinding本文を排除する。"""

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
