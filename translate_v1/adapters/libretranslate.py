"""LibreTranslate HTTP adapter。"""

from __future__ import annotations

import random
import time

import httpx


def translate_texts(
    url: str,
    api_key: str | None,
    texts: list[str],
    *,
    retry_attempts: int = 3,
    retry_base_seconds: float = 1.0,
    retry_max_seconds: float = 30.0,
    timeout_seconds: float = 300.0,
    deadline_seconds: float = 21_600.0,
) -> list[str]:
    """英語text列を日本語へ翻訳する。"""

    if not texts:
        return []
    payload: dict[str, object] = {
        "q": texts,
        "source": "en",
        "target": "ja",
        "format": "text",
    }
    if api_key:
        payload["api_key"] = api_key
    deadline = time.monotonic() + deadline_seconds
    response: httpx.Response | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = httpx.post(
                url.rstrip("/") + "/translate",
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            status = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else None
            )
            retryable = (
                status in {408, 429}
                or (status is not None and status >= 500)
                or status is None
            )
            if (
                not retryable
                or attempt >= retry_attempts
                or time.monotonic() >= deadline
            ):
                raise
            delay = min(retry_base_seconds * (2 ** (attempt - 1)), retry_max_seconds)
            time.sleep(
                random.uniform(  # noqa: S311
                    0, min(delay, max(0.0, deadline - time.monotonic()))
                )
            )
    if response is None:
        msg = "LibreTranslate request produced no response"
        raise RuntimeError(msg)
    value = response.json()
    translated = value.get("translatedText")
    if isinstance(translated, str):
        translated = [translated]
    if not isinstance(translated, list) or not all(
        isinstance(item, str) for item in translated
    ):
        msg = "LibreTranslate returned an invalid response"
        raise RuntimeError(msg)
    return translated
