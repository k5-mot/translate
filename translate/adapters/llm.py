"""単一OpenAI互換endpointへのstructured output要求。"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    Omit,
    OpenAI,
)
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from openai.types.chat import ChatCompletion

    from translate.common.config import Config

MESSAGE_OVERHEAD_BYTES = 256
logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM要求が完了せず、利用者向けの原因と対策を持つ。"""


class LLMOutputExceededError(LLMError):
    """LLMが出力上限へ到達し、対象分割が必要であることを表す。"""


class LLMOutputTokenExceededError(LLMOutputExceededError):
    """生成が出力token上限で打ち切られたことを表す。"""


class LLMResponseTooLargeError(LLMOutputExceededError):
    """応答本文がbyte数の安全上限を超えたことを表す。"""


class LLMInputExceededError(LLMError):
    """LLM入力が上限を超え、対象分割が必要であることを表す。"""


class LLMTimeoutError(LLMError):
    """LLM要求が時間切れになったことを表す。"""


class LLMConnectionError(LLMError):
    """LLM endpointに接続できなかったことを表す。"""


class LLMRateLimitError(LLMError):
    """LLM endpointがrate limitを返したことを表す。"""


class LLMAuthenticationError(LLMError):
    """LLM endpointが認証または権限不足を返したことを表す。"""


class LLMProviderError(LLMError):
    """LLM endpointがその他のHTTPエラーを返したことを表す。"""


