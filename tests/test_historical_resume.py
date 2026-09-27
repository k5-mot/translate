"""Historical Translation checkpointの安全な複製とResume境界を検証する。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx2
import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from PIL import Image

from translate_v1.adapters import llm
from translate_v1.adapters.langfuse import bind_observation_context
from translate_v1.common import lifecycle
from translate_v1.common.lifecycle import PreparedRun, PublicRunError, execute_public_run
from translate_v1.common.logger import configure_logging
from translate_v1.common.progress import TaskStatusEvent, bind_task_status
from translate_v1.common.runs import RunRepository
from translate_v1.common.workspace import OutputLock, atomic_write_json
from translate_v1.document import Block, Document, Inline, Page
from translate_v1.tasks import structure
from translate_v1.workflows import translation

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate_v1.common.settings import Settings


_SCALAR_PATHS = {
    "source",
    "output_dir",
    "workspace_dir",
    "document_path",
    "merged",
    "positioned",
    "normalized",
}
_LIST_PATHS = {"parts", "archives", "documents"}
_SAFE_STATE = {
    "backend",
    "completed_tasks",
    "current",
    "current_task",
    "total",
    "warnings",
}
_COMPLETED = [
    "SPLIT",
    "DOCLING",
    "UNPACK",
    "MERGE",
    "POSITION",
    "NORMALIZE",
    "LOAD",
]


def _digest(path: Path) -> tuple[str, int, int]:
    """File内容、mtimeおよびsizeを不変性比較用に返す。"""

    return (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        path.stat().st_mtime_ns,
        path.stat().st_size,
    )


def _is_link(path: Path) -> bool:
    """SymlinkとWindows junctionを同じ危険なcopy元として扱う。"""

    return path.is_symlink() or path.is_junction()


def _reject_link(path: Path) -> None:
    """
    履歴Artifactがlinkやjunctionなら拒否し、複製・診断が意図しない保存先へ及ぶのを防ぐ。
    """

    if _is_link(path):
        msg = "linked historical artifact is not allowed"
        raise ValueError(msg)


def _copy_regular_tree(source: Path, destination: Path) -> None:
    """Checkpoint DBとlockを除くregular fileだけを隔離先へcopyする。"""

    if destination.exists():
        msg = "historical clone destination already exists"
        raise FileExistsError(msg)
    destination.mkdir(parents=True)
    try:
        for item in source.rglob("*"):
            _reject_link(item)
            if not item.is_file():
                continue
            relative = item.relative_to(source)
            if relative.as_posix() in {
                ".workspace/checkpoints.sqlite",
                ".workspace/checkpoints.sqlite-shm",
                ".workspace/checkpoints.sqlite-wal",
                ".workspace/run.lock",
            }:
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _backup_database(source: Path, destination: Path) -> None:
    """Read-only SQLite connectionから一貫したDatabase snapshotを作る。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            closing(
                sqlite3.connect(
                    f"{source.resolve().as_uri()}?mode=ro",
                    uri=True,
                )
            ) as source_connection,
            closing(sqlite3.connect(destination)) as destination_connection,
        ):
            source_connection.backup(destination_connection)
            _verify_database(destination_connection)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def _verify_database(connection: sqlite3.Connection) -> None:
    """SQLiteの整合性検査に失敗したbackupを拒否し、不正な複製でResume検証を進めない。"""

    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        msg = "historical checkpoint backup failed integrity check"
        raise sqlite3.DatabaseError(msg)


def _map_path(value: str, source: Path, destination: Path) -> str:
    """正本Run配下の絶対pathだけをclone rootへ写像する。"""

    path = Path(value)
    if not path.is_absolute():
        msg = "historical checkpoint path must be absolute"
        raise ValueError(msg)
    try:
        relative = path.resolve().relative_to(source.resolve())
    except ValueError as error:
        msg = "historical checkpoint path is outside run root"
        raise ValueError(msg) from error
    return str((destination / relative).resolve())


