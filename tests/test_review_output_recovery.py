from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from translate.adapters.llm import LLMError, LLMOutputTruncatedError
from translate.document import Block, Document, Finding, Inline, Page
from translate.tasks import review

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings


def _pairs(count: int, size: int = 2_500) -> list[dict[str, str]]:
    """
    原文・訳文の文字数と件数を固定した比較対を作り、Reviewの入力予算と分割条件を制御する
    。
    """

    return [
        {"id": f"block-{index}", "source": "S" * size, "translation": "T" * size}
        for index in range(count)
    ]


def _document(pairs: list[dict[str, str]]) -> Document:
    """比較対をページ2の原訳文付きBlockへ変換し、Review Taskに渡す文書fixtureを作る。"""

    return Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id=item["id"],
                        order=index,
                        kind="paragraph",
                        source=[Inline(id=f"{item['id']}-source", text=item["source"])],
                        translated=[
                            Inline(id=f"{item['id']}-target", text=item["translation"])
                        ],
                    )
                    for index, item in enumerate(pairs)
                ],
            )
        ]
    )


def _finding(target: str) -> Finding:
    """対象Blockを識別できる固定指摘を作り、分割後の結果集約を検証する。"""

    return Finding(kind="translation", target_ids=[target], message=f"finding-{target}")


def _truncated() -> LLMError:
    """出力切断理由と固定usageを持つLLM障害を作り、Reviewの回復経路へ注入する。"""

    return LLMError(
        "text-output",
        LLMOutputTruncatedError(),
        failure_kind="output-truncated",
        finish_reason="length",
        input_tokens=100,
        output_tokens=16_384,
        total_tokens=16_484,
    )


def test_review_chunks_are_deterministic_and_budget_bounded() -> None:
    """
    小さい入力予算で比較対の順序を保って分割し、安定したChunk IDになることを検査する。
    """

    pairs = _pairs(3, size=2_500)
    chunks = review._review_chunks(pairs, available_input_tokens=1_024)  # noqa: SLF001

    assert [item["id"] for chunk in chunks for item in chunk] == [
        "block-0",
        "block-1",
        "block-2",
    ]
    assert len(chunks) == 3
    assert review._chunk_id(2, "0001") == "page-0002-review-0001"  # noqa: SLF001


def test_review_truncation_retries_then_splits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """切断時に同じChunkを有限再送してから二分し、各対象の指摘を集約するか検証する。"""

    calls: list[list[str]] = []

    def fake_search(*_args: object, **_kwargs: object) -> list[object]:
        """参照検索結果を空に固定し、Reviewの出力切断回復だけを試験対象にする。"""

        return []

    def fake_structured(*args: object, **_kwargs: object) -> review.ReviewResponse:
        """複数対の要求だけ出力切断にし、再送と二分後の単独要求を履歴へ記録する。"""

        prompt = json.loads(str(args[4]))
        ids = [item["id"] for item in prompt["pairs"]]
        calls.append(ids)
        if len(ids) > 1:
            raise _truncated()
        return review.ReviewResponse(findings=[_finding(ids[0])])

    monkeypatch.setattr(review, "search", fake_search)
    monkeypatch.setattr(review, "structured", fake_structured)
    settings: Settings = __import__(
        "translate.common.settings", fromlist=["Settings"]
    ).Settings(templates_dir=tmp_path, retry_attempts=2, retry_base_seconds=0)

    result = review.run(
        _document(_pairs(2, size=2_500)), {}, "rules", [], settings, tmp_path / "review"
    )

    assert [item.target_ids for item in result[2]] == [["block-0"], ["block-1"]]
    assert calls == [
        ["block-0", "block-1"],
        ["block-0", "block-1"],
        ["block-0"],
        ["block-1"],
    ]


def test_review_cache_reuses_completed_chunk_without_public_partial_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    既存Chunk Cacheが成功済み要求を再送せず、Task全体成功時だけ結果を公開する動作を検証
    する。
    """

    calls: list[list[str]] = []
    fail_second = True

    monkeypatch.setattr(review, "search", lambda *_args, **_kwargs: [])

    def fake_structured(*args: object, **_kwargs: object) -> review.ReviewResponse:
        """
        二番目のChunkだけ初回に失敗し、同じTask再実行時の成功済みChunkの再利用を記録する
        。
        """

        nonlocal fail_second
        prompt = json.loads(str(args[4]))
        ids = [item["id"] for item in prompt["pairs"]]
        calls.append(ids)
        if ids == ["block-1"] and fail_second:
            fail_second = False
            error_stage = "text-parse"
            raise LLMError(error_stage, RuntimeError("temporary"))
        return review.ReviewResponse(findings=[_finding(ids[0])])

    monkeypatch.setattr(review, "structured", fake_structured)
    settings: Settings = __import__(
        "translate.common.settings", fromlist=["Settings"]
    ).Settings(
        templates_dir=tmp_path,
        retry_attempts=1,
        context_tokens=4_096,
        output_tokens=1_024,
        image_tokens=1_024,
    )
    output = tmp_path / "review"
    with pytest.raises(LLMError):
        review.run(_document(_pairs(2, size=2_500)), {}, "rules", [], settings, output)
    assert not output.exists()
    assert (tmp_path / ".review.chunks").exists()

    result = review.run(
        _document(_pairs(2, size=2_500)), {}, "rules", [], settings, output
    )

    assert [item.target_ids for item in result[2]] == [["block-0"], ["block-1"]]
    assert calls == [["block-0"], ["block-1"], ["block-1"]]
    assert output.joinpath("page-0002.json").exists()
    assert not (tmp_path / ".review.chunks").exists()
