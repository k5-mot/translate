"""OpenAI互換Embedding endpointへの有限batch接続。"""

from __future__ import annotations

import logging
import math
import random
import time
from typing import TYPE_CHECKING

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    Omit,
    OpenAI,
)

if TYPE_CHECKING:
    from translate.common.config import Config

logger = logging.getLogger(__name__)


class EmbeddingError(ValueError):
    """Embedding endpointの通信・HTTP失敗を表す。"""


def embed(values: list[str], config: Config) -> list[list[float]]:
    """最大16件ずつEmbeddingし、件数、次元および有限値を検証する。

    Args:
        values (list[str]): 一括処理する入力Text列。
        config (Config): 接続先、上限値および処理Optionを保持する設定。

    Returns:
        list[list[float]]: 最大16件ずつEmbeddingし、件数、次元および有限値を検証する。

    Raises:
        ValueError: endpointまたはmodelの設定がない場合。
        EmbeddingError: 応答の件数、数値または次元が不正な場合。
    """

    if config.openai_base_url is None or config.openai_embedding_model is None:
        raise ValueError("embedding endpoint and model are required")
    vectors: list[list[float]] = []
    dimension: int | None = None
    logger.info(
        "Embedding開始 model=%s items=%d", config.openai_embedding_model, len(values)
    )
    with OpenAI(
        api_key=config.openai_api_key or "local-no-auth",
        base_url=config.openai_base_url,
        timeout=config.http_request_timeout_seconds,
        max_retries=0,
    ) as client:
        for first in range(0, len(values), 16):
            batch = values[first : first + 16]
            logger.debug("Embedding batch開始 offset=%d items=%d", first, len(batch))
            received = _request(batch, config, client, config.openai_embedding_model)
            if len(received) != len(batch):
                raise EmbeddingError(
                    "Embedding応答の件数が入力と一致しません。対策: "
                    "endpointのEmbedding応答形式を確認してください。"
                )
            for vector in received:
                if not vector or not all(math.isfinite(value) for value in vector):
                    raise EmbeddingError(
                        "Embedding vectorに有限でない値があります。対策: "
                        "endpointのmodel出力を確認してください。"
                    )
                if dimension is None:
                    dimension = len(vector)
                elif len(vector) != dimension:
                    raise EmbeddingError(
                        "Embedding vectorの次元が変化しました。対策: "
                        "OPENAI_EMBEDDING_MODELとendpointの設定を確認してください。"
                    )
                vectors.append(vector)
    logger.info("Embedding完了 items=%d dimensions=%s", len(vectors), dimension)
    return vectors


def _request(
    values: list[str], config: Config, client: OpenAI, model: str
) -> list[list[float]]:
    """一batchを仕様で許可されたHTTP失敗だけ再試行する。

    Args:
        values (list[str]): 一括処理する入力Text列。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        client (OpenAI): Embedding要求に使用するOpenAI Python client。
        model (str): Embedding APIへ指定するModel名。

    Returns:
        list[list[float]]: 一batchを仕様で許可されたHTTP失敗だけ再試行する。

    Raises:
        EmbeddingError: 通信、HTTP応答またはEmbedding応答の検証に失敗した場合。
    """

    deadline = time.monotonic() + config.external_task_deadline_seconds
    for attempt in range(1, config.http_retry_attempts + 1):
        logger.debug("Embedding要求 attempt=%d items=%d", attempt, len(values))
        try:
            response = client.embeddings.create(
                model=model,
                input=values,
                encoding_format="float",
                extra_headers={"Authorization": Omit()}
                if not config.openai_api_key
                else None,
            )
            break
        except (APIConnectionError, APIStatusError) as error:
            status = error.status_code if isinstance(error, APIStatusError) else None
            retryable = status is None or status in {408, 429} or status >= 500
            if not retryable or attempt >= config.http_retry_attempts:
                logger.warning("Embedding失敗 attempt=%d status=%s", attempt, status)
                if isinstance(error, APITimeoutError) or status == 408:
                    message = (
                        "Embedding要求が時間切れです。対策: "
                        "HTTP_REQUEST_TIMEOUT_SECONDSとendpointの負荷を確認してください。"
                    )
                elif status in {401, 403}:
                    message = (
                        f"Embedding認証・権限エラー (HTTP {status})。対策: "
                        "OPENAI_API_KEYを確認してください。"
                    )
                elif status == 429:
                    message = (
                        "Embeddingのrate limitに達しました。対策: "
                        "同時実行数とendpointの制限を確認してください。"
                    )
                elif status is None:
                    message = (
                        "Embedding endpointへ接続できません。対策: "
                        "OPENAI_BASE_URLとネットワークを確認してください。"
                    )
                else:
                    message = (
                        f"Embedding endpointがHTTP {status}を返しました。対策: "
                        "model名とendpointのサーバーログを確認してください。"
                    )
                raise EmbeddingError(message) from error
            delay = min(2 ** (attempt - 1), max(0.0, deadline - time.monotonic()))
            logger.warning("Embedding再試行 attempt=%d status=%s", attempt, status)
            if delay <= 0:
                raise EmbeddingError(
                    "Embedding処理の期限に達しました。対策: "
                    "EXTERNAL_TASK_DEADLINE_SECONDSとendpointの負荷を確認してください。"
                ) from error
            time.sleep(random.uniform(0, delay))  # noqa: S311
        except APIResponseValidationError as error:
            logger.warning("Embedding失敗 type=APIResponseValidationError")
            raise EmbeddingError(
                "Embedding応答の形式が不正です。対策: "
                "endpointの応答形式とサーバーログを確認してください。"
            ) from error
    data = getattr(response, "data", None)
    if not isinstance(data, list) or any(
        not isinstance(getattr(item, "index", None), int) for item in data
    ):
        raise EmbeddingError(
            "Embedding応答のdataまたはindexが不正です。対策: "
            "endpointのEmbedding応答形式を確認してください。"
        )
    ordered = sorted(data, key=lambda item: item.index)
    vectors: list[list[float]] = []
    for item in ordered:
        raw = getattr(item, "embedding", None)
        if not isinstance(raw, list) or not all(
            isinstance(value, int | float) for value in raw
        ):
            raise EmbeddingError(
                "Embedding vectorの形式が不正です。対策: "
                "endpointのEmbedding応答形式を確認してください。"
            )
        vectors.append([float(value) for value in raw])
    return vectors
