"""Docling接続断の間もサーバー側jobを手放さないことを検証する。"""

from pathlib import Path

import httpx
import pytest

from translate.adapters import docling
from translate.adapters.docling import DoclingClient
from translate.common.config import Config


def _client() -> DoclingClient:
    """再試行を1回に絞ったDocling接続を作る。"""
    return DoclingClient(
        Config(
            _env_file=None, docling_server_url="http://docling", http_retry_attempts=1
        )
    )


def test_convert_waits_through_poll_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pollの接続断が続いても、回復後の成功結果を受け取る。"""
    source = tmp_path / "part.pdf"
    source.write_bytes(b"%PDF")
    answers: list[object] = [
        httpx.Response(200, json={"task_id": "job"}),
        httpx.ConnectError("down"),
        httpx.Response(503),
        httpx.Response(200, json={"task_status": "success"}),
        httpx.Response(200, content=b"zip"),
    ]

    def request(method: str, url: str, **_kwargs: object) -> httpx.Response:
        """用意した応答を順に返す。"""
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        answer.request = httpx.Request(method, url)
        return answer

    monkeypatch.setattr(docling.httpx, "request", request)
    monkeypatch.setattr(docling.time, "sleep", lambda _: None)
    assert _client().convert(source) == (b"zip", "job", 1)


def test_convert_stops_after_outage_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """待機上限を超えた接続断は呼び出し元へ伝える。"""
    source = tmp_path / "part.pdf"
    source.write_bytes(b"%PDF")

    def request(_method: str, _url: str, **_kwargs: object) -> httpx.Response:
        """常に接続に失敗する。"""
        message = "down"
        raise httpx.ConnectError(message)

    monkeypatch.setattr(docling.httpx, "request", request)
    monkeypatch.setattr(docling, "OUTAGE_TOLERANCE_SECONDS", 0.0)
    with pytest.raises(httpx.ConnectError):
        _client().convert(source)
