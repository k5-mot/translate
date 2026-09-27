"""OpenAI互換Embedding endpointへの有限batch接続。"""

from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from translate.common.config import Config


def embed(values: list[str], config: Config) -> list[list[float]]:
    """最大16件ずつEmbeddingし、件数、次元および有限値を検証する。"""

    if config.openai_base_url is None or config.openai_embedding_model is None:
        raise ValueError("embedding endpoint and model are required")
    base_url = config.openai_base_url
    vectors: list[list[float]] = []
    dimension: int | None = None
    for first in range(0, len(values), 16):
        batch = values[first : first + 16]
        received = _request(batch, config, base_url)
        if len(received) != len(batch):
            raise ValueError("embedding response count does not match input")
        for vector in received:
            if not vector or not all(math.isfinite(value) for value in vector):
                raise ValueError("embedding vector must contain finite values")
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise ValueError("embedding vector dimension changed")
            vectors.append(vector)
    return vectors


def _request(values: list[str], config: Config, base_url: str) -> list[list[float]]:
    """一batchを仕様で許可されたHTTP失敗だけ再試行する。"""

    headers = {"Content-Type": "application/json"}
    if config.openai_api_key:
        headers["Authorization"] = f"Bearer {config.openai_api_key}"
    url = f"{base_url.rstrip('/')}/embeddings"
    deadline = time.monotonic() + config.external_task_deadline_seconds
    response: httpx.Response | None = None
    for attempt in range(1, config.http_retry_attempts + 1):
        try:
            response = httpx.post(
                url,
                headers=headers,
                json={"model": config.openai_embedding_model, "input": values},
                timeout=config.http_request_timeout_seconds,
            )
            response.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            status = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else None
            )
            retryable = status is None or status in {408, 429} or status >= 500
            if not retryable or attempt >= config.http_retry_attempts:
                raise
            delay = min(2 ** (attempt - 1), max(0.0, deadline - time.monotonic()))
            if delay <= 0:
                raise TimeoutError("embedding deadline exceeded") from error
            time.sleep(random.uniform(0, delay))  # noqa: S311
    if response is None:
        raise RuntimeError("embedding endpoint returned no response")
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("embedding response data must be an array")
    ordered = sorted(
        data, key=lambda item: item.get("index", -1) if isinstance(item, dict) else -1
    )
    vectors: list[list[float]] = []
    for item in ordered:
        raw = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(raw, list) or not all(
            isinstance(value, int | float) for value in raw
        ):
            raise ValueError("embedding response vector is invalid")
        vectors.append([float(value) for value in raw])
    return vectors
