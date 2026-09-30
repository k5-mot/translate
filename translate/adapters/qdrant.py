"""Qdrantへの決定的Point登録とRAG検索。"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from translate.common.config import Config


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
    """新revisionを確認後に旧revisionへ置換し、既存なら書込みを省略する。"""

    client, models = _client(config)
    collection = config.qdrant_collection or ""
    if not client.collection_exists(collection):
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
        return False
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
        raise RuntimeError("Qdrant registration verification failed")
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
    return True


def search(config: Config, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
    """Qdrantからscore降順、同score時Point ID順で参照文脈を返す。"""

    client, _models = _client(config)
    collection = config.qdrant_collection or ""
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
    return sorted(values, key=lambda item: (-float(item["score"]), str(item["id"])))


def _client(config: Config) -> tuple[Any, Any]:
    """optional qdrant-clientを遅延importし、検証済み設定でClientを作る。"""

    try:
        module = importlib.import_module("qdrant_client")
        models = importlib.import_module("qdrant_client.http.models")
    except ImportError as error:
        raise QdrantUnavailableError(
            "qdrant-client is required for this operation"
        ) from error
    if config.qdrant_uri is None or config.qdrant_collection is None:
        raise ValueError("Qdrant settings are required")
    return (
        module.QdrantClient(
            url=config.qdrant_uri,
            api_key=config.qdrant_api_key,
            timeout=int(config.http_request_timeout_seconds),
        ),
        models,
    )


def _validate_collection(
    client: Any, models: Any, collection: str, vector_size: int
) -> None:
    """既存collectionのvector次元とCosine距離が現在設定と一致するか検査する。"""

    info = client.get_collection(collection)
    vectors = info.config.params.vectors
    if isinstance(vectors, dict):
        raise ValueError("named Qdrant vectors are not supported")
    if vectors.size != vector_size or vectors.distance != models.Distance.COSINE:
        raise ValueError("Qdrant collection vector configuration does not match")