class LLMInvalidResponseError(LLMError):
    """LLM応答がJSONまたは応答契約を満たさなかったことを表す。"""


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
        # SDKは認証値を要求するが、ローカルの無認証endpointへは送らない。
        self.client = OpenAI(
            api_key=config.openai_api_key or "local-no-auth",
            base_url=config.openai_base_url,
            timeout=config.llm_request_timeout_seconds,
            max_retries=0,
        )

    def structured[ResponseT: BaseModel](
        self,
        *,
        task: str,
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
            task (str): Token上限の設定名に用いるTask名。
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
            LLMInputExceededError: 入力予算またはproviderのcontext上限を超えた場合。
            LLMOutputExceededError: 出力token数または応答byte数を超えた場合。
            LLMError: 通信、HTTP応答または応答内容の検証に失敗した場合。
        """

        _validate_contract(native_schema, contract, self.config)
        deadline = time.monotonic() + self.config.llm_task_deadline_seconds
        validation_retried = False
        feedback = ""
        last_error: LLMError | None = None
        last_cause: Exception | None = None
        logger.info("LLM開始 task=%s model=%s", task, model)
        for attempt in range(1, self.config.llm_retry_attempts + 1):
            logger.debug("LLM要求 task=%s attempt=%d", task, attempt)
            _validate_input_size(
                system=system,
                user=f"{user}{feedback}",
                contract=contract,
                native_schema=native_schema,
                mode=self.config.llm_structured_output_mode,
                maximum_bytes=input_tokens,
                task=task,
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
                response = self.client.chat.completions.create(**cast("Any", payload))
                content, finish_reason, used_input_tokens, used_output_tokens = (
                    _response(response)
                )
                _reject_length_finish(finish_reason, task, output_tokens)
                parsed = _parse_content(
                    content,
                    self.config.llm_structured_output_mode,
                    self.config.llm_response_max_bytes,
                )
                validated = response_type.model_validate(parsed)
                logger.info(
                    "LLM完了 task=%s attempt=%d input_tokens=%s output_tokens=%s",
                    task,
                    attempt,
                    used_input_tokens,
                    used_output_tokens,
                )
                return StructuredResult(
                    response=validated,
                    attempts=attempt,
                    input_tokens=used_input_tokens,
                    output_tokens=used_output_tokens,
                )
            except (LLMInputExceededError, LLMOutputExceededError) as error:
                logger.warning("LLM失敗 task=%s type=%s", task, type(error).__name__)
                raise
            except (
                APIResponseValidationError,
                ValueError,
                UnicodeError,
                ValidationError,
            ) as error:
                last_cause = error
                last_error = LLMInvalidResponseError(
                    "LLM応答がJSON形式または契約に適合しません。対策: "
                    "LLM_STRUCTURED_OUTPUT_MODEとmodelの対応を確認してください。"
                )
                if validation_retried or attempt >= self.config.llm_retry_attempts:
                    break
                validation_retried = True
                feedback = (
                    "\n\nThe previous response was invalid JSON or violated the contract. "
                    "Return one complete JSON object matching the contract exactly."
                )
            except APITimeoutError as error:
                last_cause = error
                last_error = LLMTimeoutError(
                    f"LLM要求が{self.config.llm_request_timeout_seconds:g}秒で時間切れです。"
                    "対策: LLM_REQUEST_TIMEOUT_SECONDSとendpointの負荷を確認してください。"
                )
                if attempt >= self.config.llm_retry_attempts:
                    break
            except APIConnectionError as error:
                last_cause = error
                last_error = LLMConnectionError(
                    "LLM endpointへ接続できません。対策: OPENAI_BASE_URLと"
                    "endpointの稼働・ネットワークを確認してください。"
                )
                if attempt >= self.config.llm_retry_attempts:
                    break
            except APIStatusError as error:
                if _is_input_overflow(error):
                    raise LLMInputExceededError(
                        "providerのcontext上限を超えました。対策: "
                        "LLM_CONTEXT_TOKENSと各Taskの入力・出力予算を"
                        "endpointの実際の上限以内に設定してください。"
                    ) from error
                last_cause = error
                last_error = _provider_error(error)
                if error.status_code not in {408, 429} and error.status_code < 500:
                    break
                if attempt >= self.config.llm_retry_attempts:
                    break
            except APIError as error:
                last_cause = error
                last_error = LLMProviderError(
                    "OpenAI Python clientがLLM応答を処理できません。対策: "
                    "endpointの応答形式とサーバーログを確認してください。"
                )
                break
            if time.monotonic() >= deadline:
                break
            logger.warning(
                "LLM再試行 task=%s attempt=%d type=%s",
                task,
                attempt,
                type(last_error).__name__,
            )
            delay = min(2 ** (attempt - 1), max(0.0, deadline - time.monotonic()))
            if delay > 0:
                time.sleep(random.uniform(0, delay))  # noqa: S311
        if last_error is None:
            logger.warning("LLM失敗 task=%s type=LLMTimeoutError", task)
            raise LLMTimeoutError(
                "LLM Callの期限に達しました。対策: "
                "LLM_TASK_DEADLINE_SECONDSとendpointの負荷を確認してください。"
            )
        logger.warning("LLM失敗 task=%s type=%s", task, type(last_error).__name__)
        raise last_error from last_cause

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
        """選択されたstructured output方式のSDK要求引数を作る。

        Args:
            model (str): LLM APIへ指定するModel名。
            system (str): LLMへ渡すSystem Prompt。
            user (str): LLMへ渡すUser Prompt。
            contract (str): 上限値と対応付けるLLM入出力契約名。
            native_schema (dict[str, object]): Providerへ渡すNative JSON Schema。
            output_tokens (int): Providerが報告した出力Token数。
            image (Path | None): Multimodal Callへ添付する画像File。

        Returns:
            dict[str, object]: Chat Completions SDKへ渡す引数。
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
            "stream": False,
            "max_tokens": output_tokens,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "top_p": 0.80,
            "extra_body": {
                "top_k": 20,
                "min_p": 0.0,
                "presence_penalty": 1.5,
                "repetition_penalty": 1.01,
                "enable_thinking": False,
                "preserve_thinking": False,
                "chat_template_kwargs": {
                    "enable_thinking": False,
                    "preserve_thinking": False,
                },
            },
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
        if not self.config.openai_api_key:
            payload["extra_headers"] = {"Authorization": Omit()}
        return payload


def _reject_length_finish(
    finish_reason: str | None, task: str, output_tokens: int
) -> None:
    """出力上限による終了を対象分割用の専用例外へ変換する。

    Args:
        finish_reason (str | None): Providerが返した生成終了理由。
        task (str): Token上限の設定名に用いるTask名。
        output_tokens (int): 要求へ指定した最大出力Token数。

    Raises:
        LLMOutputTokenExceededError: 生成が出力Token上限へ到達した場合。
        LLMInvalidResponseError: content filterで生成が停止した場合。
    """

    if finish_reason == "length":
        setting = f"{task}_OUTPUT_TOKENS"
        raise LLMOutputTokenExceededError(
            f"出力トークン上限に到達しました ({setting}={output_tokens})。対策: "
            f"{setting}を増やし、LLM_CONTEXT_TOKENS内に収めてください。"
        )
    if finish_reason == "content_filter":
        raise LLMInvalidResponseError(
            "LLM応答がcontent filterで停止しました。対策: "
            "入力内容とendpointのfilter設定を確認してください。"
        )


def _validate_input_size(
    *,
    system: str,
    user: str,
    contract: str,
    native_schema: dict[str, object],
    mode: str,
    maximum_bytes: int | None,
    task: str,
) -> None:
    """実送信するtext全体を保守的に1 UTF-8 byte=1 tokenとして検査する。

    Args:
        system (str): LLMへ渡すSystem Prompt。
        user (str): LLMへ渡すUser Prompt。
        contract (str): 上限値と対応付けるLLM入出力契約名。
        native_schema (dict[str, object]): Providerへ渡すNative JSON Schema。
        mode (str): 応答解析または上限判定Mode。
        maximum_bytes (int | None): Payloadへ含められるUTF-8 Byte数の上限。
        task (str): Token上限の設定名に用いるTask名。

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
            f"LLM input exceeds task limit: {size} > {maximum_bytes}。対策: "
            f"{task}_INPUT_TOKENSを増やし、LLM_CONTEXT_TOKENS内に収めてください。"
        )


def _is_input_overflow(error: APIStatusError) -> bool:
    """OpenAI互換endpointの入力・context超過応答を識別する。

    Args:
        error (APIStatusError): 記録または分類する例外。

    Returns:
        bool: OpenAI互換endpointの入力・context超過応答を識別する。
    """

    if error.status_code == 413:
        return True
    if error.status_code != 400:
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


def _provider_error(error: APIStatusError) -> LLMError:
    """HTTP statusを秘密情報を含まない原因と対策へ変換する。

    Args:
        error (APIStatusError): SDKが返したHTTPエラー。

    Returns:
        LLMError: status別の利用者向けエラー。
    """

    status = error.status_code
    if status == 408:
        return LLMTimeoutError(
            "LLM endpointがHTTP 408で時間切れを返しました。対策: "
            "LLM_REQUEST_TIMEOUT_SECONDSとendpointの負荷を確認してください。"
        )
    if status in {401, 403}:
        return LLMAuthenticationError(
            f"LLM認証・権限エラー (HTTP {status})。対策: "
            "OPENAI_API_KEYとendpointの権限を確認してください。"
        )
    if status == 429:
        return LLMRateLimitError(
            "LLM endpointのrate limitに達しました (HTTP 429)。対策: "
            "同時実行数を減らすか、endpointの制限を確認してください。"
        )
    if status >= 500:
        return LLMProviderError(
            f"LLM endpointがHTTP {status}を返しました。対策: "
            "endpointの稼働状態とサーバーログを確認してください。"
        )
    return LLMProviderError(
        f"LLM要求がHTTP {status}で拒否されました。対策: "
        "model名、structured output方式とendpointの対応を確認してください。"
    )


def _response(
    response: ChatCompletion,
) -> tuple[str, str | None, int | None, int | None]:
    """OpenAI互換応答から本文、終了理由およびtoken使用量を検査して得る。

    Args:
        response (ChatCompletion): SDKが返したLLM応答。

    Returns:
        tuple[str, str | None, int | None, int | None]: 応答本文、終了理由、入力Token数および出力Token数のTuple。

    Raises:
        ValueError: `LLM response must be an object`、`LLM response has no choice`、`LLM
            response content must be text`のいずれかと判定した場合。
    """

    if not response.choices:
        raise ValueError("LLM response has no choice")
    choice = response.choices[0]
    content = choice.message.content
    if not isinstance(content, str) and choice.finish_reason != "length":
        raise ValueError("LLM response content must be text")
    usage = response.usage
    return (
        content if isinstance(content, str) else "",
        choice.finish_reason,
        _token_count(usage.prompt_tokens if usage else None),
        _token_count(usage.completion_tokens if usage else None),
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
        LLMResponseTooLargeError: 応答本文がbyte数の安全上限を超えた場合。
    """

    if len(content.encode("utf-8")) > maximum_bytes:
        raise LLMResponseTooLargeError(
            f"LLM応答が{maximum_bytes} byteの安全上限を超えました。対策: "
            "LLM_RESPONSE_MAX_BYTESを上限内で増やすか、対象件数を減らしてください。"
        )
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
