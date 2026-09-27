"""単一OpenAI互換endpointへのstructured output要求。"""

from __future__ import annotations

import base64
import json
import mimetypes
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.config import Config


class LLMError(RuntimeError):
    """LLM要求が有限再試行後も完了しなかったことを表す。"""


class LLMOutputExceededError(LLMError):
    """LLMが出力上限へ到達し、対象分割が必要であることを表す。"""


@dataclass(frozen=True, slots=True)
class StructuredResult[ResponseT: BaseModel]:
    """検証済みLLM応答と再開診断に必要な使用量。"""

    response: ResponseT
    attempts: int
    input_tokens: int | None
    output_tokens: int | None


class LLMClient:
    """生成LLMの接続、再試行、JSON parseおよびPydantic検証を隠蔽する。"""

    def __init__(self, config: Config) -> None:
        """単一endpoint設定を保持し、送信はstructuredまで遅延する。"""

        if config.openai_base_url is None:
            raise ValueError("OpenAI-compatible base URL is required")
        self.config = config
        self.url = f"{config.openai_base_url.rstrip('/')}/chat/completions"
        self.headers = {"Content-Type": "application/json"}
        if config.openai_api_key:
            self.headers["Authorization"] = f"Bearer {config.openai_api_key}"

    def structured[ResponseT: BaseModel](
        self,
        *,
        model: str,
        response_type: type[ResponseT],
        system: str,
        user: str,
        contract: str,
        native_schema: dict[str, object],
        output_tokens: int,
        image: Path | None = None,
    ) -> StructuredResult[ResponseT]:
        """一つの論理要求を最大試行数内で送信し、検証済み応答を返す。"""

        _validate_contract(native_schema, contract, self.config)
        deadline = time.monotonic() + self.config.llm_task_deadline_seconds
        validation_retried = False
        feedback = ""
        last_error: Exception | None = None
        for attempt in range(1, self.config.llm_retry_attempts + 1):
            payload = self._payload(
                model=model,
                system=system,
                user=f"{user}{feedback}",
                contract=contract,
                native_schema=native_schema,
                output_tokens=output_tokens,
                image=image,
            )
            try:
                response = httpx.post(
                    self.url,
                    headers=self.headers,
                    json=payload,
                    timeout=self.config.llm_request_timeout_seconds,
                )
                response.raise_for_status()
                content, finish_reason, input_tokens, used_output_tokens = _response(
                    response
                )
                _reject_length_finish(finish_reason)
                parsed = _parse_content(
                    content,
                    self.config.llm_structured_output_mode,
                    self.config.llm_response_max_bytes,
                )
                validated = response_type.model_validate(parsed)
                return StructuredResult(
                    response=validated,
                    attempts=attempt,
                    input_tokens=input_tokens,
                    output_tokens=used_output_tokens,
                )
            except LLMOutputExceededError:
                raise
            except (ValueError, UnicodeError, ValidationError) as error:
                last_error = error
                if validation_retried or attempt >= self.config.llm_retry_attempts:
                    break
                validation_retried = True
                feedback = (
                    "\n\nThe previous response was invalid JSON or violated the contract. "
                    "Return one complete JSON object matching the contract exactly."
                )
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                last_error = error
                status = (
                    error.response.status_code
                    if isinstance(error, httpx.HTTPStatusError)
                    else None
                )
                retryable = status is None or status in {408, 429} or status >= 500
                if not retryable or attempt >= self.config.llm_retry_attempts:
                    break
            if time.monotonic() >= deadline:
                break
            delay = min(2 ** (attempt - 1), max(0.0, deadline - time.monotonic()))
            if delay > 0:
                time.sleep(random.uniform(0, delay))  # noqa: S311
        cause = type(last_error).__name__ if last_error is not None else "deadline"
        raise LLMError(f"LLM structured request failed: {cause}") from last_error

    def _payload(
        self,
        *,
        model: str,
        system: str,
        user: str,
        contract: str,
        native_schema: dict[str, object],
        output_tokens: int,
        image: Path | None,
    ) -> dict[str, object]:
        """選択されたstructured output方式のOpenAI互換requestを作る。"""

        mode = self.config.llm_structured_output_mode
        system_text = system if mode == "json_schema" else f"{system}\n\n{contract}"
        user_content: str | list[dict[str, object]] = user
        if image is not None:
            mime = mimetypes.guess_type(image.name)[0] or "image/png"
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            user_content = [
                {"type": "text", "text": user},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                },
            ]
        payload: dict[str, object] = {
            "model": model,
            "temperature": 0,
            "stream": False,
            "max_tokens": output_tokens,
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
            "thinking_budget_tokens": 0,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_content},
            ],
        }
        if mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        elif mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": native_schema,
                },
            }
        return payload


def _reject_length_finish(finish_reason: str | None) -> None:
    """出力上限による終了を対象分割用の専用例外へ変換する。"""

    if finish_reason == "length":
        raise LLMOutputExceededError("LLM output reached its token limit")


def _response(
    response: httpx.Response,
) -> tuple[str, str | None, int | None, int | None]:
    """OpenAI互換応答から本文、終了理由およびtoken使用量を検査して得る。"""

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("LLM response has no choice")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("LLM response content must be text")
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return (
        content,
        str(choices[0].get("finish_reason"))
        if choices[0].get("finish_reason")
        else None,
        _token_count(usage.get("prompt_tokens")),
        _token_count(usage.get("completion_tokens")),
    )


def _token_count(value: object) -> int | None:
    """provider値から非負の整数だけをtoken数として採用する。"""

    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _parse_content(content: str, mode: str, maximum_bytes: int) -> object:
    """応答sizeを検査し、prompt方式だけ単一JSON fenceを除去してparseする。"""

    if len(content.encode("utf-8")) > maximum_bytes:
        raise LLMOutputExceededError("LLM response exceeds byte limit")
    value = content.strip()
    if mode == "prompt" and value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    return json.loads(value)


def _validate_contract(
    schema: dict[str, object],
    contract: str,
    config: Config,
) -> None:
    """structured output契約のbyte数と入れ子深度を安全上限内に限定する。"""

    selected = (
        schema if config.llm_structured_output_mode == "json_schema" else contract
    )
    encoded = json.dumps(selected, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > config.llm_schema_max_bytes:
        raise ValueError("LLM response contract exceeds byte limit")
    if max(0, _schema_depth(schema) - 1) > config.llm_schema_max_depth:
        raise ValueError("LLM response schema exceeds depth limit")


def _schema_depth(schema: object) -> int:
    """JSON Schemaが表すobject/arrayの意味的な最大入れ子深度を返す。"""

    if not isinstance(schema, dict):
        return 0
    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties", {})
        children = properties.values() if isinstance(properties, dict) else []
        return 1 + max((_schema_depth(item) for item in children), default=0)
    if schema_type == "array":
        return 1 + _schema_depth(schema.get("items"))
    return 0
