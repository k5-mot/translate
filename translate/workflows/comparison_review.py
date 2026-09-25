"""LangGraphで独立した英日PDFの比較Reviewを管理する。"""

from __future__ import annotations

import hashlib
import json
import operator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from translate.adapters.checkpoint import open_checkpoint
from translate.adapters.langfuse import bind_observation_task, flush, observe
from translate.common.progress import (
    ProgressCallback,
    TaskStatusEvent,
    WorkflowProgress,
    report_task_status,
)
from translate.common.settings import Settings, read_rules
from translate.common.workspace import atomic_write_json, sha256_file
from translate.document import (
    AlignmentGroup,
    Block,
    Document,
    Finding,
    Inline,
    Page,
    block_text_units,
)
from translate.tasks import (
    align,
    check,
    docling,
    load,
    merge,
    normalize,
    position,
    report,
    review,
    split,
    unpack,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.runnables import RunnableConfig


class ComparisonState(TypedDict, total=False):
    source: str
    target: str
    output: str
    workspace_dir: str
    source_parts: list[str]
    source_archives: list[str]
    source_documents: list[str]
    source_merged: str
    source_positioned: str
    source_normalized: str
    source_document_path: str
    target_parts: list[str]
    target_archives: list[str]
    target_documents: list[str]
    target_merged: str
    target_positioned: str
    target_normalized: str
    target_document_path: str
    groups_path: str
    comparison_path: str
    checks_path: str
    reviews_path: str
    current_task: str
    warnings: list[str]
    current: int
    total: int
    completed_tasks: Annotated[list[str], operator.add]


COMPARISON_TASKS = [
    f"{side.upper()}-{task.upper()}"
    for task in ("split", "docling", "unpack", "merge", "position", "normalize", "load")
    for side in ("source", "target")
] + ["ALIGN", "CHECK", "REVIEW", "REPORT"]
COMPARISON_SLOTS = {task: index for index, task in enumerate(COMPARISON_TASKS, start=1)}


def _load_document(path: str) -> Document:
    """Checkpointのpathが指す文書Artifactを読み、Document schemaで検証してTaskへ渡す。"""

    return Document.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _save_findings(path: Path, values: dict[int, list[Finding]]) -> str:
    """ページ別指摘をJSONへ原子的に保存し、文書本体をGraph stateへ入れず保存pathを返す。"""

    atomic_write_json(
        path,
        {
            str(page): [item.model_dump(mode="json") for item in items]
            for page, items in values.items()
        },
    )
    return str(path)


def _load_findings(path: str) -> dict[int, list[Finding]]:
    """保存済みのページ別指摘をschema検証し、JSONのページkeyを整数へ復元する。"""

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        int(page): [Finding.model_validate(item) for item in items]
        for page, items in value.items()
    }


def _comparison_document(
    source: Document, target: Document, groups: list[AlignmentGroup]
) -> Document:
    """対応GroupのIDで本文・caption・セルを集め、Group単位の比較用Blockへ組み直す。"""

    source_units = {
        unit.id: unit
        for page in source.pages
        for block in page.blocks
        for unit in block_text_units(block)
    }
    target_units = {
        unit.id: unit
        for page in target.pages
        for block in page.blocks
        for unit in block_text_units(block)
    }
    blocks: list[Block] = []
    for order, group in enumerate(groups):
        source_text = "\n".join(
            source_units[item].text("source")
            for item in group.source_ids
            if item in source_units
        )
        target_text = "\n".join(
            target_units[item].text("source")
            for item in group.target_ids
            if item in target_units
        )
        blocks.append(
            Block(
                id=f"alignment/{order}",
                order=order,
                kind="paragraph",
                source=[Inline(id=f"alignment/{order}/source", text=source_text)],
                translated=[Inline(id=f"alignment/{order}/target", text=target_text)],
            )
        )
    return Document(pages=[Page(number=2, blocks=blocks)])


