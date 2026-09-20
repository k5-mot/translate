"""外部Adapterの有限retryと恒久Error分類を検証する。"""

from __future__ import annotations

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
    with pytest.raises(httpx.ConnectError):
        llm.structured(
            settings,
            "model",
            RetryResponse,
            "system",
            "user",
            reasoning="low",
        )
    assert calls == 3
