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
from translate.common.terminal_evidence import count_external_call

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings

ResponseT = TypeVar("ResponseT", bound=BaseModel)
ReasoningEffort = Literal["none", "low", "medium", "high"]
StructuredOutputMode = Literal["prompt", "json-schema"]
ThinkingPolicy = Literal["provider-default", "disabled"]
LLMStage = Literal[
    "vision-invoke",
    "vision-output",
    "vision-parse",
    "text-invoke",
    "text-output",
    "text-parse",
]
LLM_STAGES: tuple[LLMStage, ...] = (
    "vision-invoke",
    "vision-output",
    "vision-parse",
    "text-invoke",
    "text-output",
    "text-parse",
)
LLMFailureKind = Literal["output-truncated"]
LLMFinishReason = Literal["length"]
LLMOrigin = Literal[
    "application",
    "langchain",
    "openai-sdk",
    "transport",
    "local-runtime",
    "unknown",
]
_ORIGIN_MODULE_PREFIXES: tuple[tuple[tuple[str, ...], LLMOrigin], ...] = (
    (("openai",), "openai-sdk"),
    (("httpx", "httpcore"), "transport"),
    (("llama_cpp", "lmstudio", "lms"), "local-runtime"),
    (("langchain", "langchain_core", "langchain_openai"), "langchain"),
    (("translate",), "application"),
)


class LLMOutputTruncatedError(RuntimeError):
    """Modelが最大出力へ到達したことだけを表す安全な原因型。"""


