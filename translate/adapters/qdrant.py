"""Qdrantへの決定的Point登録とRAG検索。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from translate.common.config import Config

logger = logging.getLogger(__name__)


class QdrantUnavailableError(RuntimeError):
    """必要なoptional dependencyが導入されていないことを表す。"""


def upsert_revision(
    *,
    config: Config,
    source_key: str,
    revision: str,
    points: list[dict[str, Any]],
    vector_size: int,
) -> bool:
    """新revisionを確認後に旧revisionへ置換し、既存なら書込みを省略する。

    Args:
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        source_key (str): 旧Revisionを識別するSource Key。
        revision (str): 登録内容の世代を識別するRevision Hash。
        points (list[dict[str, Any]]): Qdrantへ登録するVector Point列。
        vector_size (int): Qdrant CollectionのVector次元数。

    Returns:
        bool: 新revisionを確認後に旧revisionへ置換し、既存なら書込みを省略する。

    Raises:
        RuntimeError: `Qdrant registration verification failed`と判定した場合。
    """

    client, models = _client(config)
    collection = config.qdrant_collection or ""
    logger.info("Qdrant登録開始 collection=%s points=%d", collection, len(points))
    if not client.collection_exists(collection):
        logger.debug(
            "Qdrant collection作成 collection=%s dimensions=%d", collection, vector_size
        )
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(
                size=vector_size, distance=models.Distance.COSINE
            ),
        )
    else:
        _validate_collection(client, models, collection, vector_size)
    ids = [point["id"] for point in points]
    existing = client.retrieve(
        collection_name=collection,
        ids=ids,
        with_payload=False,
        with_vectors=False,
    )
    if {str(item.id) for item in existing} >= set(ids):
        logger.info("Qdrant登録省略 collection=%s points=%d", collection, len(points))
        return False
    logger.debug("Qdrant upload開始 points=%d", len(points))
    client.upload_points(
        collection_name=collection,
        points=[
            models.PointStruct(
                id=point["id"], vector=point["vector"], payload=point["payload"]
            )
            for point in points
        ],
        batch_size=64,
        wait=True,
    )
    verified = client.retrieve(
        collection_name=collection,
        ids=ids,
        with_payload=False,
        with_vectors=False,
    )
    if {str(item.id) for item in verified} < set(ids):
        logger.warning("Qdrant登録失敗 type=VerificationError points=%d", len(points))
        raise RuntimeError("Qdrant registration verification failed")
    logger.debug("Qdrant旧revision削除開始")
    client.delete(
        collection_name=collection,
        points_selector=models.Filter(
            must=[
                models.FieldCondition(
                    key="source_key", match=models.MatchValue(value=source_key)
                )
            ],
            must_not=[
                models.FieldCondition(
                    key="revision", match=models.MatchValue(value=revision)
                )
            ],
        ),
        wait=True,
    )
    logger.info("Qdrant登録完了 collection=%s points=%d", collection, len(points))
    return True


def search(config: Config, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
    """Qdrantからscore降順、同score時Point ID順で参照文脈を返す。

    Args:
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        vector (list[float]): 類似検索用のEmbedding Vector。
        limit (int): Qdrantから取得する最大件数。

    Returns:
        list[dict[str, Any]]: Qdrantからscore降順、同score時Point ID順で参照文脈を返す。
    """

    client, _models = _client(config)
    collection = config.qdrant_collection or ""
    logger.debug("Qdrant検索開始 collection=%s limit=%d", collection, limit)
    response = client.query_points(
        collection_name=collection,
        query=vector,
        limit=limit,
        with_payload=True,
    )
    values = [
        {"id": str(point.id), "score": float(point.score), **(point.payload or {})}
        for point in response.points
    ]
    logger.info("Qdrant検索完了 collection=%s results=%d", collection, len(values))
    return sorted(values, key=lambda item: (-float(item["score"]), str(item["id"])))


def _client(config: Config) -> tuple[Any, Any]:
    """optional qdrant-clientを遅延importし、検証済み設定でClientを作る。

    Args:
        config (Config): 接続先、上限値および処理Optionを保持する設定。

    Returns:
        tuple[Any, Any]: optional qdrant-clientを遅延importし、検証済み設定でClientを作る。

    Raises:
        QdrantUnavailableError: `qdrant-client is required for this operation`と判定した場合。
        ValueError: `Qdrant settings are required`と判定した場合。
    """

    try:
        from qdrant_client import QdrantClient, models  # noqa: PLC0415 - optional dependency
    except ImportError as error:
        raise QdrantUnavailableError(
            "qdrant-client is required for this operation"
        ) from error
    if config.qdrant_uri is None or config.qdrant_collection is None:
        raise ValueError("Qdrant settings are required")
    return (
        QdrantClient(
            url=config.qdrant_uri,
            api_key=config.qdrant_api_key,
            timeout=int(config.http_request_timeout_seconds),
        ),
        models,
    )


def _validate_collection(
    client: Any, models: Any, collection: str, vector_size: int
) -> None:
    """既存collectionのvector次元とCosine距離が現在設定と一致するか検査する。

    Args:
        client (Any): 外部処理を呼び出すClient。
        models (Any): QdrantのModel定義Module。
        collection (str): 検証対象のQdrant Collection名。
        vector_size (int): Qdrant CollectionのVector次元数。

    Raises:
        ValueError: `named Qdrant vectors are not supported`、`Qdrant collection vector
            configuration does not match`のいずれかと判定した場合。
    """

    info = client.get_collection(collection)
    vectors = info.config.params.vectors
    if isinstance(vectors, dict):
        raise ValueError("named Qdrant vectors are not supported")
    if vectors.size != vector_size or vectors.distance != models.Distance.COSINE:
        raise ValueError("Qdrant collection vector configuration does not match")
