"""独立した原文と訳文を保守的に対応付けるALIGN Task。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from translate.models.artifacts import AlignmentResult
from translate.models.document import Document, TextUnit, iter_text_units
from translate.models.review import AlignmentGroup, ReviewTarget

_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_SECTION = re.compile(r"^\s*(\d+(?:\.\d+)+)(?=\s|[.)、:\N{FULLWIDTH COLON}-]|$)")
_FIGURE = re.compile(r"(?:\bFigure\s*|\bFig\.\s*|図\s*)(\d+)", re.IGNORECASE)
_TABLE = re.compile(r"(?:\bTable\s*|表\s*)(\d+)", re.IGNORECASE)
_TRAILING_PUNCTUATION = (
    ".,;:!?)]}、。"
    "\N{FULLWIDTH COMMA}\N{FULLWIDTH SEMICOLON}\N{FULLWIDTH COLON}"
    "\N{FULLWIDTH EXCLAMATION MARK}\N{FULLWIDTH QUESTION MARK}"
    "\N{FULLWIDTH RIGHT PARENTHESIS}」』】〉》"
)
AlignmentMethod = Literal["unique_anchor", "ordered_role"]


@dataclass(frozen=True, slots=True)
class _Element:
    """ALIGNが使用する読み順、roleおよびTextUnit。"""

    index: int
    role: str
    unit: TextUnit
    text: str


def align(source: Document, translation: Document) -> AlignmentResult:
    """一意なanchorと一致するrole列だけから1対1対応を作る。"""

    source_elements = _elements(source)
    translation_elements = _elements(translation)
    anchor_pairs = _anchor_pairs(source_elements, translation_elements)
    pairs: dict[int, tuple[int, AlignmentMethod]] = {}
    boundaries = [
        (-1, -1),
        *anchor_pairs,
        (len(source_elements), len(translation_elements)),
    ]
    for boundary_index in range(len(boundaries) - 1):
        source_left, translation_left = boundaries[boundary_index]
        source_right, translation_right = boundaries[boundary_index + 1]
        source_segment = source_elements[source_left + 1 : source_right]
        translation_segment = translation_elements[
            translation_left + 1 : translation_right
        ]
        if [item.role for item in source_segment] == [
            item.role for item in translation_segment
        ]:
            for source_item, translation_item in zip(
                source_segment,
                translation_segment,
                strict=True,
            ):
                pairs[source_item.index] = (translation_item.index, "ordered_role")
        if source_right < len(source_elements):
            pairs[source_right] = (translation_right, "unique_anchor")
    return _build_result(source_elements, translation_elements, pairs)


def _elements(document: Document) -> list[_Element]:
    """空文字列を除いた文書要素を読み順の内部表現へ変換する。"""

    values = [
        (role, unit, unit.text("source").strip())
        for role, unit in iter_text_units(document)
    ]
    return [
        _Element(index, role, unit, text)
        for index, (role, unit, text) in enumerate(values)
        if text
    ]


def _anchor_pairs(
    source: list[_Element],
    translation: list[_Element],
) -> list[tuple[int, int]]:
    """両文書で一意かつ順序が逆転しない同一anchorを抽出する。"""

    source_anchors = _anchor_positions(source)
    translation_anchors = _anchor_positions(translation)
    candidates = sorted(
        (
            (source_anchors[anchor][0], translation_anchors[anchor][0])
            for anchor in source_anchors.keys() & translation_anchors.keys()
            if len(source_anchors[anchor]) == len(translation_anchors[anchor]) == 1
        ),
        key=lambda item: item[0],
    )
    result: list[tuple[int, int]] = []
    previous_translation = -1
    for pair in candidates:
        if pair[1] > previous_translation:
            result.append(pair)
            previous_translation = pair[1]
    return result


def _anchor_positions(elements: list[_Element]) -> dict[str, list[int]]:
    """各anchorが現れる要素位置を保持する。"""

    result: dict[str, list[int]] = {}
    for element in elements:
        for anchor in _anchors(element.text, element.role):
            result.setdefault(anchor, []).append(element.index)
    return result


def _anchors(text: str, role: str) -> set[str]:
    """標準正規表現とNFKCだけで仕様上のanchorを正規化する。"""

    normalized = unicodedata.normalize("NFKC", text)
    anchors = {
        f"url:{match.group(0).rstrip(_TRAILING_PUNCTUATION)}"
        for match in _URL.finditer(normalized)
    }
    if role == "heading" and (match := _SECTION.search(normalized)):
        anchors.add(f"section:{match.group(1)}")
    anchors.update(f"figure:{match.group(1)}" for match in _FIGURE.finditer(normalized))
    anchors.update(f"table:{match.group(1)}" for match in _TABLE.finditer(normalized))
    return anchors


def _build_result(
    source: list[_Element],
    translation: list[_Element],
    pairs: dict[int, tuple[int, AlignmentMethod]],
) -> AlignmentResult:
    """確定pairと未対応要素から連番IDの結果を組み立てる。"""

    reverse_pairs = {
        translation_index: source_index
        for source_index, (translation_index, _) in pairs.items()
    }
    events: list[tuple[float, AlignmentGroup, ReviewTarget | None]] = []
    for element in source:
        pair = pairs.get(element.index)
        if pair is None:
            group = AlignmentGroup(
                id="",
                source_ids=[element.unit.id],
                kind="source_only",
                method="unmatched",
            )
            events.append((float(element.index), group, None))
            continue
        translation_index, method = pair
        translated = translation[translation_index]
        group = AlignmentGroup(
            id="",
            source_ids=[element.unit.id],
            translation_ids=[translated.unit.id],
            kind="matched",
            method=method,
        )
        target = ReviewTarget(
            id="",
            source=element.text,
            translation=translated.text,
            target_ids=[translated.unit.id],
            spans=translated.unit.spans,
        )
        events.append((float(element.index), group, target))
    for element in translation:
        if element.index not in reverse_pairs:
            relative_position = (
                (element.index + 0.5) * max(1, len(source)) / max(1, len(translation))
            )
            group = AlignmentGroup(
                id="",
                translation_ids=[element.unit.id],
                kind="translation_only",
                method="unmatched",
            )
            events.append((relative_position, group, None))
    events.sort(key=lambda item: item[0])
    groups: list[AlignmentGroup] = []
    targets: list[ReviewTarget] = []
    for number, (_, group, target) in enumerate(events, start=1):
        group.id = f"alignment-{number:06d}"
        groups.append(group)
        if target is not None:
            target.id = f"review/{group.id}"
            targets.append(target)
    return AlignmentResult(groups=groups, targets=targets)
