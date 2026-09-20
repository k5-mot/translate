"""本処理を妨げないLangfuse観測境界。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from langfuse import Langfuse

from translate.common.redaction import credential_values, redact_text, redact_value

if TYPE_CHECKING:
    from collections.abc import Iterator

    from translate.common.settings import Settings

LOGGER = logging.getLogger(__name__)
WarningSink = Callable[[str], None]
_CREDENTIALS: ContextVar[Sequence[str]] = ContextVar(
    "translate_observation_credentials", default=()
)
_WARNING_SINK: ContextVar[WarningSink | None] = ContextVar(
    "translate_observation_warning_sink", default=None
)
_TASK: ContextVar[str | None] = ContextVar("translate_observation_task", default=None)
ObservationType = Literal[
    "span",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "guardrail",
    "generation",
    "embedding",
]


@lru_cache(maxsize=4)
def _client(public_key: str, secret_key: str, host: str | None) -> Langfuse:
    """同じ接続設定のClientをWorkflow内で共有する。"""

    return Langfuse(public_key=public_key, secret_key=secret_key, base_url=host)


@contextmanager
def bind_observation_context(
    credentials: Sequence[str],
    warning_sink: WarningSink | None,
    task: str | None = None,
) -> Iterator[None]:
    """一回のRunにCredential、warning sink、Taskを隔離して束縛する。"""

    credential_token = _CREDENTIALS.set(tuple(credentials))
    sink_token = _WARNING_SINK.set(warning_sink)
    task_token = _TASK.set(task)
    try:
        yield
    finally:
        _TASK.reset(task_token)
        _WARNING_SINK.reset(sink_token)
        _CREDENTIALS.reset(credential_token)


@contextmanager
def bind_observation_task(task: str) -> Iterator[None]:
    """node内の観測warningへ現在Taskを付与する。"""

    token = _TASK.set(task)
    try:
        yield
    finally:
        _TASK.reset(token)


def _warning(action: str, error: Exception) -> None:
    # Never interpolate exception messages because SDK errors can contain endpoints.
    task = _TASK.get()
    task_suffix = f" task={redact_text(task, _CREDENTIALS.get())}" if task else ""
    warning = (
        f"Langfuse {action} failed ({type(error).__name__}); "
        f"continuing without observation{task_suffix}"
    )
    LOGGER.warning("%s", warning)
    sink = _WARNING_SINK.get()
    if sink is not None:
        try:
            sink(warning)
        except Exception as sink_error:  # noqa: BLE001
            LOGGER.warning(
                "Langfuse warning sink failed (%s); continuing",
                type(sink_error).__name__,
            )


def _get_client(settings: Settings) -> Langfuse | None:
    if not settings.langfuse_enabled:
        return None
    try:
        return _client(
            settings.langfuse_public_key or "",
            settings.langfuse_secret_key or "",
            settings.langfuse_otel_host,
        )
    except Exception as error:  # noqa: BLE001
        _warning("initialization", error)
        return None


@contextmanager
def observe(
    settings: Settings,
    name: str,
    *,
    as_type: ObservationType = "span",
    metadata: dict[str, str] | None = None,
    model: str | None = None,
) -> Iterator[object | None]:
    """秘密や本文を送らず、観測障害時はuntracedで本処理を続ける。"""

    client = _get_client(settings)
    if client is None:
        yield None
        return
    try:
        secrets = tuple(_CREDENTIALS.get()) or credential_values(settings)
        safe_name = redact_text(name, secrets)
        safe_metadata = (
            redact_value(metadata, secrets) if metadata is not None else None
        )
        if as_type in {"generation", "embedding"}:
            manager = client.start_as_current_observation(
                name=safe_name,
                as_type=as_type,
                metadata=safe_metadata,
                model=redact_text(model, secrets) if model is not None else None,
            )
        else:
            manager = client.start_as_current_observation(
                name=safe_name,
                as_type=as_type,
                metadata=safe_metadata,
            )
        observation = manager.__enter__()
    except Exception as error:  # noqa: BLE001
        _warning("start", error)
        yield None
        return

    try:
        yield observation
    except Exception as processing_error:
        try:
            observation.update(
                level="ERROR",
                status_message=type(processing_error).__name__,
            )
        except Exception as error:  # noqa: BLE001
            _warning("update", error)
        try:
            manager.__exit__(
                type(processing_error), processing_error, processing_error.__traceback__
            )
        except Exception as error:  # noqa: BLE001
            _warning("finish", error)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as error:  # noqa: BLE001
            _warning("finish", error)


def flush(settings: Settings) -> None:
    """成功・失敗にかかわらず送信を試み、観測障害だけを警告する。"""

    client = _get_client(settings)
    if client is None:
        return
    try:
        client.flush()
    except Exception as error:  # noqa: BLE001
        _warning("flush", error)