def _path_updates(
    values: dict[str, Any], source: Path, destination: Path
) -> dict[str, object]:
    """既知のpath fieldだけをrebaseし、本文相当の未知stateを拒否する。"""

    unknown = set(values) - _SCALAR_PATHS - _LIST_PATHS - _SAFE_STATE
    if unknown:
        msg = "historical checkpoint contains unknown state fields"
        raise ValueError(msg)
    if any(
        isinstance(value, (bytes, bytearray, memoryview)) for value in values.values()
    ):
        msg = "historical checkpoint contains binary state"
        raise ValueError(msg)
    updates: dict[str, object] = {}
    for key in _SCALAR_PATHS & values.keys():
        value = values[key]
        if not isinstance(value, str):
            msg = "historical checkpoint scalar path has invalid type"
            raise TypeError(msg)
        updates[key] = _map_path(value, source, destination)
    for key in _LIST_PATHS & values.keys():
        value = values[key]
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            msg = "historical checkpoint path list has invalid type"
            raise TypeError(msg)
        updates[key] = [_map_path(item, source, destination) for item in value]
    return updates


def _table_counts(database: Path) -> dict[str, int]:
    """
    Checkpointとpending writeの件数を取得して接続を閉じ、履歴複製前後の比較に使う。
    """

    connection = sqlite3.connect(database)
    try:
        checkpoints = connection.execute("SELECT count(*) FROM checkpoints").fetchone()[
            0
        ]
        writes = connection.execute("SELECT count(*) FROM writes").fetchone()[0]
        return {"checkpoints": checkpoints, "writes": writes}
    finally:
        connection.close()


def _workflow_config(root: Path) -> dict[str, object]:
    """保存されたthread IDを読み、単一同時実行で履歴Graphを再開する設定を作る。"""

    workflow = json.loads(
        (root / ".workspace" / "workflow.json").read_text(encoding="utf-8")
    )
    return {
        "configurable": {"thread_id": workflow["thread_id"]},
        "max_concurrency": 1,
    }


def _clone_historical_run(
    source: Path, destination: Path, settings: Settings
) -> tuple[dict[str, object], dict[str, int], dict[str, int]]:
    """正本lineageをcopyし、clone側だけへpath-rebase checkpointを加える。"""

    database = source / ".workspace" / "checkpoints.sqlite"
    source_before = _digest(database)
    _copy_regular_tree(source, destination)
    clone_database = destination / ".workspace" / "checkpoints.sqlite"
    try:
        _backup_database(database, clone_database)
        counts_before = _table_counts(clone_database)
        config = _workflow_config(destination)
        with SqliteSaver.from_conn_string(str(clone_database)) as saver:
            graph = translation.build_graph(settings).compile(checkpointer=saver)
            before = graph.get_state(config)
            _ensure_pending_structure(before.next, "historical")
            updates = _path_updates(dict(before.values), source, destination)
            graph.update_state(config, updates, as_node="load")
            after = graph.get_state(config)
            _ensure_pending_structure(after.next, "rebased")
        counts_after = _table_counts(clone_database)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    assert _digest(database) == source_before
    return config, counts_before, counts_after


def _ensure_pending_structure(nodes: tuple[str, ...], boundary: str) -> None:
    """次nodeがSTRUCTUREだけであることを確認し、異なる再開位置のfixtureを誤用しない。"""

    if nodes != ("structure",):
        msg = f"{boundary} checkpoint is not pending STRUCTURE"
        raise ValueError(msg)


def _page(number: int) -> Page:
    """番号でIDを区別した小さな文書ページを作り、全ページ入力と推論範囲を検証する。"""

    return Page(
        number=number,
        blocks=[
            Block(
                id=f"page-{number}-block",
                order=0,
                kind="paragraph",
                source=[Inline(id=f"page-{number}-inline", text="offline text")],
            )
        ],
    )


