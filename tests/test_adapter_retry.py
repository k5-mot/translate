"""外部Adapterの有限retryと恒久Error分類を検証する。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from translate.adapters import docling, libretranslate, llm

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def _response(
    status: int, payload: object = None, content: bytes = b""
) -> httpx.Response:
    request = httpx.Request("GET", "https://service.invalid")
    if payload is None:
        return httpx.Response(status, request=request, content=content)
    return httpx.Response(status, request=request, json=payload)


def test_libretranslate_retries_5xx_and_stops_on_permanent_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5xxだけを有限retryし、400は一回で失敗する。"""

    responses = iter([_response(503), _response(200, {"translatedText": ["訳"]})])
    calls = 0

    def post(*_args: object, **_kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(libretranslate.httpx, "post", post)
    monkeypatch.setattr(libretranslate.time, "sleep", lambda _value: None)

    assert libretranslate.translate_texts(
        "https://libre.invalid", None, ["source"], retry_base_seconds=0
    ) == ["訳"]
    assert calls == 2

    calls = 0

    def permanent(*_args: object, **_kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(400)

    monkeypatch.setattr(libretranslate.httpx, "post", permanent)
    with pytest.raises(httpx.HTTPStatusError):
        libretranslate.translate_texts("https://libre.invalid", None, ["source"])
    assert calls == 1


def test_docling_retries_submit_and_uses_configured_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docling submitの一時障害をretryし、設定timeoutを全requestへ渡す。"""

    submit_calls: list[float] = []

    def post(*_args: object, **kwargs: object) -> httpx.Response:
        submit_calls.append(float(kwargs["timeout"]))
        if len(submit_calls) == 1:
            return _response(503)
        return _response(200, {"task_id": "task-1"})

    def get(url: str, **kwargs: object) -> httpx.Response:
        assert kwargs["timeout"] == 12.5
        if "/status/" in url:
            return _response(200, {"status": "completed"})
        return _response(200, content=b"zip-result")

    monkeypatch.setattr(docling.httpx, "post", post)
    monkeypatch.setattr(docling.httpx, "get", get)
    monkeypatch.setattr(docling.time, "sleep", lambda _value: None)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    client = docling.DoclingClient(
        "https://docling.invalid",
        retry_attempts=3,
        retry_base_seconds=0,
        timeout_seconds=12.5,
    )

    payload, job = client.convert(source)

    assert payload == b"zip-result"
    assert job["task_id"] == "task-1"
    assert submit_calls == [12.5, 12.5]


class RetryResponse(BaseModel):
    """LLM retry test用のstructured response。"""

    value: str


def test_llm_schema_mode_binds_strict_response_format_without_prompt_duplication(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Schema modeはProvider制約を一度だけ設定しpromptへ重複しない。"""

    seen: dict[str, object] = {}

    class Client:
        def bind(self, **kwargs: object) -> Client:
            seen["bind"] = kwargs
            return self

        def invoke(self, messages: object) -> AIMessage:
            seen["messages"] = messages
            return AIMessage(content='{"value":"ok"}')

    def model(_settings: Settings, name: str, reasoning: str) -> Client:
        seen["model"] = name
        seen["reasoning"] = reasoning
        return Client()

    format_calls = 0

    def format_instructions(_parser: object) -> str:
        nonlocal format_calls
        format_calls += 1
        return "FORMAT-INSTRUCTION-SENTINEL"

    monkeypatch.setattr(llm, "_model", model)
    monkeypatch.setattr(
        llm.PydanticOutputParser, "get_format_instructions", format_instructions
    )

    result = llm.structured(
        settings_factory(),
        "structure-model",
        RetryResponse,
        "system rules",
        "user payload",
        reasoning="none",
        schema_mode="json-schema",
    )

    assert result == RetryResponse(value="ok")
    assert seen["model"] == "structure-model"
    assert seen["reasoning"] == "none"
    assert seen["bind"] == {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "RetryResponse",
                "strict": True,
                "schema": RetryResponse.model_json_schema(),
            },
        }
    }
    messages = seen["messages"]
    assert isinstance(messages, list)
    assert messages[0].content == "system rules"
    assert "FORMAT-INSTRUCTION-SENTINEL" not in str(messages)
    assert format_calls == 0


