"""Langfuse観測の接続範囲と障害分離を検証する。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from langfuse import Langfuse
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pydantic import BaseModel

from translate.adapters import langfuse, llm
from translate.common.lifecycle import execute_run, prepare_run
from translate.common.runs import RunRepository
from translate.common.workspace import atomic_write_bytes
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
        events.append("start")
        yield
        events.append("finish")

    def fake_run(*_args: object, **_kwargs: object) -> Path:
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
        captured.update(kwargs)
        yield

    class Client:
        def invoke(self, _messages: object) -> AIMessage:
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
            return None

        def end(self) -> None:
            return None

    class Manager:
        token: Token[bool] | None = None

        def __enter__(self) -> Observation:
            self.token = _OBSERVATION_CURRENT.set(True)
            return Observation()

        def __exit__(self, *_args: object) -> None:
            assert self.token is not None
            _OBSERVATION_CURRENT.reset(self.token)

    class LangfuseClient:
        def start_as_current_observation(self, **_kwargs: object) -> Manager:
            return Manager()

        def start_observation(self, **_kwargs: object) -> Observation:
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
            self.name = name

        def start_observation(self, **kwargs: object) -> Observation:
            child_name = str(kwargs["name"])
            events.append(f"child:{self.name}:{child_name}")
            if failure_stage == "child-start":
                raise OSError(sentinel)
            return Observation(child_name)

        def update(self, **_kwargs: object) -> None:
            if failure_stage == "child-update" and self.name == "task.structure":
                raise OSError(sentinel)

        def end(self) -> None:
            events.append(f"end:{self.name}")
            if failure_stage == "child-end" and self.name == "task.structure":
                raise OSError(sentinel)

    class Client:
        def start_observation(self, **kwargs: object) -> Observation:
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
            message = f"finish failed at {credential}"
            raise OSError(message)

        def update(self, **_kwargs: object) -> None:
            return None

    class LangfuseClient:
        def start_observation(self, **_kwargs: object) -> Observation:
            starts.append("detached")
            return Observation()

        def start_as_current_observation(self, **_kwargs: object) -> object:
            starts.append("current")
            message = "generation must not attach a current observation"
            raise AssertionError(message)

    class ModelClient:
        def bind(self, **_kwargs: object) -> ModelClient:
            return self

        def invoke(self, _messages: object) -> AIMessage:
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
            if failure_stage == "finish":
                raise OSError(sentinel)

        def update(self, **_kwargs: object) -> None:
            return None

    class Client:
        def start_observation(self, **_kwargs: object) -> Observation:
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
            raise OSError(sentinel)

        def end(self) -> None:
            return None

    class Client:
        def start_observation(self, **_kwargs: object) -> Observation:
            return Observation()

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=sentinel,
    )
    caplog.set_level(logging.WARNING)

    def processing_failure() -> None:
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
            message = f"endpoint failed with {credential_value}"
            raise OSError(message)

        def flush(self) -> None:
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
    """初期化以外の各SDK境界をTask付きwarningへ変換する。"""

    credential = "langfuse-secret-value"
    warnings: list[str] = []

    class Observation:
        def update(self, **_kwargs: object) -> None:
            message = f"update endpoint contains {credential}"
            raise OSError(message)

    class Manager:
        def __enter__(self) -> Observation:
            return Observation()

        def __exit__(self, *_args: object) -> None:
            message = f"finish endpoint contains {credential}"
            raise OSError(message)

    class Client:
        def start_as_current_observation(self, **_kwargs: object) -> Manager:
            return Manager()

        def flush(self) -> None:
            message = f"flush endpoint contains {credential}"
            raise OSError(message)

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=credential,
    )
    caplog.set_level(logging.WARNING)

    def processing_failure() -> None:
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
        message = f"initialization endpoint contains {credential}"
        raise OSError(message)

    def sink_failure(_warning: str) -> None:
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
