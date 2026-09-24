"""Langfuse観測の接続範囲と障害分離を検証する。"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from langfuse import Langfuse
from langgraph.checkpoint.sqlite import SqliteSaver
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from PIL import Image
from pydantic import BaseModel

from translate.adapters import langfuse, llm
from translate.common.lifecycle import execute_run, prepare_run
from translate.common.progress import bind_task_status
from translate.common.runs import RunRepository
from translate.common.workspace import atomic_write_bytes, atomic_write_json
from translate.document import Block, Document, Inline, Page
from translate.tasks import structure
from translate.workflows import translation as translation_workflow

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from translate.common.progress import ProgressCallback
    from translate.common.settings import Backend, Settings


class _Response(BaseModel):
    value: str


_OBSERVATION_CURRENT: ContextVar[bool] = ContextVar(
    "test_langfuse_observation_current", default=False
)


def _offline_chat_model(
    calls: list[bool], current_probe: Callable[[], bool] | None = None
) -> tuple[ChatOpenAI, httpx2.Client]:
    """実OpenAI SDK response stackをNetworkなしで構成する。"""

    def handler(_request: object) -> httpx2.Response:
        """
        送信時の観測contextを記録し、実ネットワークなしでOpenAI互換の正常JSON応答を返す
        。
        """

        calls.append(
            current_probe() if current_probe is not None else _OBSERVATION_CURRENT.get()
        )
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-offline",
                "object": "chat.completion",
                "created": 0,
                "model": "offline-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"value":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 5,
                    "total_tokens": 8,
                },
                "provider_private": "SECRET-OFFLINE-RAW-RESPONSE",
            },
        )

    http_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return (
        ChatOpenAI(
            model="offline-model",
            base_url="http://offline.invalid/v1",
            api_key="offline-key",
            max_retries=0,
            http_client=http_client,
        ),
        http_client,
    )


def _real_langfuse_client(
    public_key: str, credential: str
) -> tuple[Langfuse, InMemorySpanExporter]:
    """Network exporterを使わない実Langfuse clientを返す。"""

    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=public_key,
        secret_key=credential,
        base_url="http://offline.invalid",
        span_exporter=exporter,
        tracer_provider=TracerProvider(),
    )
    return client, exporter


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_workflow_flushes_after_success_and_failure(
    outcome: str,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Workflow結果に関係なくtraceをflushする。"""

    events: list[str] = []

    @contextmanager
    def fake_observe(*_args: object, **_kwargs: object) -> Iterator[None]:
        """観測contextの開始と正常終了を記録し、Workflow終了時のflush順序を検証する。"""

        events.append("start")
        yield
        events.append("finish")

    def fake_run(*_args: object, **_kwargs: object) -> Path:
        """指定ケースでWorkflowだけを失敗させ、成功・失敗双方のflush経路を検証する。"""

        if outcome == "failure":
            message = "workflow failure"
            raise RuntimeError(message)
        return Path("result.docx")

    monkeypatch.setattr(translation_workflow, "observe", fake_observe)
    monkeypatch.setattr(translation_workflow, "_run", fake_run)
    monkeypatch.setattr(
        translation_workflow,
        "flush",
        lambda _settings: events.append("flush"),
    )
    settings = settings_factory()

    if outcome == "failure":
        with pytest.raises(RuntimeError, match="workflow failure"):
            translation_workflow.run(
                Path("source.pdf"), Path("output"), "llm", settings
            )
    else:
        assert translation_workflow.run(
            Path("source.pdf"), Path("output"), "llm", settings
        ) == Path("result.docx")

    assert events[-1] == "flush"