def test_llm_schema_mode_preserves_retry_and_parse_contracts(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Schema modeでもtransportとparseだけを有限retryする。"""

    calls = 0
    bind_calls = 0

    class Client:
        def bind(self, **_kwargs: object) -> Client:
            nonlocal bind_calls
            bind_calls += 1
            return self

        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            if calls == 1:
                message = "SECRET-TRANSPORT"
                raise httpx.ConnectError(message)
            if calls == 2:
                return AIMessage(content="SECRET-MALFORMED")
            return AIMessage(content='{"value":"ok"}')

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())
    monkeypatch.setattr(llm.time, "sleep", lambda _value: None)

    result = llm.structured(
        settings_factory(retry_attempts=3, retry_base_seconds=0),
        "model",
        RetryResponse,
        "system",
        "user",
        reasoning="none",
        schema_mode="json-schema",
    )

    assert result.value == "ok"
    assert calls == 3
    assert bind_calls == 1


def test_llm_schema_mode_classifies_length_before_parse(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Schema modeの途中応答もparseせず安全な出力枯渇にする。"""

    calls = 0

    class Client:
        def bind(self, **_kwargs: object) -> Client:
            return self

        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            return AIMessage(
                content="SECRET-PARTIAL",
                response_metadata={
                    "finish_reason": "length",
                    "token_usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                },
            )

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())

    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings_factory(retry_attempts=3),
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="none",
            schema_mode="json-schema",
        )

    assert calls == 1
    assert captured.value.stage == "text-output"
    assert captured.value.failure_kind == "output-truncated"
    assert captured.value.finish_reason == "length"
    assert captured.value.output_tokens == 20
    assert "SECRET-PARTIAL" not in str(captured.value)


def test_llm_schema_mode_normalizes_sdk_length_error_without_raw_completion(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """SDKが先に投げるlength Errorから安全なusageだけを保持する。"""

    calls = 0
    length_error_type = type("LengthFinishReasonError", (Exception,), {})
    length_error_type.__module__ = "openai"
    error = length_error_type("SECRET-RAW-COMPLETION")
    error.completion = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="length")],
        usage=SimpleNamespace(
            prompt_tokens=1_324,
            completion_tokens=16_384,
            total_tokens=17_708,
        ),
    )

    class Client:
        def bind(self, **_kwargs: object) -> Client:
            return self

        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            raise error

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())

    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings_factory(retry_attempts=3),
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="none",
            schema_mode="json-schema",
        )

    assert calls == 1
    assert captured.value.stage == "text-output"
    assert captured.value.cause_type == "LLMOutputTruncatedError"
    assert captured.value.failure_kind == "output-truncated"
    assert captured.value.finish_reason == "length"
    assert captured.value.input_tokens == 1_324
    assert captured.value.output_tokens == 16_384
    assert captured.value.total_tokens == 17_708
    assert "SECRET-RAW-COMPLETION" not in str(captured.value)


