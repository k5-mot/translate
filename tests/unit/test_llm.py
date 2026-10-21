"""LLM adapter retry behavior tests."""

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from translate.adapters.llm import (
    LLMClient,
    LLMInvalidResponseError,
    StructuredResult,
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