def test_llm_call_is_observed_without_sending_prompt_body(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """LLM spanにはModel等の最小metadataだけを渡し、本文は渡さない。"""

    captured: dict[str, object] = {}

    @contextmanager
    def fake_observe(*_args: object, **kwargs: object) -> Iterator[None]:
        """LLM観測開始の引数を捕捉し、prompt本文が観測metadataへ渡されないか調べる。"""

        captured.update(kwargs)
        yield

    class Client:
        def invoke(self, _messages: object) -> AIMessage:
            """
            固定の正常JSONを返し、LLM処理と観測metadataの検査を外部サービスから独立させ
            る。
            """

            return AIMessage(content='{"value":"ok"}')

    monkeypatch.setattr(llm, "observe", fake_observe)
    monkeypatch.setattr(llm, "_model", lambda *_args: Client())
    settings = settings_factory()

    result = llm.structured(
        settings,
        "safe-model-name",
        _Response,
        "secret system body",
        "secret user body",
        reasoning="low",
    )

    assert result.value == "ok"
    assert captured == {
        "as_type": "generation",
        "detached": True,
        "metadata": {"reasoning": "low", "response_type": "_Response"},
        "model": "safe-model-name",
    }
    assert "secret" not in repr(captured)


def test_actual_openai_response_stack_parses_offline_completion(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """実SDK response変換とstrict-schema parseをNetworkなしで通す。"""

    calls: list[bool] = []
    sentinel = "SECRET-OFFLINE-RAW-RESPONSE"
    model, http_client = _offline_chat_model(calls)
    monkeypatch.setattr(llm, "_model", lambda *_args: model)
    caplog.set_level(logging.WARNING)

    try:
        result = llm.structured(
            settings_factory(),
            "offline-model",
            _Response,
            "system",
            "user",
            reasoning="none",
            schema_mode="json-schema",
        )
    finally:
        http_client.close()

    assert result.value == "ok"
    assert calls == [False]
    assert sentinel not in caplog.text


@pytest.mark.parametrize("mode", ["current", "detached"])
def test_actual_openai_response_stack_distinguishes_observation_context(
    mode: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """detached観測だけが実SDK呼出しのcurrent contextを変更しない。"""

    calls: list[bool] = []
    model, http_client = _offline_chat_model(calls)

    class Observation:
        def update(self, **_kwargs: object) -> None:
            # 観測の更新を無処理で受け、実応答stackのcurrent context検証に集中する。
            return None

        def end(self) -> None:
            # 観測終了を無処理で受け、current contextの有無と送信経路の関係だけを検証す
            # る。
            return None

    class Manager:
        token: Token[bool] | None = None

        def __enter__(self) -> Observation:
            """
            現在の観測contextを有効にしてtokenを保持し、SDK送信時のcontext検出を可能にす
            る。
            """

            self.token = _OBSERVATION_CURRENT.set(True)
            return Observation()

        def __exit__(self, *_args: object) -> None:
            """
            保持したtokenで観測contextを元に戻し、次の送信Testへ状態を持ち越さない。
            """

            assert self.token is not None
            _OBSERVATION_CURRENT.reset(self.token)

    class LangfuseClient:
        def start_as_current_observation(self, **_kwargs: object) -> Manager:
            """contextを有効化するManagerを返し、current観測を使うSDK経路を模擬する。"""

            return Manager()

        def start_observation(self, **_kwargs: object) -> Observation:
            """
            current contextを変更しない観測doubleを返し、detached観測との違いを検証する
            。
            """

            return Observation()

    monkeypatch.setattr(llm, "_model", lambda *_args: model)
    monkeypatch.setattr(
        langfuse,
        "_get_client",
        lambda settings: LangfuseClient() if settings.langfuse_enabled else None,
    )
    model_settings = settings_factory()
    credential_value = "SECRET-OFFLINE-KEY"
    observation_settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=credential_value,
    )
    caplog.set_level(logging.WARNING)

    try:
        with langfuse.observe(
            observation_settings,
            "offline.generation",
            as_type="generation",
            detached=mode == "detached",
        ):
            result = llm.structured(
                model_settings,
                "offline-model",
                _Response,
                "system",
                "user",
                reasoning="none",
                schema_mode="json-schema",
            )
    finally:
        http_client.close()

    assert result.value == "ok"
    assert calls == [mode == "current"]
    assert "SECRET-OFFLINE-RAW-RESPONSE" not in caplog.text
    assert credential_value not in caplog.text


def test_translation_workflow_keeps_model_outside_real_langfuse_current_span(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """公開Workflowの実Langfuse spanをModel処理中のcurrentにしない。"""

    calls: list[bool] = []
    credential = "lf-offline-workflow-credential"
    model, http_client = _offline_chat_model(
        calls,
        lambda: trace.get_current_span().get_span_context().is_valid,
    )
    client, exporter = _real_langfuse_client("pk-lf-workflow", credential)
    settings = settings_factory(
        langfuse_public_key="pk-lf-workflow",
        langfuse_secret_key=credential,
    )
    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: client)
    monkeypatch.setattr(llm, "_model", lambda *_args: model)

    def model_run(*_args: object, **_kwargs: object) -> Path:
        """
        実SDKのオフライン送信経路をWorkflowから呼び、正常解析後に代替DOCX pathを返す。
        """

        result = llm.structured(
            settings,
            "offline-model",
            _Response,
            "system",
            "user",
            reasoning="none",
            schema_mode="json-schema",
        )
        assert result.value == "ok"
        return Path("result.docx")

    monkeypatch.setattr(translation_workflow, "_run", model_run)
    caplog.set_level(logging.WARNING)

    try:
        assert translation_workflow.run(
            Path("source.pdf"), Path("output"), "llm", settings
        ) == Path("result.docx")
        client.flush()
    finally:
        http_client.close()
        client.shutdown()

    spans = exporter.get_finished_spans()
    assert calls == [False]
    assert {span.name for span in spans} >= {
        "workflow.pdf-translation",
        "llm.request",
    }
    assert "SECRET-OFFLINE-RAW-RESPONSE" not in repr(spans)
    assert credential not in caplog.text


def test_real_langfuse_detached_hierarchy_preserves_parents_without_current_span(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """non-current三層観測で親子関係とModel context隔離を両立する。"""

    calls: list[bool] = []
    credential = "lf-offline-hierarchy-credential"
    model, http_client = _offline_chat_model(
        calls,
        lambda: trace.get_current_span().get_span_context().is_valid,
    )
    client, exporter = _real_langfuse_client("pk-lf-hierarchy", credential)
    settings = settings_factory(
        langfuse_public_key="pk-lf-hierarchy",
        langfuse_secret_key=credential,
    )
    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: client)
    monkeypatch.setattr(llm, "_model", lambda *_args: model)
    caplog.set_level(logging.WARNING)

    try:
        with (
            langfuse.observe(
                settings, "workflow.offline", as_type="chain", detached=True
            ),
            langfuse.observe(settings, "task.structure", detached=True),
        ):
            result = llm.structured(
                settings,
                "offline-model",
                _Response,
                "system",
                "user",
                reasoning="none",
                schema_mode="json-schema",
            )
        client.flush()
    finally:
        http_client.close()
        client.shutdown()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    workflow = spans["workflow.offline"]
    task = spans["task.structure"]
    generation = spans["llm.request"]
    assert result.value == "ok"
    assert calls == [False]
    assert {span.context.trace_id for span in spans.values()} == {
        workflow.context.trace_id
    }
    assert task.parent is not None
    assert task.parent.span_id == workflow.context.span_id
    assert generation.parent is not None
    assert generation.parent.span_id == task.context.span_id
    assert "SECRET-OFFLINE-RAW-RESPONSE" not in repr(tuple(spans.values()))
    assert credential not in caplog.text


def test_pending_structure_resume_crosses_real_graph_and_sdk_once(  # noqa: C901, PLR0915
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """呼出元threadでGraphのSTRUCTUREを再開し、固定SDK応答を一度だけ解析する。"""

    credential = "lf-offline-graph-credential"
    calls: list[dict[str, object]] = []
    boundaries: list[tuple[str, int]] = []
    statuses: list[object] = []
    warnings: list[str] = []
    main_thread = threading.get_ident()

    def handler(_request: object) -> httpx2.Response:
        """
        送信thread・親観測・current spanを記録し、再開Graphからの実SDK経路へ空patch応答
        を返す。
        """

        calls.append(
            {
                "thread": threading.get_ident(),
                "parent_bound": langfuse._PARENT_OBSERVATION.get() is not None,  # noqa: SLF001
                "current_span": trace.get_current_span().get_span_context().is_valid,
            }
        )
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-offline-graph",
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
                "provider_private": "SECRET-GRAPH-RAW-RESPONSE",
            },
        )

    http_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    model = ChatOpenAI(
        model="offline-model",
        base_url="http://offline.invalid/v1",
        api_key="offline-key",
        max_retries=0,
        http_client=http_client,
    )

    class BoundModelProbe:
        def __init__(self, inner: object) -> None:
            """
            bind済みModelを保持し、処理を再実装せず送信前後だけ計測できるようにする。
            """

            self.inner = inner

        def invoke(self, messages: object, *args: object, **kwargs: object) -> object:
            """
            送信前後のthreadを記録して実Modelへ委譲し、応答まで同じ境界を通るか確認する
            。
            """

            boundaries.append(("invoke", threading.get_ident()))
            result = self.inner.invoke(  # type: ignore[attr-defined]
                messages, *args, **kwargs
            )
            boundaries.append(("response", threading.get_ident()))
            return result

    class ModelProbe:
        def bind(self, *args: object, **kwargs: object) -> BoundModelProbe:
            """
            bind時のthreadを記録し、実Modelのbind結果を送信境界計測用のprobeへ渡す。
            """

            boundaries.append(("bind", threading.get_ident()))
            return BoundModelProbe(model.bind(*args, **kwargs))

    def model_factory(*_args: object, **_kwargs: object) -> ModelProbe:
        """Model構築境界のthreadを記録し、実Modelへ委譲するprobeを返す。"""

        boundaries.append(("build", threading.get_ident()))
        return ModelProbe()

    real_parse = llm.PydanticOutputParser.parse

    def parse_once(parser: object, value: str) -> object:
        """
        解析時のthreadを記録し、既存parserへ委譲して実解析の回数と実行境界を調べる。
        """

        boundaries.append(("parse", threading.get_ident()))
        return real_parse(parser, value)  # type: ignore[arg-type]

    def render_page(_source: Path, _page: int, output: Path, _dpi: int = 120) -> Path:
        """構造推定に必要なPNGを作り、実PDF描画なしでGraphとSDKの再開経路を通す。"""

        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.new("RGB", (32, 32), "white") as image:
            image.save(output, format="PNG")
        return output

    def unexpected(*_args: object, **_kwargs: object) -> object:
        """
        成功済みTaskが呼ばれたら直ちに失敗させ、Checkpoint再開時の意図しない再実行を検出
        する。
        """

        msg = "completed task was replayed"
        raise AssertionError(msg)

    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("structure", "translation", "review"):
        (templates / f"{name}-rules.md").write_text("rules", encoding="utf-8")
    settings = settings_factory(
        templates_dir=templates,
        retry_attempts=1,
        openai_base_url="http://offline.invalid/v1",
        openai_api_key="offline-key",
        structure_model="offline-model",
        translation_model="offline-model",
        review_model="offline-model",
        fix_model="offline-model",
        langfuse_public_key="pk-lf-graph-boundary",
        langfuse_secret_key=credential,
    )
    client, exporter = _real_langfuse_client("pk-lf-graph-boundary", credential)
    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: client)
    monkeypatch.setattr(llm, "_model", model_factory)
    monkeypatch.setattr(llm.PydanticOutputParser, "parse", parse_once)
    monkeypatch.setattr(structure.pdf, "render_page", render_page)
    for task in (
        translation_workflow.split,
        translation_workflow.docling,
        translation_workflow.unpack,
        translation_workflow.merge,
        translation_workflow.position,
        translation_workflow.normalize,
        translation_workflow.load,
    ):
        monkeypatch.setattr(task, "run", unexpected)

    source = tmp_path / "source.pdf"
    source.write_bytes(b"offline-pdf")
    output_dir = tmp_path / "outputs"
    workspace = tmp_path / "workspace"
    loaded = workspace / "load" / "document.json"
    document = Document(
        pages=[
            Page(
                number=3,
                blocks=[
                    Block(
                        id="page-3-block-1",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="page-3-inline-1", text="offline text")],
                    )
                ],
            )
        ]
    )
    atomic_write_json(loaded, document.model_dump(mode="json"))
    config = {
        "configurable": {"thread_id": "offline-structure-resume"},
        "max_concurrency": 1,
    }
    state = {
        "source": str(source.resolve()),
        "output_dir": str(output_dir.resolve()),
        "workspace_dir": str(workspace.resolve()),
        "backend": "llm",
        "document_path": str(loaded.resolve()),
        "current_task": "LOAD",
        "current": 7,
        "total": 17,
        "completed_tasks": [
            "SPLIT",
            "DOCLING",
            "UNPACK",
            "MERGE",
            "POSITION",
            "NORMALIZE",
            "LOAD",
        ],
    }
    caplog.set_level(logging.WARNING)

    try:
        checkpoint_path = workspace / "checkpoints.sqlite"
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            compiled = translation_workflow.build_graph(settings).compile(
                checkpointer=saver,
                interrupt_after=["structure"],
            )
            compiled.update_state(config, state, as_node="load")
            assert compiled.get_state(config).next == ("structure",)
            with (
                bind_task_status(statuses.append),
                langfuse.bind_observation_context(
                    [credential], warnings.append, "TRANSLATE"
                ),
                langfuse.observe(
                    settings,
                    "workflow.pdf-translation",
                    as_type="chain",
                    detached=True,
                ),
            ):
                updates = list(compiled.stream(None, config, stream_mode="values"))
            snapshot = compiled.get_state(config)
            assert snapshot.next == ("translate",)
        client.flush()
    finally:
        http_client.close()
        client.shutdown()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert len(calls) == 1
    # Locked LangGraph's synchronous stream keeps this node on the caller thread.
    # This guards against attributing the real-run failure to a nonexistent hop.
    assert calls[0]["thread"] == main_thread
    assert calls[0]["parent_bound"] is True
    assert calls[0]["current_span"] is False
    assert [name for name, _thread in boundaries] == [
        "build",
        "bind",
        "invoke",
        "response",
        "parse",
    ]
    assert len({thread for _name, thread in boundaries}) == 1
    assert sum(update.get("current_task") == "STRUCTURE" for update in updates) == 1
    assert [(event.task, event.phase) for event in statuses] == [
        ("STRUCTURE", "started"),
        ("STRUCTURE", "completed"),
    ]
    assert warnings == []
    assert (workspace / "structure" / "document.json").is_file()
    assert (workspace / "structure-pages" / "page-0003" / ".complete.json").is_file()
    workflow = spans["workflow.pdf-translation"]
    task = spans["task.structure"]
    generation = spans["llm.request"]
    assert task.parent is not None
    assert task.parent.span_id == workflow.context.span_id
    assert generation.parent is not None
    assert generation.parent.span_id == task.context.span_id
    assert credential not in caplog.text
    assert "SECRET-GRAPH-RAW-RESPONSE" not in caplog.text
    assert "SECRET-GRAPH-RAW-RESPONSE" not in repr(tuple(spans.values()))


