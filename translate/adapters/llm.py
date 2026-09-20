"""LangChainによるOpenAI互換LLM呼出し。"""

from __future__ import annotations

import base64
import mimetypes
import random
import time
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from translate.adapters.langfuse import observe

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings

ResponseT = TypeVar("ResponseT", bound=BaseModel)


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


def _invoke_with_retry(settings: Settings, call: Callable[[], Any]) -> Any:
    deadline = time.monotonic() + settings.task_deadline_seconds
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            return call()
        except Exception as error:
            status = _status_code(error)
            retryable = (
                isinstance(error, httpx.TransportError)
                or status in {408, 429}
                or (status is not None and status >= 500)
            )
            if (
                not retryable
                or attempt >= settings.retry_attempts
                or time.monotonic() >= deadline
            ):
                raise
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
    with observe(
        settings,
        "llm.request",
        as_type="generation",
        metadata={"reasoning": reasoning, "response_type": response_type.__name__},
        model=model,
    ):
        response = _invoke_with_retry(
            settings,
            lambda: client.invoke(
                [SystemMessage(content=system_text), HumanMessage(content=content)]
            ),
        )
        value = response.content
        if not isinstance(value, str):
            value = str(value)
        return parser.parse(value)
