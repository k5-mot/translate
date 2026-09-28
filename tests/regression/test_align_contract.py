"""ALIGNの1対1、多対多および未対応分類fixture。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from translate_v1.document import AlignmentGroup, Block, Document, Inline, Page
from translate_v1.tasks import align

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate_v1.common.settings import Settings


def _document(prefix: str, texts: list[str]) -> Document:
    """原文・訳文のIDをprefixで区別した一ページ文書を作り、対応付け対象を固定する。"""

    return Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id=f"{prefix}/{index}",
                        order=index,
                        kind="paragraph",
                        source=[Inline(id=f"{prefix}/{index}/text", text=text)],
                    )
                    for index, text in enumerate(texts)
                ],
            )
        ]
    )


def _assert_partition(
    groups: list[AlignmentGroup], source: Document, target: Document
) -> None:
    """
    対応Groupが両文書の全Blockを過不足なく含み、同じ側のIDを重複使用しないことを確認する
    。
    """

    source_ids = [item for group in groups for item in group.source_ids]
    target_ids = [item for group in groups for item in group.target_ids]
    expected_source = [block.id for page in source.pages for block in page.blocks]
    expected_target = [block.id for page in target.pages for block in page.blocks]
    assert sorted(source_ids) == sorted(expected_source)
    assert sorted(target_ids) == sorted(expected_target)
    assert len(source_ids) == len(set(source_ids))
    assert len(target_ids) == len(set(target_ids))


def test_one_to_one_and_unmatched_blocks_are_partitioned(
    tmp_path: Path,
) -> None:
    """全IDのpartitionと先頭の1対1対応、余った訳文のtarget_only分類を検査する。"""

    source = _document("source", ["Section 1", "source only"])
    target = _document("target", ["節 1", "target extra", "target only"])

    groups = align.run(source, target, tmp_path / "align")

    _assert_partition(groups, source, target)
    assert groups[0].source_ids == ["source/0"]
    assert groups[0].target_ids == ["target/0"]
    assert groups[-1].kind == "target_only"


@pytest.mark.parametrize(
    "case",
    [
        (
            ["one source"],
            ["target a", "target b"],
            [
                AlignmentGroup(
                    source_ids=["source/0"], target_ids=["target/0", "target/1"]
                )
            ],
        ),
        (
            ["source a", "source b"],
            ["one target"],
            [
                AlignmentGroup(
                    source_ids=["source/0", "source/1"], target_ids=["target/0"]
                )
            ],
        ),
    ],
    ids=["one-to-many", "many-to-one"],
)
def test_model_alignment_accepts_valid_multi_block_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    case: tuple[list[str], list[str], list[AlignmentGroup]],
) -> None:
    """有効な1対多・多対1応答を全ID一意のpartitionとして採用する。"""

    source_texts, target_texts, expected = case
    source = _document("source", source_texts)
    target = _document("target", target_texts)
    monkeypatch.setattr(
        align,
        "structured",
        lambda *_args, **_kwargs: align.AlignmentResponse(groups=expected),
    )

    groups = align.run(source, target, tmp_path / "align", settings_factory())

    assert groups == expected
    _assert_partition(groups, source, target)