@pytest.mark.parametrize("failure_stage", ["child-start", "child-update", "child-end"])
def test_detached_child_failure_resets_parent_before_next_root(  # noqa: C901
    failure_stage: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """子観測障害後の独立Runが以前の親観測を再利用しない。"""

    sentinel = "SECRET-DETACHED-CHILD"
    events: list[str] = []
    warnings: list[str] = []

    class Observation:
        def __init__(self, name: str) -> None:
            """観測名を保持し、親子関係と特定の子観測での障害を識別できるようにする。"""

            self.name = name

        def start_observation(self, **kwargs: object) -> Observation:
            """親子の観測名を記録し、指定ケースだけ子観測の開始を失敗させる。"""

            child_name = str(kwargs["name"])
            events.append(f"child:{self.name}:{child_name}")
            if failure_stage == "child-start":
                raise OSError(sentinel)
            return Observation(child_name)

        def update(self, **_kwargs: object) -> None:
            """
            指定されたSTRUCTURE子観測の更新だけを失敗させ、親contextの復元を試験する。
            """

            if failure_stage == "child-update" and self.name == "task.structure":
                raise OSError(sentinel)

        def end(self) -> None:
            """
            終了した観測名を記録し、STRUCTURE子観測の終了障害を選択的に発生させる。
            """

            events.append(f"end:{self.name}")
            if failure_stage == "child-end" and self.name == "task.structure":
                raise OSError(sentinel)

    class Client:
        def start_observation(self, **kwargs: object) -> Observation:
            """
            root観測の開始を記録し、前の子観測障害が次のrootへ親として残らないか調べる。
            """

            name = str(kwargs["name"])
            events.append(f"root:{name}")
            return Observation(name)

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=sentinel,
    )
    caplog.set_level(logging.WARNING)

    def business_failure() -> None:
        """
        製品処理のValueErrorを発生させ、観測の更新・終了障害に上書きされないか検証する。
        """

        message = "business failure"
        raise ValueError(message)

    with langfuse.bind_observation_context((sentinel,), warnings.append, "STRUCTURE"):
        with langfuse.observe(
            settings, "workflow.first", as_type="chain", detached=True
        ):
            if failure_stage == "child-start":
                with langfuse.observe(settings, "task.structure", detached=True):
                    pass
            else:
                with (
                    pytest.raises(ValueError, match="business failure"),
                    langfuse.observe(settings, "task.structure", detached=True),
                ):
                    business_failure()
        with langfuse.observe(
            settings, "workflow.next", as_type="chain", detached=True
        ):
            pass

    assert "root:workflow.next" in events
    assert not any(
        event.endswith(":workflow.next")
        for event in events
        if event.startswith("child:")
    )
    assert len(warnings) == 1
    action = {
        "child-start": "start",
        "child-update": "update",
        "child-end": "finish",
    }[failure_stage]
    assert action in warnings[0]
    assert "task=STRUCTURE" in warnings[0]
    assert sentinel not in warnings[0]
    assert sentinel not in caplog.text