def test_llm_schema_mode_does_not_retry_permanent_400(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Providerがschema policyを拒否した400は一回で停止する。"""

    calls = 0
    request = httpx.Request("POST", "https://service.invalid")
    response = httpx.Response(400, request=request)

    class Client:
        def bind(self, **_kwargs: object) -> Client:
            return self

        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            message = "SECRET-PROVIDER-REJECTION"
            raise httpx.HTTPStatusError(message, request=request, response=response)

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())

    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings_factory(retry_attempts=3),
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="none",
            schema_mode="json-schema",
        )

    assert calls == 1
    assert captured.value.stage == "text-invoke"
    assert captured.value.cause_type == "HTTPStatusError"
    assert "SECRET-PROVIDER-REJECTION" not in str(captured.value)


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("translate.fake", "application"),
        ("langchain_openai.fake", "langchain"),
        ("openai.fake", "openai-sdk"),
        ("httpx.fake", "transport"),
        ("lmstudio.fake", "local-runtime"),
        ("unrelated.fake", "unknown"),
    ],
)
def test_llm_origin_diagnostic_reduces_traceback_without_raw_values(
    module: str, expected: str
) -> None:
    """診断wrapperはframeを固定originへ縮約しraw値を返さない。"""

    sentinel = "SECRET-PATH-PROMPT-RESPONSE"
    namespace: dict[str, object] = {"__name__": module, "sentinel": sentinel}
    exec("def fail():\n    raise TypeError(sentinel)", namespace)  # noqa: S102
    fail = namespace["fail"]

    try:
        fail()  # type: ignore[operator]
    except TypeError as error:
        origin = llm._exception_origin(error)  # noqa: SLF001
        chain = llm._exception_chain_types(error)  # noqa: SLF001
    else:  # pragma: no cover - helper always raises
        pytest.fail("diagnostic fixture did not raise")

    assert origin == expected
    assert chain == ("TypeError",)
    assert sentinel not in origin
    assert all(sentinel not in item for item in chain)


def test_llm_origin_diagnostic_follows_exception_chain_once() -> None:
    """cause chainを循環せず調べ、安全な型名だけを返す。"""

    namespace: dict[str, object] = {"__name__": "openai._base_client"}
    exec(  # noqa: S102
        "def fail():\n"
        "    try:\n"
        "        raise TypeError('SECRET-INNER')\n"
        "    except TypeError as error:\n"
        "        raise RuntimeError('SECRET-OUTER') from error",
        namespace,
    )

    with pytest.raises(RuntimeError) as captured:
        namespace["fail"]()  # type: ignore[operator]

    assert llm._exception_origin(captured.value) == "openai-sdk"  # noqa: SLF001
    assert llm._exception_chain_types(captured.value) == (  # noqa: SLF001
        "RuntimeError",
        "TypeError",
    )


def test_llm_retries_network_errors_and_exhausts_at_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """LLM Network Errorを既定回数内でretryし、上限後は伝播する。"""

    calls = 0

    class Client:
        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            if calls < 3:
                message = "temporary"
                raise httpx.ConnectError(message)
            return AIMessage(content='{"value":"ok"}')

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())
    monkeypatch.setattr(llm.time, "sleep", lambda _value: None)
    settings = settings_factory(retry_attempts=3, retry_base_seconds=0)

    result = llm.structured(
        settings,
        "model",
        RetryResponse,
        "system",
        "user",
        reasoning="low",
    )

    assert result.value == "ok"
    assert calls == 3

    calls = 0

    class FailingClient:
        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            message = "persistent"
            raise httpx.ConnectError(message)

    monkeypatch.setattr(llm, "_model", lambda *_args: FailingClient())
    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings,
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )
    assert calls == 3
    assert captured.value.stage == "text-invoke"
    assert captured.value.cause_type == "ConnectError"
    assert "persistent" not in str(captured.value)


def test_llm_retries_boundary_type_and_parse_errors_without_leaking_content(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """invoke TypeErrorとmalformed responseを有限retryして安全に正規化する。"""

    sentinel = "SECRET-PROMPT-OR-RAW-RESPONSE"
    sleeps: list[float] = []
    calls = 0

    class BrokenResponse:
        @property
        def content(self) -> str:
            raise TypeError(sentinel)

    class Client:
        def invoke(self, _messages: object) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TypeError(sentinel)
            if calls == 2:
                return BrokenResponse()
            if calls == 3:
                return AIMessage(content=sentinel)
            return AIMessage(content='{"value":"ok"}')

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    monkeypatch.setattr(llm.random, "uniform", lambda _start, end: end)
    settings = settings_factory(retry_attempts=4, retry_base_seconds=0.25)

    result = llm.structured(
        settings,
        "model",
        RetryResponse,
        "system",
        "user",
        reasoning="low",
    )

    assert result.value == "ok"
    assert calls == 4
    assert sleeps == [0.25, 0.5, 1.0]

    calls = 0

    class MalformedClient:
        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            return AIMessage(content=sentinel)

    monkeypatch.setattr(llm, "_model", lambda *_args: MalformedClient())
    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings,
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )

    assert calls == 4
    assert captured.value.stage == "text-parse"
    assert captured.value.cause_type == "OutputParserException"
    assert sentinel not in str(captured.value)


def test_llm_does_not_retry_permanent_or_outside_boundary_errors(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """恒久4xxとClient構築TypeErrorは一度で停止する。"""

    calls = 0
    request = httpx.Request("POST", "https://service.invalid")
    response = httpx.Response(400, request=request)

    class Client:
        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            message = "permanent raw response"
            raise httpx.HTTPStatusError(message, request=request, response=response)

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())
    monkeypatch.setattr(llm.time, "sleep", lambda _value: None)
    settings = settings_factory(retry_attempts=3, retry_base_seconds=0)

    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings,
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )

    assert calls == 1
    assert captured.value.stage == "text-invoke"
    assert captured.value.cause_type == "HTTPStatusError"
    assert "raw response" not in str(captured.value)

    model_calls = 0

    def invalid_model(*_args: object) -> object:
        nonlocal model_calls
        model_calls += 1
        message = "invalid client configuration"
        raise TypeError(message)

    monkeypatch.setattr(llm, "_model", invalid_model)
    with pytest.raises(TypeError, match="invalid client configuration"):
        llm.structured(
            settings,
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )
    assert model_calls == 1

    prompt_calls = 0

    def invalid_prompt(_parser: object) -> str:
        nonlocal prompt_calls
        prompt_calls += 1
        message = "invalid prompt construction"
        raise TypeError(message)

    monkeypatch.setattr(
        llm.PydanticOutputParser, "get_format_instructions", invalid_prompt
    )
    with pytest.raises(TypeError, match="invalid prompt construction"):
        llm.structured(
            settings,
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )
    assert prompt_calls == 1
    assert model_calls == 1


@pytest.mark.parametrize(
    "case",
    [
        (
            "",
            {
                "finish_reason": "length",
                "token_usage": {
                    "prompt_tokens": 1_328,
                    "completion_tokens": 4_096,
                    "total_tokens": 5_424,
                },
            },
            None,
            (1_328, 4_096, 5_424),
        ),
        (
            'SECRET-PARTIAL-RAW {"value":',
            {"finish_reason": "length", "raw": "SECRET-METADATA"},
            {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46},
            (12, 34, 46),
        ),
    ],
    ids=["response-metadata", "usage-metadata"],
)
def test_llm_classifies_length_before_parse_without_retry_or_leak(
    case: tuple[
        str,
        dict[str, object],
        dict[str, int] | None,
        tuple[int, int, int],
    ],
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """空または途中のlength応答をparseせず安全に一回で停止する。"""

    content, response_metadata, usage_metadata, expected = case
    calls = 0

    class Client:
        def invoke(self, _messages: object) -> AIMessage:
            nonlocal calls
            calls += 1
            return AIMessage(
                content=content,
                response_metadata=response_metadata,
                usage_metadata=usage_metadata,
            )

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())

    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings_factory(retry_attempts=4, retry_base_seconds=0),
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )

    assert calls == 1
    assert captured.value.stage == "text-output"
    assert captured.value.cause_type == "LLMOutputTruncatedError"
    assert captured.value.failure_kind == "output-truncated"
    assert captured.value.finish_reason == "length"
    assert (
        captured.value.input_tokens,
        captured.value.output_tokens,
        captured.value.total_tokens,
    ) == expected
    for forbidden in (content, "SECRET-METADATA"):
        if forbidden:
            assert forbidden not in str(captured.value)


def test_llm_token_usage_rejects_non_integer_or_negative_values(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """診断にはnon-negative integerだけを許可する。"""

    class Client:
        def invoke(self, _messages: object) -> AIMessage:
            return AIMessage(
                content="",
                response_metadata={
                    "finish_reason": "length",
                    "token_usage": {
                        "prompt_tokens": -1,
                        "completion_tokens": True,
                        "total_tokens": "5",
                    },
                },
            )

    monkeypatch.setattr(llm, "_model", lambda *_args: Client())

    with pytest.raises(llm.LLMError) as captured:
        llm.structured(
            settings_factory(),
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )

    assert captured.value.input_tokens is None
    assert captured.value.output_tokens is None
    assert captured.value.total_tokens is None
