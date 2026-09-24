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
    return [
        {"id": f"block-{index}", "source": "S" * size, "translation": "T" * size}
        for index in range(count)
    ]


def _document(pairs: list[dict[str, str]]) -> Document:
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
    return Finding(kind="translation", target_ids=[target], message=f"finding-{target}")


def _truncated() -> LLMError:
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
    calls: list[list[str]] = []

    def fake_search(*_args: object, **_kwargs: object) -> list[object]:
        return []

    def fake_structured(*args: object, **_kwargs: object) -> review.ReviewResponse:
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
    calls: list[list[str]] = []
    fail_second = True

    monkeypatch.setattr(review, "search", lambda *_args, **_kwargs: [])

    def fake_structured(*args: object, **_kwargs: object) -> review.ReviewResponse:
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