def test_llm_detached_finish_failure_keeps_success_without_retry_or_leak(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """応答後の観測終了失敗は成功値を変えずProviderへ再送しない。"""

    credential = "SECRET-DETACHED-ENDPOINT"
    calls = 0
    starts: list[str] = []

    class Observation:
        def end(self) -> None:
            """
            秘密値を含む観測終了障害を発生させ、成功済みLLMの再送や情報漏洩がないか調べ
            る。
            """

            message = f"finish failed at {credential}"
            raise OSError(message)

        def update(self, **_kwargs: object) -> None:
            # 観測更新を正常に受け、終了障害だけに検証条件を限定する。
            return None

    class LangfuseClient:
        def start_observation(self, **_kwargs: object) -> Observation:
            """detached観測の開始を記録し、終了障害を持つ観測doubleを返す。"""

            starts.append("detached")
            return Observation()

        def start_as_current_observation(self, **_kwargs: object) -> object:
            """
            current観測の利用を失敗させ、LLM generationがdetached境界を守るか検証する。
            """

            starts.append("current")
            message = "generation must not attach a current observation"
            raise AssertionError(message)

    class ModelClient:
        def bind(self, **_kwargs: object) -> ModelClient:
            """schema指定を受理し、正常応答の送信回数を観測できる同じdoubleを返す。"""

            return self

        def invoke(self, _messages: object) -> AIMessage:
            """正常JSONを返して呼出数を記録し、観測終了失敗によるLLM再送を検出する。"""

            nonlocal calls
            calls += 1
            return AIMessage(content='{"value":"ok"}')

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: LangfuseClient())
    monkeypatch.setattr(llm, "_model", lambda *_args: ModelClient())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=credential,
    )
    caplog.set_level(logging.WARNING)

    result = llm.structured(
        settings,
        "model",
        _Response,
        "system",
        "user",
        reasoning="none",
        schema_mode="json-schema",
    )

    assert result.value == "ok"
    assert calls == 1
    assert starts == ["detached"]
    assert "Langfuse finish failed (OSError)" in caplog.text
    assert credential not in caplog.text


