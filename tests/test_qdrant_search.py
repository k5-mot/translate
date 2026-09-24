"""Qdrant検索のretry、失敗伝播および再現Artifactを検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from langchain_core.documents import Document

from translate.adapters import qdrant

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def test_search_retries_and_records_reproducible_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """一時障害後の結果をquery、Collection、日時、引用元と共に保存する。"""

    calls = 0

    class Store:
        def similarity_search_with_score(
            self, query: str, *, k: int
        ) -> list[tuple[Document, float]]:
            """
            queryと取得件数を検査し、二回の障害後に引用元付き検索結果を返して再試行と保
            存を検証する。
            """

            nonlocal calls
            calls += 1
            assert query == "needle"
            assert k == 5
            if calls < 3:
                message = "temporary Qdrant failure"
                raise OSError(message)
            return [
                (
                    Document(
                        page_content="evidence",
                        metadata={"source": "reference.md", "chunk": 2},
                    ),
                    0.91,
                )
            ]

    monkeypatch.setattr(qdrant, "_store", lambda _settings: Store())
    monkeypatch.setattr(qdrant.time, "sleep", lambda _value: None)
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_attempts=3,
        retry_base_seconds=0,
    )
    artifact = tmp_path / "qdrant" / "search.json"

    result = qdrant.search(settings, "needle", artifact_path=artifact)

    assert calls == 3
    assert result == [
        {
            "text": "evidence",
            "source": "reference.md",
            "chunk": 2,
            "score": 0.91,
        }
    ]
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    assert saved["query"] == "needle"
    assert saved["collection"] == "references"
    assert saved["searched_at"].endswith("+00:00")
    assert saved["citations"] == ["reference.md"]
    assert saved["results"] == result


def test_search_exhaustion_propagates_and_does_not_publish_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """retry上限後は空結果へ変換せず、Task停止用の例外を伝播する。"""

    calls = 0

    class Store:
        def similarity_search_with_score(
            self, *_args: object, **_kwargs: object
        ) -> object:
            """
            毎回検索障害を返して回数を数え、上限停止時に空結果やArtifactを公開しないか調
            べる。
            """

            nonlocal calls
            calls += 1
            message = "persistent Qdrant failure"
            raise OSError(message)

    monkeypatch.setattr(qdrant, "_store", lambda _settings: Store())
    monkeypatch.setattr(qdrant.time, "sleep", lambda _value: None)
    settings = settings_factory(
        qdrant_url="https://qdrant.invalid",
        qdrant_collection="references",
        embedding_model="embedding",
        retry_attempts=3,
        retry_base_seconds=0,
    )
    artifact = tmp_path / "search.json"

    with pytest.raises(OSError, match="persistent"):
        qdrant.search(settings, "needle", artifact_path=artifact)

    assert calls == 3
    assert not artifact.exists()