def _synthetic_historical_run(
    root: Path, settings: Settings
) -> tuple[RunRepository, str]:
    """LOAD完了とpage 2確定済みの小さいhistorical Runを作る。"""

    source = root / "source.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"offline-pdf")
    repository = RunRepository(root / "runs")
    record = repository.create("translate", {"source": source}, {}, "f" * 64)
    record = repository.save(
        record.model_copy(update={"status": "failed", "last_task": "STRUCTURE"})
    )
    paths = repository.paths(record.run_id)
    copied_source = paths.root / record.inputs[0].relative_path
    work = paths.workspace
    artifacts = {
        "parts": work / "split" / "part.pdf",
        "archives": work / "docling" / "part.zip",
        "documents": work / "docling" / "part" / "document.json",
        "merged": work / "merge" / "document.json",
        "positioned": work / "position" / "document.json",
        "normalized": work / "normalize" / "document.json",
        "document_path": work / "load" / "document.json",
    }
    document = Document(pages=[_page(1), _page(2), _page(3)])
    for key, path in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if key == "parts":
            path.write_bytes(b"part")
        elif key == "archives":
            path.write_bytes(b"archive")
        else:
            atomic_write_json(path, document.model_dump(mode="json"))
    rules = "offline rules"
    page_two = document.pages[1]
    key = structure._page_key(  # noqa: SLF001
        page_two,
        hashlib.sha256(copied_source.read_bytes()).hexdigest(),
        rules,
        settings,
    )
    structure._save_page_checkpoint(  # noqa: SLF001
        work / "structure-pages" / "page-0002", key, page_two, []
    )
    thread_id = "historical-structure-resume"
    atomic_write_json(work / "workflow.json", {"thread_id": thread_id})
    state = {
        "source": str(copied_source.resolve()),
        "output_dir": str(paths.outputs.resolve()),
        "workspace_dir": str(work.resolve()),
        "backend": "llm",
        "parts": [str(artifacts["parts"].resolve())],
        "archives": [str(artifacts["archives"].resolve())],
        "documents": [str(artifacts["documents"].resolve())],
        "merged": str(artifacts["merged"].resolve()),
        "positioned": str(artifacts["positioned"].resolve()),
        "normalized": str(artifacts["normalized"].resolve()),
        "document_path": str(artifacts["document_path"].resolve()),
        "current_task": "LOAD",
        "current": 7,
        "total": 17,
        "completed_tasks": _COMPLETED,
    }
    config = {"configurable": {"thread_id": thread_id}, "max_concurrency": 1}
    with SqliteSaver.from_conn_string(str(work / "checkpoints.sqlite")) as saver:
        graph = translation.build_graph(settings).compile(checkpointer=saver)
        graph.update_state(config, state, as_node="load")
    return repository, record.run_id


def _offline_model(
    boundaries: list[str], concurrency: dict[str, int]
) -> tuple[object, httpx2.Client]:
    """Strict-schema応答を返す実ChatOpenAI stackを計測する。"""

    def handler(_request: object) -> httpx2.Response:
        """実HTTP送信なしで構造応答を返し、呼出数と最大同時実行数を記録する。"""

        concurrency["active"] += 1
        concurrency["maximum"] = max(concurrency["maximum"], concurrency["active"])
        concurrency["calls"] += 1
        try:
            return httpx2.Response(
                200,
                json={
                    "id": "chatcmpl-historical",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "offline-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"patches":[]}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                    },
                    "provider_private": "SECRET-HISTORICAL-RAW-RESPONSE",
                },
            )
        finally:
            concurrency["active"] -= 1

    http_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    model = ChatOpenAI(
        model="offline-model",
        base_url="http://offline.invalid/v1",
        api_key="offline-key",
        max_retries=0,
        http_client=http_client,
    )

    class BoundModel:
        def __init__(self, inner: object) -> None:
            """bind済み実Modelを保持し、送受信境界の観測だけを追加できるようにする。"""

            self.inner = inner

        def invoke(self, messages: object, *args: object, **kwargs: object) -> object:
            """
            実Modelへ委譲して送信・応答の境界を記録し、SDK経路が一回だけ通るか検証する。
            """

            boundaries.append("invoke")
            result = self.inner.invoke(messages, *args, **kwargs)  # type: ignore[attr-defined]
            boundaries.append("response")
            return result

    class Model:
        def bind(self, *args: object, **kwargs: object) -> BoundModel:
            """実Modelのbindに委譲し、bind回数と後続送信を追跡するprobeを返す。"""

            boundaries.append("bind")
            return BoundModel(model.bind(*args, **kwargs))

    return Model(), http_client


