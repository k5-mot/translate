"""Langfuse観測の接続範囲と障害分離を検証する。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import AIMessage
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
        "metadata": {"reasoning": "low", "response_type": "_Response"},
        "model": "safe-model-name",
    }
    assert "secret" not in repr(captured)


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
