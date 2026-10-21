"""Qdrantへの決定的Point登録とRAG検索。"""

import logging
from typing import Any, Self

from translate.common.config import Config

logger = logging.getLogger(__name__)


class QdrantUnavailableError(RuntimeError):
    """必要なoptional dependencyが導入されていないことを表す。"""


class QdrantStore:
    """一つのcollectionへの接続と登録・検索を管理する。"""

    def __init__(self, config: Config) -> None:
        """設定を検証して、背景通信のない同期clientを生成する。

        Args:
            config: Qdrantの接続先、collectionおよびtimeout。

        Raises:
            QdrantUnavailableError: optional dependencyがない場合。
            ValueError: 接続先またはcollectionが未設定の場合。
        """
        try:
            from qdrant_client import QdrantClient, models  # noqa: PLC0415 - optional dependency
        except ImportError as error:
            raise QdrantUnavailableError(
                "qdrant-client is required for this operation"
            ) from error
        if config.qdrant_uri is None or config.qdrant_collection is None:
            raise ValueError("Qdrant settings are required")
        self.collection = config.qdrant_collection
        self.models = models
        self.client = QdrantClient(
            url=config.qdrant_uri,
            api_key=config.qdrant_api_key,
            timeout=int(config.http_request_timeout_seconds),
            check_compatibility=False,  # 背景threadのversion確認を同期要求と重ねない。
        )

    def __enter__(self) -> Self:
        """接続を使う処理へ自身を渡す。

        Returns:
            QdrantStore: この接続。
        """
        return self

    def __exit__(self, *_error: object) -> None:
        """正常終了と例外の双方で接続を閉じる。

        Args:
            *_error: context内の例外情報。
        """
        self.client.close()

    def upsert_revision(
        self,
        *,
        source_key: str,
        revision: str,
        points: list[dict[str, Any]],
        vector_size: int,
    ) -> bool:
        """新revisionを確認後に旧revisionへ置換し、既存なら書込みを省略する。

        Args:
            source_key (str): 旧Revisionを識別するSource Key。
            revision (str): 登録内容の世代を識別するRevision Hash。
            points (list[dict[str, Any]]): Qdrantへ登録するVector Point列。
            vector_size (int): Qdrant CollectionのVector次元数。

        Returns:
            bool: 新revisionを確認後に旧revisionへ置換し、既存なら書込みを省略する。

        Raises:
            RuntimeError: `Qdrant registration verification failed`と判定した場合。
        """

        client, models = self.client, self.models
        collection = self.collection
        logger.info("Qdrant登録開始 collection=%s points=%d", collection, len(points))
        if not client.collection_exists(collection):
            logger.debug(
                "Qdrant collection作成 collection=%s dimensions=%d",
                collection,
                vector_size,
            )
            client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
            )
        else:
            self._validate_collection(vector_size)
        ids = [point["id"] for point in points]
        existing = client.retrieve(
            collection_name=collection,
            ids=ids,
            with_payload=False,
            with_vectors=False,
        )
        if {str(item.id) for item in existing} >= set(ids):
            logger.info(
                "Qdrant登録省略 collection=%s points=%d", collection, len(points)
            )
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
            parallel=1,
            wait=True,
        )
        verified = client.retrieve(
            collection_name=collection,
            ids=ids,
            with_payload=False,
            with_vectors=False,
        )
        if {str(item.id) for item in verified} < set(ids):
            logger.warning(
                "Qdrant登録失敗 type=VerificationError points=%d", len(points)
            )
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

    def search(self, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        """Qdrantからscore降順、同score時Point ID順で参照文脈を返す。

        Args:
            vector (list[float]): 類似検索用のEmbedding Vector。
            limit (int): Qdrantから取得する最大件数。

        Returns:
            list[dict[str, Any]]: Qdrantからscore降順、同score時Point ID順で参照文脈を返す。
        """

        client = self.client
        collection = self.collection
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

    def _validate_collection(self, vector_size: int) -> None:
        """既存collectionのvector次元とCosine距離が現在設定と一致するか検査する。

        Args:
            vector_size (int): Qdrant CollectionのVector次元数。

        Raises:
            ValueError: `named Qdrant vectors are not supported`、`Qdrant collection vector
                configuration does not match`のいずれかと判定した場合。
        """

        info = self.client.get_collection(self.collection)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            raise ValueError("named Qdrant vectors are not supported")
        if (
            vectors is None
            or vectors.size != vector_size
            or vectors.distance != self.models.Distance.COSINE
        ):
            raise ValueError("Qdrant collection vector configuration does not match")