@pytest.mark.parametrize("failure_stage", ["start", "finish"])
def test_detached_observation_boundary_failures_preserve_success(
    failure_stage: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """detached観測の作成・終了障害を一回のwarningへ縮退する。"""

    sentinel = "SECRET-OBSERVATION-FAILURE"
    warnings: list[str] = []

    class Observation:
        def end(self) -> None:
            """選択ケースだけ観測終了を失敗させ、処理成功が維持されるか検証する。"""

            if failure_stage == "finish":
                raise OSError(sentinel)

        def update(self, **_kwargs: object) -> None:
            # 観測更新を無処理で受け、開始または終了の障害を個別に試験できるようにする。
            return None

    class Client:
        def start_observation(self, **_kwargs: object) -> Observation:
            """
            選択ケースで観測開始を失敗させ、その他では終了障害を選べる観測doubleを返す。
            """

            if failure_stage == "start":
                raise OSError(sentinel)
            return Observation()

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=sentinel,
    )
    caplog.set_level(logging.WARNING)

    with (
        langfuse.bind_observation_context((sentinel,), warnings.append, "STRUCTURE"),
        langfuse.observe(settings, "llm.request", as_type="generation", detached=True),
    ):
        result = "ok"

    assert result == "ok"
    assert len(warnings) == 1
    assert failure_stage in warnings[0]
    assert "task=STRUCTURE" in warnings[0]
    assert sentinel not in warnings[0]
    assert sentinel not in caplog.text