def _render_page(_source: Path, _page: int, output: Path, _dpi: int = 120) -> Path:
    """実PDF描画を小さなPNGへ置き換え、履歴ResumeのSDK経路を画像内容から独立させる。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", (32, 32), "white") as image:
        image.save(output, format="PNG")
    return output


def _resume_structure(
    root: Path,
    settings: Settings,
    config: dict[str, object],
    *,
    wrapper: str,
) -> tuple[list[dict[str, Any]], tuple[str, ...], list[TaskStatusEvent]]:
    """Pending STRUCTUREを実Graphで一度だけResumeする。"""

    statuses: list[TaskStatusEvent] = []
    warnings: list[str] = []
    work = root / ".workspace"
    with SqliteSaver.from_conn_string(str(work / "checkpoints.sqlite")) as saver:
        graph = translation.build_graph(settings).compile(
            checkpointer=saver,
            interrupt_after=["structure"],
        )
        with ExitStack() as stack:
            if wrapper in {"logging", "all"}:
                configure_logging(work / "logs" / "run.log", [])
            if wrapper in {"lock", "all"}:
                stack.enter_context(OutputLock(work))
            if wrapper in {"status", "all"}:
                stack.enter_context(bind_task_status(statuses.append))
            if wrapper in {"observation", "all"}:
                stack.enter_context(
                    bind_observation_context([], warnings.append, "TRANSLATE")
                )
            try:
                updates = list(graph.stream(None, config, stream_mode="values"))
            finally:
                if wrapper in {"logging", "all"}:
                    configure_logging()
        next_nodes = graph.get_state(config).next
    assert warnings == []
    return updates, next_nodes, statuses


@pytest.fixture
def historical_settings(
    tmp_path: Path,
    settings_factory: Callable[..., Settings],
) -> Settings:
    """
    実サービスへ接続しないModel設定と構造規則を用意し、履歴Testの試行条件を固定する。
    """

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "structure-rules.md").write_text("offline rules", encoding="utf-8")
    return settings_factory(
        templates_dir=templates,
        retry_attempts=1,
        openai_base_url="http://offline.invalid/v1",
        openai_api_key="offline-key",
        structure_model="offline-model",
    )


def test_historical_checkpoint_clone_is_read_only_and_rebased(
    tmp_path: Path,
    historical_settings: Settings,
) -> None:
    """合成checkpoint DBの不変性と複製側の履歴件数増加・path再配置を確認する。"""

    repository, run_id = _synthetic_historical_run(
        tmp_path / "source", historical_settings
    )
    source = repository.paths(run_id).root
    source_database = source / ".workspace" / "checkpoints.sqlite"
    before = _digest(source_database)
    destination = tmp_path / "clone" / run_id

    config, counts_before, counts_after = _clone_historical_run(
        source, destination, historical_settings
    )

    assert _digest(source_database) == before
    assert counts_after["checkpoints"] == counts_before["checkpoints"] + 1
    assert counts_after["writes"] >= counts_before["writes"]
    with SqliteSaver.from_conn_string(
        str(destination / ".workspace" / "checkpoints.sqlite")
    ) as saver:
        snapshot = (
            translation.build_graph(historical_settings)
            .compile(checkpointer=saver)
            .get_state(config)
        )
    assert snapshot.next == ("structure",)
    assert snapshot.values["completed_tasks"] == _COMPLETED
    for key in _SCALAR_PATHS:
        assert Path(snapshot.values[key]).is_relative_to(destination)
    for key in _LIST_PATHS:
        assert all(
            Path(item).is_relative_to(destination) for item in snapshot.values[key]
        )


def _set_outside(values: dict[str, Any], outside: Path) -> None:
    """文書入力pathを領域外へ改変し、履歴stateのpath検証が拒否するか調べる。"""

    values["source"] = str(outside)


def _set_unknown_body(values: dict[str, Any], _outside: Path) -> None:
    """許可されない本文keyを履歴stateへ混ぜ、文書本文の持込み拒否を検証する。"""

    values["body"] = "secret text"


def _set_binary(values: dict[str, Any], _outside: Path) -> None:
    """小さなmetadata欄へbinaryを混ぜ、履歴stateの型制約を検証する。"""

    values["current"] = b"binary"


@pytest.mark.parametrize(
    ("mutation", "error_type"),
    [
        (_set_outside, ValueError),
        (_set_unknown_body, ValueError),
        (_set_binary, ValueError),
    ],
)
def test_historical_checkpoint_rejects_unsafe_state(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any], Path], None],
    error_type: type[Exception],
) -> None:
    """Root外path、未知本文fieldおよびbinary stateをrebaseしない。"""

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    values: dict[str, Any] = {
        "source": str((source / "input.pdf").resolve()),
        "completed_tasks": _COMPLETED,
    }
    mutation(values, tmp_path / "outside.pdf")

    with pytest.raises(error_type):
        _path_updates(values, source, destination)


def test_historical_clone_removes_partial_copy_on_link_or_copy_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """link判定とcopy失敗を注入し、部分cloneの削除を確認する。実linkは作らない。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.json").write_text("{}", encoding="utf-8")
    linked = source / "linked.json"
    linked.write_text("{}", encoding="utf-8")
    destination = tmp_path / "linked-clone"
    monkeypatch.setattr(f"{__name__}._is_link", lambda path: path.name == linked.name)
    with pytest.raises(ValueError, match="linked historical"):
        _copy_regular_tree(source, destination)
    assert not destination.exists()

    monkeypatch.setattr(f"{__name__}._is_link", lambda _path: False)

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        """履歴Artifactのcopyを失敗させ、不完全な複製が片付けられるか確認する。"""

        message = "copy failed"
        raise OSError(message)

    monkeypatch.setattr(shutil, "copy2", fail_copy)
    destination = tmp_path / "failed-clone"
    with pytest.raises(OSError, match="copy failed"):
        _copy_regular_tree(source, destination)
    assert not destination.exists()


