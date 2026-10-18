"""LLM adapter retry behavior tests."""

from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from translate.adapters.llm import LLMClient, LLMInvalidResponseError
from translate.common.config import Config


class ChatMessage:
    """SDK message shape consumed by the adapter."""

    content: str

    def __init__(self, content: str) -> None:
        self.content = content


class ChatChoice:
    """SDK choice shape consumed by the adapter."""

    message: ChatMessage
    finish_reason: str

    def __init__(self, content: str) -> None:
        self.message = ChatMessage(content)
        self.finish_reason = "stop"


class ChatResponse:
    """SDK response shape consumed by the adapter."""

    choices: list[ChatChoice]
    usage: None = None

    def __init__(self, content: str) -> None:
        self.choices = [ChatChoice(content)]


class Response(BaseModel):
    """Minimal response model for structured output tests."""

    value: int


def test_structured_retries_invalid_contract_with_feedback() -> None:
    """無効な契約応答の内容を使い、再試行を成功させる。"""
    client = LLMClient(
        Config(
            openai_base_url="http://localhost/v1",
            llm_retry_attempts=2,
            llm_task_deadline_seconds=60,
        )
    )
    client.client.chat.completions.create = Mock(
        side_effect=[
            ChatResponse('{"value": "bad"}'),
            ChatResponse('{"value": 1}'),
        ]
    )

    result = client.structured(
        task="REVIEW",
        model="test",
        response_type=Response,
        system="system",
        user="user",
        contract="contract",
        native_schema={"type": "object"},
        output_tokens=100,
    )

    assert result.response == Response(value=1)
    retry_payload = client.client.chat.completions.create.call_args_list[1].kwargs
    assert (
        "Previous response validation failed" in retry_payload["messages"][1]["content"]
    )


def test_structured_rejects_invalid_contract_after_retries() -> None:
    """契約違反応答が上限回数続く場合に失敗する。"""
    client = LLMClient(
        Config(
            openai_base_url="http://localhost/v1",
            llm_retry_attempts=2,
            llm_task_deadline_seconds=60,
        )
    )
    client.client.chat.completions.create = Mock(
        return_value=ChatResponse('{"value": "bad"}')
    )

    with pytest.raises(LLMInvalidResponseError, match="JSON形式または契約"):
        client.structured(
            task="REVIEW",
            model="test",
            response_type=Response,
            system="system",
            user="user",
            contract="contract",
            native_schema={"type": "object"},
            output_tokens=100,
        )