def test_detached_update_failure_preserves_business_error(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """detached観測更新失敗より本来の処理Errorを優先する。"""

    sentinel = "SECRET-DETACHED-UPDATE"
    warnings: list[str] = []

    class Observation:
        def update(self, **_kwargs: object) -> None:
            """製品例外の記録時に観測更新を失敗させ、元の製品例外が保たれるか調べる。"""

            raise OSError(sentinel)

        def end(self) -> None:
            # 観測終了は成功させ、更新障害だけの影響を検証する。
            return None

    class Client:
        def start_observation(self, **_kwargs: object) -> Observation:
            """更新だけが失敗する観測doubleを返し、製品例外の保持を検証する。"""

            return Observation()

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=sentinel,
    )
    caplog.set_level(logging.WARNING)

    def processing_failure() -> None:
        """製品処理のValueErrorを投げ、観測更新失敗がその例外を隠さないか調べる。"""

        message = "business failure"
        raise ValueError(message)

    with (
        pytest.raises(ValueError, match="business failure"),
        langfuse.bind_observation_context((sentinel,), warnings.append, "STRUCTURE"),
        langfuse.observe(settings, "llm.request", as_type="generation", detached=True),
    ):
        processing_failure()

    assert len(warnings) == 1
    assert "Langfuse update failed (OSError)" in warnings[0]
    assert sentinel not in warnings[0]
    assert sentinel not in caplog.text