def test_historical_backup_rejects_corrupt_database(
    tmp_path: Path,
) -> None:
    """破損Databaseをcloneとして公開せず部分Fileを除去する。"""

    source = tmp_path / "corrupt.sqlite"
    source.write_bytes(b"not-a-sqlite-database")
    destination = tmp_path / "clone.sqlite"

    with pytest.raises(sqlite3.DatabaseError):
        _backup_database(source, destination)
    assert not destination.exists()


def test_fresh_full_document_reuses_page_checkpoint_and_sdk_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    historical_settings: Settings,
) -> None:
    """合成した三頁の文書でpage 2の独自Cacheを再利用し、page 3だけSDKを呼ぶ。"""

    repository, run_id = _synthetic_historical_run(
        tmp_path / "fresh", historical_settings
    )
    root = repository.paths(run_id).root
    config = _workflow_config(root)
    boundaries: list[str] = []
    concurrency = {"active": 0, "maximum": 0, "calls": 0}
    model, http_client = _offline_model(boundaries, concurrency)

    def model_factory(*_args: object) -> object:
        """新規実行でのModel構築を記録し、準備済みのオフラインModelへ接続する。"""

        boundaries.append("build")
        return model

    monkeypatch.setattr(llm, "_model", model_factory)
    real_parse = llm.PydanticOutputParser.parse

    def parse_once(parser: object, value: str) -> object:
        """新規実行での解析回数を記録し、実parserへ委譲して結果の意味を変えない。"""

        boundaries.append("parse")
        return real_parse(parser, value)  # type: ignore[arg-type]

    monkeypatch.setattr(llm.PydanticOutputParser, "parse", parse_once)
    monkeypatch.setattr(structure.pdf, "render_page", _render_page)
    database = root / ".workspace" / "checkpoints.sqlite"
    checkpoint_counts = _table_counts(database)
    try:
        updates, next_nodes, _statuses = _resume_structure(
            root,
            historical_settings,
            config,
            wrapper="direct",
        )
    finally:
        http_client.close()

    assert next_nodes == ("translate",)
    assert sum(item.get("current_task") == "STRUCTURE" for item in updates) == 1
    assert concurrency == {"active": 0, "maximum": 1, "calls": 1}
    assert boundaries == ["build", "bind", "invoke", "response", "parse"]
    assert (
        _table_counts(database)["checkpoints"] == checkpoint_counts["checkpoints"] + 1
    )
    assert (root / ".workspace/structure-pages/page-0003/.complete.json").is_file()


