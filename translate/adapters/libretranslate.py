"""LibreTranslateの英語から日本語へのbatch翻訳interface。"""

from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from translate.common.config import Config

logger = logging.getLogger(__name__)


def translate_texts(values: list[str], config: Config) -> list[str]:
    """文字列配列を一括送信し、同じ件数の日本語訳を返す。

    Args:
        values (list[str]): 一括処理する入力Text列。
        config (Config): 接続先、上限値および処理Optionを保持する設定。

    Returns:
        list[str]: 文字列配列を一括送信し、同じ件数の日本語訳を返す。

    Raises:
        ValueError: `LibreTranslate URL is required`、`LibreTranslate response is
            invalid`、`LibreTranslate response count does not match input`のいずれかと判定した場合。
        TimeoutError: `LibreTranslate task deadline exceeded`と判定した場合。
        RuntimeError: `LibreTranslate returned no response`と判定した場合。
    """

    if config.libretranslate_url is None:
        raise ValueError("LibreTranslate URL is required")
    payload: dict[str, object] = {
        "q": values,
        "source": "en",
        "target": "ja",
        "format": "text",
    }
    if config.libretranslate_api_key:
        payload["api_key"] = config.libretranslate_api_key
    deadline = time.monotonic() + config.external_task_deadline_seconds
    response: httpx.Response | None = None
    logger.info("LibreTranslate開始 items=%d", len(values))
    for attempt in range(1, config.http_retry_attempts + 1):
        logger.debug("LibreTranslate要求 attempt=%d", attempt)
        try:
            response = httpx.post(
                f"{config.libretranslate_url.rstrip('/')}/translate",
                json=payload,
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
                logger.warning(
                    "LibreTranslate失敗 attempt=%d status=%s", attempt, status
                )
                raise
            delay = min(2 ** (attempt - 1), max(0.0, deadline - time.monotonic()))
            logger.warning("LibreTranslate再試行 attempt=%d status=%s", attempt, status)
            if delay <= 0:
                raise TimeoutError("LibreTranslate task deadline exceeded") from error
            time.sleep(random.uniform(0, delay))  # noqa: S311
    if response is None:
        raise RuntimeError("LibreTranslate returned no response")
    body = response.json()
    translated = body.get("translatedText") if isinstance(body, dict) else None
    if isinstance(translated, str):
        translated = [translated]
    if not isinstance(translated, list) or not all(
        isinstance(item, str) for item in translated
    ):
        raise ValueError("LibreTranslate response is invalid")
    if len(translated) != len(values):
        raise ValueError("LibreTranslate response count does not match input")
    logger.info("LibreTranslate完了 items=%d", len(translated))
    return translated