def test_observation_and_flush_failures_warn_without_blocking_or_leaking(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """観測Service停止時も本処理を完了し、例外messageや鍵をlogへ出さない。"""

    credential_value = "lf-credential-do-not-log"

    class Client:
        def start_as_current_observation(self, **_kwargs: object) -> object:
            """
            秘密値を含む観測開始障害を発生させ、警告だけで製品処理が続くか検証する。
            """

            message = f"endpoint failed with {credential_value}"
            raise OSError(message)

        def flush(self) -> None:
            """
            秘密値を含むflush障害を発生させ、終了処理が漏洩せず継続するか検証する。
            """

            message = f"flush failed with {credential_value}"
            raise OSError(message)

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=credential_value,
    )
    caplog.set_level(logging.WARNING)
    completed = False

    with langfuse.observe(settings, "workflow.test"):
        completed = True
    langfuse.flush(settings)

    assert completed
    assert "Langfuse start failed (OSError)" in caplog.text
    assert "Langfuse flush failed (OSError)" in caplog.text
    assert credential_value not in caplog.text


def test_each_langfuse_failure_stage_reaches_context_warning_sink_once(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """観測update・finish・flushの障害を各一回、Task付きwarningへ変換する。"""

    credential = "langfuse-secret-value"
    warnings: list[str] = []

    class Observation:
        def update(self, **_kwargs: object) -> None:
            """
            観測更新を秘密値付きで失敗させ、contextに束縛した警告先への安全な通知を調べ
            る。
            """

            message = f"update endpoint contains {credential}"
            raise OSError(message)

    class Manager:
        def __enter__(self) -> Observation:
            """更新障害を持つ観測doubleを返し、観測contextへの進入自体は成功させる。"""

            return Observation()

        def __exit__(self, *_args: object) -> None:
            """
            観測終了を秘密値付きで失敗させ、更新障害とは別の警告として通知されるか調べる
            。
            """

            message = f"finish endpoint contains {credential}"
            raise OSError(message)

    class Client:
        def start_as_current_observation(self, **_kwargs: object) -> Manager:
            """開始は成功させ、更新と終了の各障害を検証できるManagerを返す。"""

            return Manager()

        def flush(self) -> None:
            """
            flushを秘密値付きで失敗させ、他の観測障害とともに安全に警告されるか調べる。
            """

            message = f"flush endpoint contains {credential}"
            raise OSError(message)

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=credential,
    )
    caplog.set_level(logging.WARNING)

    def processing_failure() -> None:
        """
        観測context内で製品例外を発生させ、更新・終了の警告と元例外の扱いを検証する。
        """

        with langfuse.observe(settings, "workflow.test"):
            message = f"business failure {credential}"
            raise ValueError(message)

    with langfuse.bind_observation_context((credential,), warnings.append, "REVIEW"):
        with pytest.raises(ValueError, match="business failure"):
            processing_failure()
        langfuse.flush(settings)

    assert len(warnings) == 3
    assert {item.split()[1] for item in warnings} == {"update", "finish", "flush"}
    assert all("task=REVIEW" in item for item in warnings)
    assert credential not in "\n".join(warnings)
    assert credential not in caplog.text


