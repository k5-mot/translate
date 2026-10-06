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

MESSAGE_OVERHEAD_BYTES = 256


class LLMError(RuntimeError):
    """LLM要求が有限再試行後も完了しなかったことを表す。"""


class LLMOutputExceededError(LLMError):
    """LLMが出力上限へ到達し、対象分割が必要であることを表す。"""


class LLMInputExceededError(LLMError):
    """LLM入力が上限を超え、対象分割が必要であることを表す。"""


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
        """単一endpoint設定を保持し、送信はstructuredまで遅延する。

        Args:
            config (Config): 接続先、上限値および処理Optionを保持する設定。

        Raises:
            ValueError: `OpenAI-compatible base URL is required`と判定した場合。
        """

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
        input_tokens: int | None = None,
        output_tokens: int,
        image: Path | None = None,
    ) -> StructuredResult[ResponseT]:
        """一つの論理要求を最大試行数内で送信し、検証済み応答を返す。

        Args:
            model (str): LLM APIへ指定するModel名。
            response_type (type[ResponseT]): 応答を検証するPydantic Model Type。
            system (str): LLMへ渡すSystem Prompt。
            user (str): LLMへ渡すUser Prompt。
            contract (str): 上限値と対応付けるLLM入出力契約名。
            native_schema (dict[str, object]): Providerへ渡すNative JSON Schema。
            input_tokens (int | None): Providerが報告した入力Token数。
            output_tokens (int): Providerが報告した出力Token数。
            image (Path | None): Multimodal Callへ添付する画像File。

        Returns:
            StructuredResult[ResponseT]: 一つの論理要求を最大試行数内で送信し、検証済み応答を返す。

        Raises:
            LLMInputExceededError: `LLM input exceeded the provider context limit`と判定した場合。
            LLMError: `f'LLM structured request failed: {cause}'`と判定した場合。
        """

        _validate_contract(native_schema, contract, self.config)
        deadline = time.monotonic() + self.config.llm_task_deadline_seconds
        validation_retried = False
        feedback = ""
        last_error: Exception | None = None
        for attempt in range(1, self.config.llm_retry_attempts + 1):
            _validate_input_size(
                system=system,
                user=f"{user}{feedback}",
                contract=contract,
                native_schema=native_schema,
                mode=self.config.llm_structured_output_mode,
                maximum_bytes=input_tokens,
            )
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
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    if _is_input_overflow(error):
                        raise LLMInputExceededError(
                            "LLM input exceeded the provider context limit"
                        ) from error
                    raise
                content, finish_reason, used_input_tokens, used_output_tokens = (
                    _response(response)
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
                    input_tokens=used_input_tokens,
                    output_tokens=used_output_tokens,
                )
            except (LLMInputExceededError, LLMOutputExceededError):
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
        """選択されたstructured output方式のOpenAI互換requestを作る。

        Args:
            model (str): LLM APIへ指定するModel名。
            system (str): LLMへ渡すSystem Prompt。
            user (str): LLMへ渡すUser Prompt。
            contract (str): 上限値と対応付けるLLM入出力契約名。
            native_schema (dict[str, object]): Providerへ渡すNative JSON Schema。
            output_tokens (int): Providerが報告した出力Token数。
            image (Path | None): Multimodal Callへ添付する画像File。

        Returns:
            dict[str, object]: 選択されたstructured output方式のOpenAI互換requestを作る。
        """

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
            # Qwen3.8で観測した反復を抑え、訳語への影響を小さくする。
            "repetition_penalty": 1.01,
            "stream": False,
            "max_tokens": output_tokens,
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
    """出力上限による終了を対象分割用の専用例外へ変換する。

    Args:
        finish_reason (str | None): Providerが返した生成終了理由。

    Raises:
        LLMOutputExceededError: `LLM output reached its token limit`と判定した場合。
    """

    if finish_reason == "length":
        raise LLMOutputExceededError("LLM output reached its token limit")