@pytest.mark.parametrize(
    "mode",
    ["direct", "logging", "lock", "status", "observation", "all"],
)
def test_historical_resume_crosses_full_document_and_wrappers_once(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    historical_settings: Settings,
    mode: str,
) -> None:
    """合成三頁の複製checkpointを観測等の境界で囲み、一回のSDK呼出を確認する。"""

    repository, run_id = _synthetic_historical_run(
        tmp_path / "source", historical_settings
    )
    source = repository.paths(run_id).root
    destination = tmp_path / "clone" / run_id
    config, _before, _after = _clone_historical_run(
        source, destination, historical_settings
    )
    boundaries: list[str] = []
    concurrency = {"active": 0, "maximum": 0, "calls": 0}
    model, http_client = _offline_model(boundaries, concurrency)

    def model_factory(*_args: object) -> object:
        """履歴ResumeでのModel構築を記録し、準備済みのオフラインModelへ接続する。"""

        boundaries.append("build")
        return model

    monkeypatch.setattr(llm, "_model", model_factory)
    real_parse = llm.PydanticOutputParser.parse

    def parse_once(parser: object, value: str) -> object:
        """
        履歴Resumeでの解析回数を記録し、実parserへ委譲して一回だけ解析するか調べる。
        """

        boundaries.append("parse")
        return real_parse(parser, value)  # type: ignore[arg-type]

    monkeypatch.setattr(llm.PydanticOutputParser, "parse", parse_once)
    monkeypatch.setattr(structure.pdf, "render_page", _render_page)
    for task in (
        translation.split,
        translation.docling,
        translation.unpack,
        translation.merge,
        translation.position,
        translation.normalize,
        translation.load,
    ):
        monkeypatch.setattr(
            task,
            "run",
            lambda *_args, **_kwargs: pytest.fail("completed task was replayed"),
        )

    database = destination / ".workspace" / "checkpoints.sqlite"
    checkpoint_counts = _table_counts(database)
    try:
        updates, next_nodes, statuses = _resume_structure(
            destination,
            historical_settings,
            config,
            wrapper=mode,
        )
    finally:
        http_client.close()

    assert next_nodes == ("translate",)
    assert sum(item.get("current_task") == "STRUCTURE" for item in updates) == 1
    assert concurrency == {"active": 0, "maximum": 1, "calls": 1}
    assert boundaries == ["build", "bind", "invoke", "response", "parse"]
    assert (
        _table_counts(database)["checkpoints"] == checkpoint_counts["checkpoints"] + 1
    )
    assert (
        destination / ".workspace/structure-pages/page-0003/.complete.json"
    ).is_file()
    assert (destination / ".workspace/structure/document.json").is_file()
    assert "SECRET-HISTORICAL-RAW-RESPONSE" not in caplog.text
    if mode in {"status", "all"}:
        assert [(event.task, event.phase) for event in statuses] == [
            ("STRUCTURE", "started"),
            ("STRUCTURE", "completed"),
        ]
    else:
        assert statuses == []
    if mode in {"lock", "all"}:
        assert not (destination / ".workspace/run.lock").read_bytes()


def test_public_lifecycle_reaches_post_structure_boundary_without_typeerror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    historical_settings: Settings,
) -> None:
    """公開Lifecycle wrapper内でもSTRUCTURE後の既知Errorまで到達する。"""

    source_repository, run_id = _synthetic_historical_run(
        tmp_path / "source", historical_settings
    )
    source = source_repository.paths(run_id).root
    destination = tmp_path / "clone-runs" / run_id
    config, _before, _after = _clone_historical_run(
        source, destination, historical_settings
    )
    boundaries: list[str] = []
    concurrency = {"active": 0, "maximum": 0, "calls": 0}
    model, http_client = _offline_model(boundaries, concurrency)
    monkeypatch.setattr(llm, "_model", lambda *_args: model)
    monkeypatch.setattr(structure.pdf, "render_page", _render_page)

    class PostStructureBoundaryError(RuntimeError):
        pass

    def run_to_boundary(
        _source: Path,
        _output: Path,
        _backend: object,
        settings: Settings,
        _callback: object,
        workspace: Path,
    ) -> Path:
        """
        公開LifecycleからSTRUCTURE完了と次のTRANSLATE位置まで進め、意図した例外で境界を
        止める。
        """

        updates, next_nodes, _statuses = _resume_structure(
            workspace.parent,
            settings,
            config,
            wrapper="direct",
        )
        assert next_nodes == ("translate",)
        assert any(item.get("current_task") == "STRUCTURE" for item in updates)
        raise PostStructureBoundaryError

    monkeypatch.setattr(lifecycle, "run_translation", run_to_boundary)
    repository = RunRepository(destination.parent)
    record = repository.load(run_id)
    prepared = PreparedRun(
        record,
        repository.paths(run_id),
        {"source": destination / record.inputs[0].relative_path},
        resumed=True,
    )
    try:
        with pytest.raises(PublicRunError) as captured:
            execute_public_run(repository, prepared, historical_settings)
    finally:
        http_client.close()

    assert captured.value.failure.error_type == "PostStructureBoundaryError"
    assert captured.value.failure.cause_type is None
    assert captured.value.failure.cause_type != "TypeError"
    assert concurrency == {"active": 0, "maximum": 1, "calls": 1}
    assert (destination / ".workspace/structure/document.json").is_file()
    assert repository.load(run_id).status == "failed"