def test_initialization_and_warning_sink_failures_are_non_blocking(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Client生成とwarning保存の双方が壊れても本処理を継続する。"""

    credential = "initialization-secret"

    def client_failure(*_args: object) -> object:
        """SDK Client初期化を秘密値付きで失敗させ、観測なしの継続を検証する。"""

        message = f"initialization endpoint contains {credential}"
        raise OSError(message)

    def sink_failure(_warning: str) -> None:
        """
        警告通知先自体を失敗させ、観測障害の通知失敗でも製品処理を妨げないか調べる。
        """

        message = f"sink contains {credential}"
        raise RuntimeError(message)

    monkeypatch.setattr(langfuse, "_client", client_failure)
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=credential,
    )
    caplog.set_level(logging.WARNING)
    completed = False

    with (
        langfuse.bind_observation_context((credential,), sink_failure, "TRANSLATE"),
        langfuse.observe(settings, "workflow.test"),
    ):
        completed = True

    assert completed
    assert "Langfuse initialization failed (OSError)" in caplog.text
    assert "Langfuse warning sink failed (RuntimeError)" in caplog.text
    assert credential not in caplog.text


@pytest.mark.integration
def test_lifecycle_persists_duplicate_langfuse_warning_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """同じ観測障害はRun warningへ一度だけ保存し本処理を完了する。"""

    credential = "run-warning-secret"
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("structure", "translation", "review"):
        (templates / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (templates / "glossary.csv").write_text("en,ja\n", encoding="utf-8")
    (templates / "template.docx").write_bytes(b"template")
    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=templates,
        langfuse_public_key="public",
        langfuse_secret_key=credential,
    )

    class Client:
        def start_as_current_observation(self, **_kwargs: object) -> object:
            """
            同じ秘密値入りSDK障害を繰り返し発生させ、Run警告の秘匿と重複抑止を検証する。
            """

            message = f"SDK body contains {credential}"
            raise OSError(message)

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())

    def workflow(
        _source: Path,
        output_dir: Path,
        _backend: Backend,
        run_settings: Settings,
        _callback: ProgressCallback | None,
        _workspace: Path | None,
    ) -> Path:
        """
        同じTask観測を二度失敗させた後に成果物を保存し、Run完了と警告一件への集約を調べ
        る。
        """

        for _ in range(2):
            with (
                langfuse.bind_observation_task("DOCLING"),
                langfuse.observe(run_settings, "task.docling"),
            ):
                pass
        output = output_dir / "document.ja.docx"
        atomic_write_bytes(output, b"complete")
        return output

    monkeypatch.setattr("translate.common.lifecycle.run_translation", workflow)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fixture")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings)

    completed, _ = execute_run(repository, prepared, settings)

    assert completed.status == "completed"
    matching = [
        warning for warning in completed.warnings if "Langfuse start failed" in warning
    ]
    assert len(matching) == 1
    assert "task=DOCLING" in matching[0]
    run_json = repository.paths(completed.run_id).metadata.read_text(encoding="utf-8")
    log = (
        repository.paths(completed.run_id)
        .workspace.joinpath("logs", "run.log")
        .read_text(encoding="utf-8")
    )
    assert credential not in run_json
    assert credential not in log