def _validate_input_size(
    *,
    system: str,
    user: str,
    contract: str,
    native_schema: dict[str, object],
    mode: str,
    maximum_bytes: int | None,
) -> None:
    """実送信するtext全体を保守的に1 UTF-8 byte=1 tokenとして検査する。

    Args:
        system (str): LLMへ渡すSystem Prompt。
        user (str): LLMへ渡すUser Prompt。
        contract (str): 上限値と対応付けるLLM入出力契約名。
        native_schema (dict[str, object]): Providerへ渡すNative JSON Schema。
        mode (str): 応答解析または上限判定Mode。
        maximum_bytes (int | None): Payloadへ含められるUTF-8 Byte数の上限。

    Raises:
        LLMInputExceededError: `f'LLM input exceeds task limit: {size} >
            {maximum_bytes}'`と判定した場合。
    """

    if maximum_bytes is None:
        return
    system_text = system if mode == "json_schema" else f"{system}\n\n{contract}"
    schema_text = (
        json.dumps(native_schema, ensure_ascii=False, separators=(",", ":"))
        if mode == "json_schema"
        else ""
    )
    size = (
        len((system_text + user + schema_text).encode("utf-8")) + MESSAGE_OVERHEAD_BYTES
    )
    if size > maximum_bytes:
        raise LLMInputExceededError(
            f"LLM input exceeds task limit: {size} > {maximum_bytes}"
        )


def _is_input_overflow(error: httpx.HTTPStatusError) -> bool:
    """OpenAI互換endpointの入力・context超過応答を識別する。

    Args:
        error (httpx.HTTPStatusError): 記録または分類する例外。

    Returns:
        bool: OpenAI互換endpointの入力・context超過応答を識別する。
    """

    if error.response.status_code == 413:
        return True
    if error.response.status_code != 400:
        return False
    message = error.response.text.casefold()
    return any(
        marker in message
        for marker in (
            "context length",
            "context_length_exceeded",
            "maximum context",
            "prompt is too long",
            "too many tokens",
            "input tokens",
            "input length",
            "maximum sequence length",
            "max sequence length",
        )
    )


def _response(
    response: httpx.Response,
) -> tuple[str, str | None, int | None, int | None]:
    """OpenAI互換応答から本文、終了理由およびtoken使用量を検査して得る。

    Args:
        response (httpx.Response): 保存する検証済みLLM応答Model。

    Returns:
        tuple[str, str | None, int | None, int | None]: 応答本文、終了理由、入力Token数および出力Token数のTuple。

    Raises:
        ValueError: `LLM response must be an object`、`LLM response has no choice`、`LLM
            response content must be text`のいずれかと判定した場合。
    """

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
    """provider値から非負の整数だけをtoken数として採用する。

    Args:
        value (object): Provider応答から取得したToken数候補。

    Returns:
        int | None: provider値から非負の整数だけをtoken数として採用する。
    """

    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _parse_content(content: str, mode: str, maximum_bytes: int) -> object:
    """応答sizeを検査し、prompt方式だけ単一JSON fenceを除去してparseする。

    Args:
        content (str): JSONとして解析するLLM応答本文。
        mode (str): 応答解析または上限判定Mode。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        object: 応答sizeを検査し、prompt方式だけ単一JSON fenceを除去してparseする。

    Raises:
        LLMOutputExceededError: `LLM response exceeds byte limit`と判定した場合。
    """

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
    """structured output契約のbyte数と入れ子深度を安全上限内に限定する。

    Args:
        schema (dict[str, object]): 深さまたは契約を検証するJSON Schema。
        contract (str): 上限値と対応付けるLLM入出力契約名。
        config (Config): 接続先、上限値および処理Optionを保持する設定。

    Raises:
        ValueError: `LLM response contract exceeds byte limit`、`LLM response schema exceeds
            depth limit`のいずれかと判定した場合。
    """

    selected = (
        schema if config.llm_structured_output_mode == "json_schema" else contract
    )
    encoded = json.dumps(selected, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > config.llm_schema_max_bytes:
        raise ValueError("LLM response contract exceeds byte limit")
    if max(0, _schema_depth(schema) - 1) > config.llm_schema_max_depth:
        raise ValueError("LLM response schema exceeds depth limit")


def _schema_depth(schema: object) -> int:
    """JSON Schemaが表すobject/arrayの意味的な最大入れ子深度を返す。

    Args:
        schema (object): 深さまたは契約を検証するJSON Schema。

    Returns:
        int: JSON Schemaが表すobject/arrayの意味的な最大入れ子深度を返す。
    """

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