def build_graph(
    settings: Settings,
) -> StateGraph[ComparisonState]:  # ty: ignore[invalid-type-arguments]
    """両PDFの検証後に原文・訳文を逐次抽出し、対応付けと検査へ進むGraphを返す。"""

    # `ty` does not yet expose TypedDict's runtime key attributes to LangGraph's stub.
    graph = StateGraph(ComparisonState)  # ty: ignore[invalid-argument-type]

    def tracked(
        name: str, function: Callable[[ComparisonState], dict[str, Any]]
    ) -> None:
        """Task通知と観測を付けたnodeを登録し、Task本体とGraphへの接続を分離する。"""

        def wrapped(state: ComparisonState) -> dict[str, Any]:
            """開始・成否を通知してTaskを実行し、成功時だけ完了名をGraph state更新に添える。"""

            report_task_status(TaskStatusEvent(name, "started"))
            try:
                with (
                    bind_observation_task(name),
                    observe(
                        settings,
                        f"task.{name.casefold()}",
                        detached=True,
                        metadata={"task": name},
                    ),
                ):
                    result = {**function(state), "completed_tasks": [name]}
            except BaseException as error:
                target_id = getattr(error, "target_id", None)
                if target_id is None:
                    target_id = {
                        "SOURCE-SPLIT": "source_en",
                        "TARGET-SPLIT": "translation_ja",
                    }.get(name)
                report_task_status(
                    TaskStatusEvent(
                        name,
                        "failed",
                        page=getattr(error, "page", None),
                        group=getattr(error, "group", None),
                        target_id=target_id,
                        stage=getattr(error, "stage", None),
                        cause_type=getattr(error, "cause_type", None),
                        failure_kind=getattr(error, "failure_kind", None),
                        finish_reason=getattr(error, "finish_reason", None),
                        input_tokens=getattr(error, "input_tokens", None),
                        output_tokens=getattr(error, "output_tokens", None),
                        total_tokens=getattr(error, "total_tokens", None),
                        error=error,
                    )
                )
                raise
            report_task_status(TaskStatusEvent(name, "completed"))
            return result

        graph.add_node(name.lower().replace("-", "_"), wrapped)

    def branch_root(state: ComparisonState, side: str) -> Path:
        """原文側と訳文側の中間成果物を混在させないよう、それぞれの保存directoryを返す。"""

        return Path(state["workspace_dir"]) / side

    def split_node(state: ComparisonState, side: str) -> dict[str, Any]:
        """指定側のPDFを検証・分割し、生成partのpathだけを次のnodeへ渡す。"""

        root = branch_root(state, side)
        manifest = split.run(
            Path(state[side]),  # ty: ignore[invalid-key]
            root / "split",
            settings.split_pages,  # type: ignore[literal-required]
            role="source_en" if side == "source" else "translation_ja",
        )
        return {f"{side}_parts": [item["path"] for item in manifest["parts"]]}

    def docling_node(state: ComparisonState, side: str) -> dict[str, Any]:
        """指定側のPDF partを逐次Doclingへ送り、応答ZIPのpathをGraph stateへ返す。"""

        root = branch_root(state, side)
        parts = state[f"{side}_parts"]  # ty: ignore[invalid-key]
        values = docling.run([Path(item) for item in parts], root / "docling", settings)
        return {f"{side}_archives": [str(item) for item in values]}

    def unpack_node(state: ComparisonState, side: str) -> dict[str, Any]:
        """指定側の応答ZIPを安全に展開し、抽出された文書JSONのpathを返す。"""

        archives = state[f"{side}_archives"]  # ty: ignore[invalid-key]
        values = unpack.run([Path(item) for item in archives])
        return {f"{side}_documents": [str(item) for item in values]}

    def merge_node(state: ComparisonState, side: str) -> dict[str, Any]:
        """指定側の抽出結果を原本PDFに対応させて統合し、統合JSONのpathを返す。"""

        root = branch_root(state, side)
        documents = state[f"{side}_documents"]  # ty: ignore[invalid-key]
        value = merge.run(
            [Path(item) for item in documents],
            Path(state[side]),  # ty: ignore[invalid-key]
            root / "merge",
        )
        return {f"{side}_merged": str(value)}

    def position_node(state: ComparisonState, side: str) -> dict[str, Any]:
        """指定側の統合文書の座標と読み順を補正し、補正済みArtifactのpathを返す。"""

        root = branch_root(state, side)
        source = state[f"{side}_merged"]  # ty: ignore[invalid-key]
        return {
            f"{side}_positioned": str(position.run(Path(source), root / "position"))
        }

    def normalize_node(state: ComparisonState, side: str) -> dict[str, Any]:
        """指定側の文書から不要要素を除去・整形し、正規化したJSONのpathを返す。"""

        root = branch_root(state, side)
        source = state[f"{side}_positioned"]  # ty: ignore[invalid-key]
        return {
            f"{side}_normalized": str(normalize.run(Path(source), root / "normalize"))
        }

    def load_node(state: ComparisonState, side: str) -> dict[str, Any]:
        """指定側の正規化JSONを共通文書Modelへ変換・保存し、そのArtifactのpathを返す。"""

        root = branch_root(state, side)
        source = state[f"{side}_normalized"]  # ty: ignore[invalid-key]
        load.run(Path(source), root / "load")
        return {f"{side}_document_path": str(root / "load" / "document.json")}

    def align_node(state: ComparisonState) -> dict[str, Any]:
        """原訳文の対応Groupと比較用文書を保存し、後続検査に必要な二つのpathを返す。"""

        work = Path(state["workspace_dir"])
        source = _load_document(state["source_document_path"])
        target = _load_document(state["target_document_path"])
        groups = align.run(source, target, work / "align", settings)
        comparison = _comparison_document(source, target, groups)
        comparison_path = work / "align" / "comparison.json"
        atomic_write_json(comparison_path, comparison.model_dump(mode="json"))
        return {
            "groups_path": str(work / "align" / "alignment.json"),
            "comparison_path": str(comparison_path),
        }

    def check_node(state: ComparisonState) -> dict[str, Any]:
        """対応済み原訳文の決定的検査を行い、ページ別指摘を保存してpathを返す。"""

        work = Path(state["workspace_dir"])
        values = check.run(
            _load_document(state["comparison_path"]),
            settings.templates_dir / "glossary.csv",
            work / "check",
        )
        return {
            "checks_path": _save_findings(work / "check" / "findings.json", values),
        }

    def review_node(state: ComparisonState) -> dict[str, Any]:
        """対応済み原訳文・CHECK指摘・規則・用語集をLLM Reviewへ渡し、結果の保存pathを返す。"""

        work = Path(state["workspace_dir"])
        checks = _load_findings(state["checks_path"])
        values = review.run(
            _load_document(state["comparison_path"]),
            checks,
            read_rules(settings, "review"),
            check.read_glossary(settings.templates_dir / "glossary.csv"),
            settings,
            work / "review",
        )
        return {
            "reviews_path": _save_findings(work / "review" / "findings.json", values),
        }

    def report_node(state: ComparisonState) -> dict[str, Any]:
        """保存された対応Groupと両検査結果から、比較reportとその中間成果物を出力する。"""

        work = Path(state["workspace_dir"])
        groups = [
            AlignmentGroup.model_validate(item)
            for item in json.loads(
                Path(state["groups_path"]).read_text(encoding="utf-8")
            )
        ]
        checks = [
            item
            for items in _load_findings(state["checks_path"]).values()
            for item in items
        ]
        reviews = [
            item
            for items in _load_findings(state["reviews_path"]).values()
            for item in items
        ]
        report.run(groups, checks, reviews, Path(state["output"]), work / "report")
        return {}

    # 遅延実行される各nodeがloop終了後も元の側を使うよう、既定引数へsideを固定する。
    for side in ("source", "target"):
        tracked(
            f"{side.upper()}-SPLIT", lambda state, side=side: split_node(state, side)
        )
        tracked(
            f"{side.upper()}-DOCLING",
            lambda state, side=side: docling_node(state, side),
        )
        tracked(
            f"{side.upper()}-UNPACK",
            lambda state, side=side: unpack_node(state, side),
        )
        tracked(
            f"{side.upper()}-MERGE", lambda state, side=side: merge_node(state, side)
        )
        tracked(
            f"{side.upper()}-POSITION",
            lambda state, side=side: position_node(state, side),
        )
        tracked(
            f"{side.upper()}-NORMALIZE",
            lambda state, side=side: normalize_node(state, side),
        )
        tracked(f"{side.upper()}-LOAD", lambda state, side=side: load_node(state, side))
    tracked("ALIGN", align_node)
    tracked("CHECK", check_node)
    tracked("REVIEW", review_node)
    tracked("REPORT", report_node)
    # Validate both PDFs before calling an external service, then keep the two
    # independently checkpointed branches strictly sequential. Local Docling and
    # model services are capacity-one resources, and concurrent status callbacks
    # would contend for the same Run metadata artifact.
    for side in ("source", "target"):
        graph.add_edge(f"{side}_docling", f"{side}_unpack")
        graph.add_edge(f"{side}_unpack", f"{side}_merge")
        graph.add_edge(f"{side}_merge", f"{side}_position")
        graph.add_edge(f"{side}_position", f"{side}_normalize")
        graph.add_edge(f"{side}_normalize", f"{side}_load")
    graph.add_edge(START, "source_split")
    graph.add_edge("source_split", "target_split")
    graph.add_edge("target_split", "source_docling")
    graph.add_edge("source_load", "target_docling")
    graph.add_edge("target_load", "align")
    graph.add_edge("align", "check")
    graph.add_edge("check", "review")
    graph.add_edge("review", "report")
    graph.add_edge("report", END)
    return graph


