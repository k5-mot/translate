"""LangGraphで翻訳Taskの順序と分岐を管理する。"""

from __future__ import annotations

import hashlib
import json
import operator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from translate.adapters.langfuse import bind_observation_task, flush, observe
from translate.common.progress import (
    ProgressCallback,
    TaskStatusEvent,
    WorkflowProgress,
    report_task_status,
)
from translate.common.settings import Backend, Settings, read_rules
from translate.common.workspace import atomic_write_json, sha256_file
from translate.document import Document, Finding
from translate.tasks import (
    check,
    cover,
    docling,
    docx,
    fix,
    load,
    markdown,
    merge,
    normalize,
    position,
    review,
    split,
    structure,
    translate,
    translate_lite,
    unpack,
    validate,
    verify,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.runnables import RunnableConfig


class TranslationState(TypedDict, total=False):
    source: str
    output_dir: str
    workspace_dir: str
    backend: Backend
    parts: list[str]
    archives: list[str]
    documents: list[str]
    merged: str
    positioned: str
    normalized: str
    document_path: str
    checks_path: str
    reviews_path: str
    cover: str
    markdown: str
    docx: str
    current_task: str
    warnings: list[str]
    current: int
    total: int
    completed_tasks: Annotated[list[str], operator.add]


TRANSLATION_SLOTS = {
    "SPLIT": 1,
    "DOCLING": 2,
    "UNPACK": 3,
    "MERGE": 4,
    "POSITION": 5,
    "NORMALIZE": 6,
    "LOAD": 7,
    "STRUCTURE": 8,
    "TRANSLATE": 9,
    "TRANSLATE-LITE": 9,
    "CHECK": 10,
    "REVIEW": 11,
    "FIX": 12,
    "VERIFY": 13,
    "COVER": 14,
    "VALIDATE": 15,
    "MARKDOWN": 16,
    "DOCX": 17,
}


def _document(state: TranslationState) -> Document:
    return Document.model_validate_json(
        Path(state["document_path"]).read_text(encoding="utf-8")
    )


def _findings(path: str) -> dict[int, list[Finding]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        int(page): [Finding.model_validate(item) for item in items]
        for page, items in value.items()
    }


def _save_document(path: Path, document: Document) -> str:
    atomic_write_json(path, document.model_dump(mode="json"))
    return str(path)


def _save_findings(path: Path, values: dict[int, list[Finding]]) -> str:
    atomic_write_json(
        path,
        {
            str(page): [item.model_dump(mode="json") for item in items]
            for page, items in values.items()
        },
    )
    return str(path)


def _workspace(state: TranslationState) -> Path:
    return Path(state["workspace_dir"])


def build_graph(
    settings: Settings,
) -> StateGraph[TranslationState]:  # ty: ignore[invalid-type-arguments]
    """設定を閉じ込めた未compileの翻訳graphを返す。"""

    # `ty` does not yet expose TypedDict's runtime key attributes to LangGraph's stub.
    graph = StateGraph(TranslationState)  # ty: ignore[invalid-argument-type]

    def node(name: str, function: Callable[[TranslationState], dict[str, Any]]) -> None:
        def wrapped(state: TranslationState) -> dict[str, Any]:
            report_task_status(TaskStatusEvent(name, "started"))
            try:
                with (
                    bind_observation_task(name),
                    observe(
                        settings, f"task.{name.casefold()}", metadata={"task": name}
                    ),
                ):
                    completed = [name]
                    if name == "TRANSLATE":
                        completed.insert(0, "TRANSLATE-LITE")
                    elif name == "TRANSLATE-LITE":
                        completed.insert(0, "TRANSLATE")
                    elif name == "COVER" and not any(
                        _findings(state["reviews_path"]).values()
                    ):
                        completed = ["FIX", "VERIFY", name]
                    result = {
                        **function(state),
                        "current_task": name,
                        "current": TRANSLATION_SLOTS[name],
                        "total": 17,
                        "completed_tasks": completed,
                    }
            except BaseException as error:
                report_task_status(_failed_status(name, error))
                raise
            report_task_status(TaskStatusEvent(name, "completed"))
            return result

        graph.add_node(name.lower().replace("-", "_"), wrapped)

    def split_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        manifest = split.run(
            Path(state["source"]), work / "split", settings.split_pages, role="source"
        )
        return {"parts": [item["path"] for item in manifest["parts"]]}

    def docling_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        values = docling.run(
            [Path(item) for item in state["parts"]], work / "docling", settings
        )
        return {"archives": [str(item) for item in values]}

    def unpack_node(state: TranslationState) -> dict[str, Any]:
        values = unpack.run([Path(item) for item in state["archives"]])
        return {"documents": [str(item) for item in values]}

    def merge_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        value = merge.run(
            [Path(item) for item in state["documents"]],
            Path(state["source"]),
            work / "merge",
        )
        return {"merged": str(value)}

    def position_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        return {
            "positioned": str(position.run(Path(state["merged"]), work / "position"))
        }

    def normalize_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        return {
            "normalized": str(
                normalize.run(Path(state["positioned"]), work / "normalize")
            )
        }

    def load_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        load.run(Path(state["normalized"]), work / "load")
        return {"document_path": str(work / "load" / "document.json")}

    def structure_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        value = structure.run(
            _document(state),
            Path(state["source"]),
            read_rules(settings, "structure"),
            settings,
            work / "structure",
        )
        return {
            "document_path": _save_document(work / "structure" / "document.json", value)
        }

    def translate_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        glossary = check.read_glossary(settings.templates_dir / "glossary.csv")
        value = translate.run(
            _document(state),
            read_rules(settings, "translation"),
            glossary,
            settings,
            work / "translate",
        )
        return {
            "document_path": _save_document(work / "translate" / "document.json", value)
        }

    def translate_lite_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        value = translate_lite.run(_document(state), settings, work / "translate")
        return {
            "document_path": _save_document(work / "translate" / "document.json", value)
        }

    def check_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        values = check.run(
            _document(state), settings.templates_dir / "glossary.csv", work / "check"
        )
        return {"checks_path": _save_findings(work / "check" / "findings.json", values)}

    def review_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        glossary = check.read_glossary(settings.templates_dir / "glossary.csv")
        values = review.run(
            _document(state),
            _findings(state["checks_path"]),
            read_rules(settings, "review"),
            glossary,
            settings,
            work / "review",
        )
        return {
            "reviews_path": _save_findings(work / "review" / "findings.json", values)
        }

    def fix_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        value = fix.run(
            _document(state),
            _findings(state["reviews_path"]),
            read_rules(settings, "review"),
            settings,
            work / "fix",
        )
        return {"document_path": _save_document(work / "fix" / "document.json", value)}

    def verify_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        value = verify.run(
            _document(state),
            _findings(state["reviews_path"]),
            settings,
            work / "verify",
        )
        return {
            "document_path": _save_document(work / "verify" / "document.json", value)
        }

    def cover_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        return {
            "cover": str(cover.run(Path(state["source"]), work / "cover" / "cover.png"))
        }

    def validate_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        validate.run(
            _document(state), work / "merge", work / "validate" / "report.json"
        )
        return {"document_path": state["document_path"]}

    def markdown_node(state: TranslationState) -> dict[str, Any]:
        work = _workspace(state)
        value = markdown.run(
            _document(state),
            work / "markdown" / "document.ja.md",
            Path(state["cover"]),
            work / "merge",
        )
        return {"markdown": str(value)}

    def docx_node(state: TranslationState) -> dict[str, Any]:
        output = Path(state["output_dir"]) / "document.ja.docx"
        value = docx.run(
            Path(state["markdown"]), output, settings.templates_dir / "template.docx"
        )
        return {"docx": str(value)}

    node("SPLIT", split_node)
    node("DOCLING", docling_node)
    node("UNPACK", unpack_node)
    node("MERGE", merge_node)
    node("POSITION", position_node)
    node("NORMALIZE", normalize_node)
    node("LOAD", load_node)
    node("STRUCTURE", structure_node)
    node("TRANSLATE", translate_node)
    node("TRANSLATE-LITE", translate_lite_node)
    node("CHECK", check_node)
    node("REVIEW", review_node)
    node("FIX", fix_node)
    node("VERIFY", verify_node)
    node("COVER", cover_node)
    node("VALIDATE", validate_node)
    node("MARKDOWN", markdown_node)
    node("DOCX", docx_node)

    graph.add_edge(START, "split")
    graph.add_edge("split", "docling")
    graph.add_edge("docling", "unpack")
    graph.add_edge("unpack", "merge")
    graph.add_edge("merge", "position")
    graph.add_edge("position", "normalize")
    graph.add_edge("normalize", "load")
    graph.add_edge("load", "structure")
    # Note 1: Backend selection belongs to the graph, not either translation Task.
    graph.add_conditional_edges(
        "structure",
        lambda state: (
            "translate_lite" if state["backend"] == "libretranslate" else "translate"
        ),
        {"translate": "translate", "translate_lite": "translate_lite"},
    )
    graph.add_edge("translate", "check")
    graph.add_edge("translate_lite", "check")
    graph.add_edge("check", "review")
    # Note 2: FIX and VERIFY have no work when REVIEW reports no findings.
    graph.add_conditional_edges(
        "review",
        lambda state: (
            "fix" if any(_findings(state["reviews_path"]).values()) else "cover"
        ),
        {"fix": "fix", "cover": "cover"},
    )
    graph.add_edge("fix", "verify")
    graph.add_edge("verify", "cover")
    graph.add_edge("cover", "validate")
    graph.add_edge("validate", "markdown")
    graph.add_edge("markdown", "docx")
    graph.add_edge("docx", END)
    return graph


def _failed_status(name: str, error: BaseException) -> TaskStatusEvent:
    return TaskStatusEvent(
        name,
        "failed",
        page=getattr(error, "page", None),
        group=getattr(error, "group", None),
        target_id=getattr(error, "target_id", None),
        error=error,
    )


def _run(
    source: Path,
    output_dir: Path,
    backend: Backend,
    settings: Settings,
    callback: ProgressCallback | None = None,
    workspace_dir: Path | None = None,
) -> Path:
    """SQLite checkpoint付きgraphを実行し、生成DOCXを返す。"""

    work = workspace_dir or output_dir / ".workspace"
    work.mkdir(parents=True, exist_ok=True)
    # Note 3: Inputs, models and rules together define a reusable checkpoint run.
    fingerprint = {
        "source_hash": sha256_file(source),
        "backend": backend,
        "structure_model": settings.structure_model,
        "translation_model": settings.translation_model,
        "review_model": settings.review_model,
        "fix_model": settings.fix_model,
        "structure_rules": hashlib.sha256(
            read_rules(settings, "structure").encode()
        ).hexdigest(),
        "translation_rules": hashlib.sha256(
            read_rules(settings, "translation").encode()
        ).hexdigest(),
        "review_rules": hashlib.sha256(
            read_rules(settings, "review").encode()
        ).hexdigest(),
    }
    thread_id = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode()
    ).hexdigest()
    atomic_write_json(work / "workflow.json", {**fingerprint, "thread_id": thread_id})
    initial: TranslationState = {
        "source": str(source.resolve()),
        "output_dir": str(output_dir.resolve()),
        "workspace_dir": str(work.resolve()),
        "backend": backend,
        "current": 0,
        "total": 17,
        "completed_tasks": [],
    }
    last = initial
    # Note 4: The context manager keeps the SQLite connection alive while streaming.
    with SqliteSaver.from_conn_string(str(work / "checkpoints.sqlite")) as saver:
        compiled = build_graph(settings).compile(checkpointer=saver)
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "max_concurrency": 1,
        }
        snapshot = compiled.get_state(config)
        existing = snapshot.values.get("docx") if snapshot.values else None
        if not snapshot.next and existing and Path(existing).exists():
            return Path(existing)
        # Note 5: `None` resumes the pending node without replaying completed nodes.
        graph_input = None if snapshot.next else initial
        tracker = WorkflowProgress(
            TRANSLATION_SLOTS,
            callback,
            list(snapshot.values.get("completed_tasks", [])) if snapshot.values else [],
        )
        for current in compiled.stream(graph_input, config, stream_mode="values"):
            last = current
            actual = current.get("current_task")
            for task in current.get("completed_tasks", []):
                tracker.emit(task, skipped=task != actual)
    return Path(last["docx"])


def run(
    source: Path,
    output_dir: Path,
    backend: Backend,
    settings: Settings,
    callback: ProgressCallback | None = None,
    workspace_dir: Path | None = None,
) -> Path:
    """翻訳Workflowをtraceし、結果にかかわらず観測をflushする。"""

    try:
        with observe(
            settings,
            "workflow.pdf-translation",
            as_type="chain",
            metadata={"backend": backend},
        ):
            return _run(source, output_dir, backend, settings, callback, workspace_dir)
    finally:
        flush(settings)
