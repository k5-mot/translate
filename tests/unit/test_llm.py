"""LLM adapter retry behavior tests."""

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import BaseModel

from translate.adapters.llm import (
    LLMClient,
    LLMInvalidResponseError,
    StructuredResult,
    _provider_error,
)
from translate.common.config import Config


class Response(BaseModel):
    """Minimal response model for structured output tests."""

    value: int


def _response(content: str) -> SimpleNamespace:
    """Build the SDK response shape read by LLMClient."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop"
            )
        ],
        usage=None,
    )


def _client() -> LLMClient:
    """Create a client configured for two quick test attempts."""
    return LLMClient(
        Config(
            openai_base_url="http://localhost/v1",
            llm_retry_attempts=2,
            llm_task_deadline_seconds=60,
        )
    )


def _call(
    client: LLMClient, validate: Callable[[Response], None] | None = None
) -> StructuredResult[Response]:
    """Send the minimal structured request used by the retry tests."""
    return client.structured(
        task="REVIEW",
        model="test",
        response_type=Response,
        system="system",
        user="user",
        contract="contract",
        native_schema={"type": "object"},
        output_tokens=100,
        validate=validate,
    )


def test_structured_retries_invalid_schema_response() -> None:
    """Pydantic検証に失敗した応答を直して再試行する。"""
    client = _client()
    client.client.chat.completions.create = Mock(
        side_effect=[_response('{"value": "bad"}'), _response('{"value": 1}')]
    )

    result = _call(client)

    assert result.response == Response(value=1)
    retry_payload = client.client.chat.completions.create.call_args_list[1].kwargs
    assert (
        "Previous response validation failed" in retry_payload["messages"][1]["content"]
    )


def test_structured_retries_callback_validation_error() -> None:
    """操作固有の検証コールバック失敗も再試行する。"""
    client = _client()
    client.client.chat.completions.create = Mock(
        side_effect=[_response('{"value": 1}'), _response('{"value": 1}')]
    )
    validations = 0

    def validate(response: Response) -> None:
        """Reject the first answer to verify callback errors use the retry path."""
        nonlocal validations
        assert response.value == 1
        validations += 1
        if validations == 1:
            message = "selected IDs are not covered"
            raise ValueError(message)

    result = _call(client, validate)

    assert result.response == Response(value=1)
    retry_payload = client.client.chat.completions.create.call_args_list[1].kwargs
    assert "selected IDs are not covered" in retry_payload["messages"][1]["content"]


def test_structured_rejects_invalid_schema_after_retries() -> None:
    """契約違反応答が上限回数続く場合に失敗する。"""
    client = _client()
    client.client.chat.completions.create = Mock(
        return_value=_response('{"value": "bad"}')
    )

    with pytest.raises(LLMInvalidResponseError, match="JSON形式または契約"):
        _call(client)


def test_provider_error_exposes_only_safe_http_diagnostics() -> None:
    """400診断に構造化出力原因を示し、provider messageは記録しない。"""
    error = _provider_error(
        SimpleNamespace(
            status_code=400,
            code="invalid_schema",
            param="response_format",
            response=SimpleNamespace(headers={"x-request-id": "req-123"}),
            body={
                "error": {
                    "type": "invalid_request_error",
                    "message": (
                        "Unsupported json_schema for response_format: source text"
                    ),
                }
            },
        )
    )

    assert "code=invalid_schema" in str(error)
    assert "param=response_format" in str(error)
    assert "type=invalid_request_error" in str(error)
    assert "request_id=req-123" in str(error)
    assert "category=structured_output" in str(error)
    assert "source text" not in str(error)


def test_fits_input_uses_counter_only_above_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """byte数が予算内なら問い合わせず、超過時はtoken counterの値で判定する。"""
    calls: list[str] = []

    def post(url: str, **_kwargs: object) -> httpx.Response:
        """固定のtoken数を返す。"""
        calls.append(url)
        return httpx.Response(
            200, json={"total_tokens": 500}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr("translate.adapters.llm.httpx.post", post)
    client = LLMClient(Config(_env_file=None, openai_base_url="http://litellm/v1"))
    assert client.fits_input("model", "short", 1000)
    assert not calls
    assert client.fits_input("model", "x" * 5000, 1000)
    assert calls == ["http://litellm/utils/token_counter"]
    assert not client.fits_input("model", "x" * 5000, 400)


def test_fits_input_falls_back_to_bytes_once_without_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未対応のendpointではbyte換算で判定し、再度問い合わせない。"""
    calls: list[str] = []

    def post(url: str, **_kwargs: object) -> httpx.Response:
        """LM Studio同様にHTTP 200の別形式で応答する。"""
        calls.append(url)
        return httpx.Response(
            200, json={"error": "Unexpected"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr("translate.adapters.llm.httpx.post", post)
    client = LLMClient(Config(_env_file=None, openai_base_url="http://llm/v1"))
    assert client.fits_input("model", "x" * 1500, 1000)
    assert not client.fits_input("model", "x" * 2500, 1000)
    assert len(calls) == 1