def _run(
    source: Path,
    target: Path,
    output: Path,
    settings: Settings,
    callback: ProgressCallback | None = None,
    workspace_dir: Path | None = None,
) -> Path:
    """比較graphをSQLite checkpoint付きで実行する。"""

    work = workspace_dir or output.parent / ".workspace"
    work.mkdir(parents=True, exist_ok=True)
    metadata_path = work / "workflow.json"
    if metadata_path.exists():
        saved = json.loads(metadata_path.read_text(encoding="utf-8"))
        if saved.get("llm_reasoning_mode", "task-default") != settings.reasoning_mode:
            msg = "LLM_REASONING_MODE differs from saved workflow; use a new workspace"
            raise ValueError(msg)
    fingerprint = {
        "source_hash": sha256_file(source),
        "target_hash": sha256_file(target),
        "review_model": settings.review_model,
        "review_rules": hashlib.sha256(
            read_rules(settings, "review").encode()
        ).hexdigest(),
    }
    # A new thread alone would not isolate the existing workspace's chunk cache.
    if settings.reasoning_mode == "off":
        fingerprint["llm_reasoning_mode"] = "off"
    thread_id = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode()
    ).hexdigest()
    atomic_write_json(work / "workflow.json", {**fingerprint, "thread_id": thread_id})
    initial: ComparisonState = {
        "source": str(source.resolve()),
        "target": str(target.resolve()),
        "output": str(output.resolve()),
        "workspace_dir": str(work.resolve()),
        "current": 0,
        "total": 18,
        "completed_tasks": [],
    }
    with open_checkpoint(work / "checkpoints.sqlite") as saver:
        compiled = build_graph(settings).compile(checkpointer=saver)
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "max_concurrency": 1,
        }
        snapshot = compiled.get_state(config)
        if not snapshot.next and snapshot.values and output.exists():
            return output
        graph_input = None if snapshot.next else initial
        tracker = WorkflowProgress(
            COMPARISON_SLOTS,
            callback,
            list(snapshot.values.get("completed_tasks", [])) if snapshot.values else [],
        )
        for update in compiled.stream(graph_input, config, stream_mode="updates"):
            for value in update.values():
                for task in value.get("completed_tasks", []):
                    tracker.emit(task)
    return output


def run(
    source: Path,
    target: Path,
    output: Path,
    settings: Settings,
    callback: ProgressCallback | None = None,
    workspace_dir: Path | None = None,
) -> Path:
    """比較Workflowをtraceし、結果にかかわらず観測をflushする。"""

    try:
        with observe(
            settings,
            "workflow.comparison-review",
            as_type="chain",
            detached=True,
        ):
            return _run(source, target, output, settings, callback, workspace_dir)
    finally:
        flush(settings)