class LLMError(RuntimeError):
    """LLM境界のstageと安全な下位例外型だけを公開する。"""

    def __init__(
        self,
        stage: LLMStage,
        cause: BaseException,
        *,
        failure_kind: LLMFailureKind | None = None,
        finish_reason: LLMFinishReason | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        """公開する失敗stageと数値診断を保持し、原因例外の本文をメッセージへ含めない。"""

        if stage not in LLM_STAGES:
            msg = "invalid LLM stage"
            raise ValueError(msg)
        self.stage = stage
        self.cause_type = type(cause).__name__
        self.failure_kind = failure_kind
        self.finish_reason = finish_reason
        self.input_tokens = _safe_token_count(input_tokens)
        self.output_tokens = _safe_token_count(output_tokens)
        self.total_tokens = _safe_token_count(total_tokens)
        super().__init__(f"LLM request failed during {stage}: {self.cause_type}")


class _LLMAttemptError(Exception):
    """一回の試行結果をraw messageなしでretry loopへ渡す。"""

    def __init__(
        self,
        stage: LLMStage,
        cause: Exception,
        *,
        retryable: bool,
        failure_kind: LLMFailureKind | None = None,
        finish_reason: LLMFinishReason | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        """再試行判断用の原因と診断を内部に保持し、生の原因本文は例外メッセージへ展開しない。"""

        self.stage = stage
        self.cause = cause
        self.retryable = retryable
        self.failure_kind = failure_kind
        self.finish_reason = finish_reason
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        super().__init__("LLM attempt failed")


def _safe_token_count(value: object) -> int | None:
    """Provider metadataからnon-negative integerだけを許可する。"""

    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _exception_chain_types(error: BaseException) -> tuple[str, ...]:
    """例外chainから安全な型名だけを有限件数返す。"""

    names: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(names) < 8:
        seen.add(id(current))
        name = type(current).__name__
        names.append(name if name.isidentifier() else "Exception")
        current = current.__cause__ or current.__context__
    return tuple(names)


def _module_origin(module: str) -> LLMOrigin | None:
    """module名を固定prefixだけでoriginへ分類する。"""

    for prefixes, origin in _ORIGIN_MODULE_PREFIXES:
        if any(
            module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes
        ):
            return origin
    return None


def _exception_origin(error: BaseException) -> LLMOrigin:
    """tracebackのmodule名を固定分類へ縮約し、生のframe情報を返さない。"""

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frames = []
        traceback = current.__traceback__
        while traceback is not None:
            frames.append(traceback.tb_frame)
            traceback = traceback.tb_next
        for frame in reversed(frames):
            module = str(frame.f_globals.get("__name__", ""))
            origin = _module_origin(module)
            if origin is not None:
                return origin
        current = current.__cause__ or current.__context__
    return "unknown"


def _response_diagnostics(
    response: object,
) -> tuple[LLMFinishReason | None, int | None, int | None, int | None]:
    """LangChainの既知metadata形からallowlist値だけを取り出す。"""

    response_metadata = getattr(response, "response_metadata", {})
    usage_metadata = getattr(response, "usage_metadata", {})
    if not isinstance(response_metadata, dict):
        response_metadata = {}
    if not isinstance(usage_metadata, dict):
        usage_metadata = {}
    token_usage = response_metadata.get("token_usage", {})
    if not isinstance(token_usage, dict):
        token_usage = {}
    finish_reason: LLMFinishReason | None = (
        "length" if response_metadata.get("finish_reason") == "length" else None
    )
    input_tokens = _safe_token_count(usage_metadata.get("input_tokens"))
    output_tokens = _safe_token_count(usage_metadata.get("output_tokens"))
    total_tokens = _safe_token_count(usage_metadata.get("total_tokens"))
    return (
        finish_reason,
        input_tokens
        if input_tokens is not None
        else _safe_token_count(token_usage.get("prompt_tokens")),
        output_tokens
        if output_tokens is not None
        else _safe_token_count(token_usage.get("completion_tokens")),
        total_tokens
        if total_tokens is not None
        else _safe_token_count(token_usage.get("total_tokens")),
    )


def _sdk_length_diagnostics(
    error: Exception,
) -> tuple[LLMFinishReason, int | None, int | None, int | None] | None:
    """OpenAI SDKがparse前に投げるlength Errorからallowlist値だけを得る。"""

    error_type = type(error)
    if (
        error_type.__name__ != "LengthFinishReasonError"
        or _module_origin(error_type.__module__) != "openai-sdk"
    ):
        return None
    completion = getattr(error, "completion", None)
    choices = getattr(completion, "choices", None)
    if not isinstance(choices, (list, tuple)) or not choices:
        return None
    if getattr(choices[0], "finish_reason", None) != "length":
        return None
    usage = getattr(completion, "usage", None)
    return (
        "length",
        _safe_token_count(getattr(usage, "prompt_tokens", None)),
        _safe_token_count(getattr(usage, "completion_tokens", None)),
        _safe_token_count(getattr(usage, "total_tokens", None)),
    )


def _model(
    settings: Settings,
    model: str,
    reasoning: ReasoningEffort,
    thinking: ThinkingPolicy,
) -> ChatOpenAI:
    """要求ごとの推論・出力・待機条件を設定し、外側と重複しないようSDK再試行を無効にする。"""

    extra_body: dict[str, object] = {"reasoning_effort": reasoning}
    if thinking == "disabled":
        # The local template hint alone does not prevent Gemma from reopening
        # its thought channel. llama.cpp applies this numeric budget per request.
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        extra_body["thinking_budget_tokens"] = 0
    return ChatOpenAI(
        model=model,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        max_tokens=settings.output_tokens,
        temperature=0,
        max_retries=0,
        timeout=settings.request_timeout_seconds,
        extra_body=extra_body,
    )


def _status_code(error: Exception) -> int | None:
    """SDKとHTTP層で異なる例外形から、再試行判断用のstatus codeを取り出す。"""

    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _invoke_with_retry[ResultT](
    settings: Settings, call: Callable[[], ResultT]
) -> ResultT:
    """再実行可能と判定した失敗だけを有限回再試行し、停止時は安全な公開例外へ変換する。"""

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
                raise LLMError(
                    error.stage,
                    error.cause,
                    failure_kind=error.failure_kind,
                    finish_reason=error.finish_reason,
                    input_tokens=error.input_tokens,
                    output_tokens=error.output_tokens,
                    total_tokens=error.total_tokens,
                ) from None
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
    reasoning: ReasoningEffort,
    schema_mode: StructuredOutputMode = "prompt",
    thinking: ThinkingPolicy = "provider-default",
    image: Path | None = None,
) -> ResponseT:
    """Pydantic schemaに従う応答をLangChain経由で取得する。"""

    parser = PydanticOutputParser(pydantic_object=response_type)
    system_text = (
        system
        if schema_mode == "json-schema"
        else f"{system}\n\n{parser.get_format_instructions()}"
    )
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
    base_client = _model(settings, model, reasoning, thinking)
    client = (
        base_client.bind(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_type.__name__,
                    "strict": True,
                    "schema": response_type.model_json_schema(),
                },
            }
        )
        if schema_mode == "json-schema"
        else base_client
    )
    mode: Literal["vision", "text"] = "vision" if image is not None else "text"
    messages = [SystemMessage(content=system_text), HumanMessage(content=content)]

    def invoke_and_parse() -> ResponseT:
        """一回の送信とschema解析を行い、通信障害・解析失敗・出力切断を再試行判断用に分ける。"""

        invoke_stage: LLMStage = "vision-invoke" if mode == "vision" else "text-invoke"
        try:
            count_external_call("llm")
            response = client.invoke(messages)
        except Exception as error:  # noqa: BLE001
            length = _sdk_length_diagnostics(error)
            if length is not None:
                finish_reason, input_tokens, output_tokens, total_tokens = length
                output_stage: LLMStage = (
                    "vision-output" if mode == "vision" else "text-output"
                )
                raise _LLMAttemptError(
                    output_stage,
                    LLMOutputTruncatedError(),
                    retryable=False,
                    failure_kind="output-truncated",
                    finish_reason=finish_reason,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                ) from None
            status = _status_code(error)
            retryable = (
                isinstance(error, (httpx.TransportError, TypeError))
                or status in {408, 429}
                or (status is not None and status >= 500)
            )
            raise _LLMAttemptError(invoke_stage, error, retryable=retryable) from None

        finish_reason, input_tokens, output_tokens, total_tokens = (
            _response_diagnostics(response)
        )
        if finish_reason == "length":
            output_stage: LLMStage = (
                "vision-output" if mode == "vision" else "text-output"
            )
            raise _LLMAttemptError(
                output_stage,
                LLMOutputTruncatedError(),
                retryable=False,
                failure_kind="output-truncated",
                finish_reason=finish_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )

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
        detached=True,
        metadata={"reasoning": reasoning, "response_type": response_type.__name__},
        model=model,
    ):
        return _invoke_with_retry(settings, invoke_and_parse)
