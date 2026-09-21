"""LangChainによるOpenAI互換LLM呼出し。"""

from __future__ import annotations

import base64
import json
import mimetypes
import random
import time
from typing import TYPE_CHECKING, Any, Literal, TypeVar

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from translate.adapters.langfuse import observe

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings

ResponseT = TypeVar("ResponseT", bound=BaseModel)
LLMStage = Literal[
    "vision-invoke",
    "vision-parse",
    "text-invoke",
    "text-parse",
]
LLM_STAGES: tuple[LLMStage, ...] = (
    "vision-invoke",
    "vision-parse",
    "text-invoke",
    "text-parse",
)


class LLMError(RuntimeError):
    """LLM境界のstageと安全な下位例外型だけを公開する。"""

    def __init__(self, stage: LLMStage, cause: BaseException) -> None:
        if stage not in LLM_STAGES:
            msg = "invalid LLM stage"
            raise ValueError(msg)
        self.stage = stage
        self.cause_type = type(cause).__name__
        super().__init__(f"LLM request failed during {stage}: {self.cause_type}")


class _LLMAttemptError(Exception):
    """一回の試行結果をraw messageなしでretry loopへ渡す。"""

    def __init__(self, stage: LLMStage, cause: Exception, *, retryable: bool) -> None:
        self.stage = stage
        self.cause = cause
        self.retryable = retryable
        super().__init__("LLM attempt failed")


def _model(settings: Settings, model: str, reasoning: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        max_tokens=settings.output_tokens,
        temperature=0,
        max_retries=0,
        timeout=settings.request_timeout_seconds,
        extra_body={"reasoning_effort": reasoning},
    )


def _status_code(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _invoke_with_retry[ResultT](
    settings: Settings, call: Callable[[], ResultT]
) -> ResultT:
    deadline = time.monotonic() + settings.task_deadline_seconds
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            return call()
        except _LLMAttemptError as error:
            if (
                not error.retryable
                or attempt >= settings.retry_attempts
                or time.monotonic() >= deadline
            ):
                raise LLMError(error.stage, error.cause) from None
            delay = min(
                settings.retry_base_seconds * (2 ** (attempt - 1)),
                settings.retry_max_seconds,
            )
            time.sleep(
                random.uniform(  # noqa: S311
                    0, min(delay, max(0.0, deadline - time.monotonic()))
                )
            )
    msg = "LLM request exhausted without response"
    raise RuntimeError(msg)


def structured[ResponseT: BaseModel](
    settings: Settings,
    model: str,
    response_type: type[ResponseT],
    system: str,
    user: str,
    *,
    reasoning: str,
    image: Path | None = None,
) -> ResponseT:
    """Pydantic schemaに従う応答をLangChain経由で取得する。"""

    parser = PydanticOutputParser(pydantic_object=response_type)
    system_text = f"{system}\n\n{parser.get_format_instructions()}"
    content: str | list[str | dict[Any, Any]] = user
    if image is not None:
        mime = mimetypes.guess_type(image.name)[0] or "image/png"
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": user},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            },
        ]
    client = _model(settings, model, reasoning)
    mode: Literal["vision", "text"] = "vision" if image is not None else "text"
    messages = [SystemMessage(content=system_text), HumanMessage(content=content)]

    def invoke_and_parse() -> ResponseT:
        invoke_stage: LLMStage = "vision-invoke" if mode == "vision" else "text-invoke"
        try:
            response = client.invoke(messages)
        except Exception as error:  # noqa: BLE001
            status = _status_code(error)
            retryable = (
                isinstance(error, (httpx.TransportError, TypeError))
                or status in {408, 429}
                or (status is not None and status >= 500)
            )
            raise _LLMAttemptError(invoke_stage, error, retryable=retryable) from None

        parse_stage: LLMStage = "vision-parse" if mode == "vision" else "text-parse"
        try:
            value = response.content
            if not isinstance(value, str):
                value = str(value)
            return parser.parse(value)
        except (
            TypeError,
            json.JSONDecodeError,
            OutputParserException,
            ValidationError,
        ) as error:
            raise _LLMAttemptError(parse_stage, error, retryable=True) from None

    with observe(
        settings,
        "llm.request",
        as_type="generation",
        metadata={"reasoning": reasoning, "response_type": response_type.__name__},
        model=model,
    ):
        return _invoke_with_retry(settings, invoke_and_parse)
