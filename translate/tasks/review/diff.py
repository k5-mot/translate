"""英文v1と英文v2を決定的に比較してUpgrade計画を作る。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from translate.artifact_store import write_model
from translate.models.document import (
    Document,
    TextSpan,
    TextUnit,
    iter_text_units,
    text_unit_index,
)
from translate.models.upgrade import (
    ChangeAction,
    ChangeKind,
    ChangeMethod,
    UpgradePlan,
    VersionChange,
)
from translate.tasks.review.align import align

if TYPE_CHECKING:
    from pathlib import Path

    from translate.models.artifacts import AlignmentResult


@dataclass(frozen=True, slots=True)
class _Element:
    """DIFF用の読み順、roleおよび正規化text。"""

    index: int
    role: str
    unit: TextUnit
    normalized: str


def diff(
    source_v1: Document,
    source_v2: Document,
    translation_v1: Document,
    baseline: AlignmentResult,
    task_directory: Path,
) -> UpgradePlan:
    """一意な同文と既存ALIGNから版間変更と再利用方針を確定する。

    Args:
        source_v1 (Document): 比較基準にする英文v1。
        source_v2 (Document): 変更を反映する英文v2。
        translation_v1 (Document): 比較基準にする日本語v1。
        baseline (AlignmentResult): 版間差分の基準にするALIGN結果。
        task_directory (Path): 対象Taskの成果物Directory。

    Returns:
        UpgradePlan: 一意な同文と既存ALIGNから版間変更と再利用方針を確定する。
    """

    old = _elements(source_v1)
    new = _elements(source_v2)
    pairs = _version_pairs(source_v1, source_v2, old, new)
    reverse = {
        new_index: (old_index, method)
        for old_index, (new_index, method) in pairs.items()
    }
    translated_by_source = _baseline_pairs(baseline)
    translated_units = text_unit_index(translation_v1)
    changes: list[VersionChange] = []
    paired_old: set[int] = set()
    for element in new:
        pair = reverse.get(element.index)
        if pair is None:
            changes.append(
                _change(
                    len(changes),
                    element,
                    None,
                    [],
                    "added",
                    "translate",
                    "unmatched",
                )
            )
            continue
        old_index, method = pair
        paired_old.add(old_index)
        previous = old[old_index]
        if previous.normalized == element.normalized:
            kind = "unchanged" if old_index == element.index else "moved"
        else:
            kind = "modified"
        translation_ids = translated_by_source.get(previous.unit.id, [])
        action = (
            "reuse"
            if kind in {"unchanged", "moved"}
            and len(translation_ids) == 1
            and _compatible(element.unit, translated_units.get(translation_ids[0]))
            else "translate"
        )
        changes.append(
            _change(
                len(changes),
                element,
                previous,
                translation_ids,
                kind,
                action,
                method,
            )
        )
    for element in old:
        if element.index not in paired_old:
            changes.append(
                VersionChange(
                    id=f"change-{len(changes) + 1:06d}",
                    kind="deleted",
                    source_v1_ids=[element.unit.id],
                    translation_v1_ids=translated_by_source.get(element.unit.id, []),
                    action="delete",
                    method="unmatched",
                )
            )
    result = UpgradePlan(changes=changes)
    write_model(task_directory / "plan.json", result)
    return result


def _elements(document: Document) -> list[_Element]:
    """空でないTextUnitを文書の読み順で列挙する。

    Args:
        document (Document): 変換または検証対象のDocument。

    Returns:
        list[_Element]: 空でないTextUnitを文書の読み順で列挙する。
    """

    values = [
        (role, unit, _normalize(unit.text("source")))
        for role, unit in iter_text_units(document)
    ]
    return [
        _Element(index, role, unit, normalized)
        for index, (role, unit, normalized) in enumerate(
            item for item in values if item[2]
        )
    ]


def _version_pairs(
    source_v1: Document,
    source_v2: Document,
    old: list[_Element],
    new: list[_Element],
) -> dict[int, tuple[int, ChangeMethod]]:
    """一意な同文を優先し、残りへ既存ALIGNの保守的な対応を使う。

    Args:
        source_v1 (Document): 比較基準にする英文v1。
        source_v2 (Document): 変更を反映する英文v2。
        old (list[_Element]): 旧版の比較要素または対応する旧要素。
        new (list[_Element]): 新版の比較要素または現在の要素。

    Returns:
        dict[int, tuple[int, ChangeMethod]]: 一意な同文を優先し、残りへ既存ALIGNの保守的な対応を使う。
    """

    old_keys = _key_positions(old)
    new_keys = _key_positions(new)
    pairs: dict[int, tuple[int, ChangeMethod]] = {
        old_keys[key][0]: (new_keys[key][0], "unique_text")
        for key in old_keys.keys() & new_keys.keys()
        if len(old_keys[key]) == len(new_keys[key]) == 1
    }
    used_new = {value[0] for value in pairs.values()}
    old_by_id = {item.unit.id: item.index for item in old}
    new_by_id = {item.unit.id: item.index for item in new}
    for group in align(source_v1, source_v2).groups:
        if (
            group.kind != "matched"
            or len(group.source_ids) != 1
            or len(group.translation_ids) != 1
        ):
            continue
        old_index = old_by_id[group.source_ids[0]]
        new_index = new_by_id[group.translation_ids[0]]
        if old_index not in pairs and new_index not in used_new:
            pairs[old_index] = (new_index, group.method)
            used_new.add(new_index)
    return pairs


def _key_positions(elements: list[_Element]) -> dict[tuple[str, str], list[int]]:
    """roleと正規化textごとの出現位置を保持する。

    Args:
        elements (list[_Element]): 位置を索引化する比較要素列。

    Returns:
        dict[tuple[str, str], list[int]]: roleと正規化textごとの出現位置を保持する。
    """

    result: dict[tuple[str, str], list[int]] = {}
    for element in elements:
        result.setdefault((element.role, element.normalized), []).append(element.index)
    return result


def _baseline_pairs(alignment: AlignmentResult) -> dict[str, list[str]]:
    """1対1の英文v1と日本語v1対応だけをID索引へ変換する。

    Args:
        alignment (AlignmentResult): Reportへ記録するALIGN結果。

    Returns:
        dict[str, list[str]]: 1対1の英文v1と日本語v1対応だけをID索引へ変換する。
    """

    return {
        group.source_ids[0]: group.translation_ids
        for group in alignment.groups
        if group.kind == "matched"
        and len(group.source_ids) == 1
        and len(group.translation_ids) == 1
    }


def _compatible(source_v2: TextUnit, translation_v1: TextUnit | None) -> bool:
    """再利用対象Spanの件数、kindおよび日本語textを検査する。

    Args:
        source_v2 (TextUnit): 変更を反映する英文v2。
        translation_v1 (TextUnit | None): 比較基準にする日本語v1。

    Returns:
        bool: 再利用対象Spanの件数、kindおよび日本語textを検査する。
    """

    if translation_v1 is None:
        return False
    source_spans = _translatable_spans(source_v2)
    translation_spans = _translatable_spans(translation_v1)
    return (
        bool(source_spans)
        and len(source_spans) == len(translation_spans)
        and all(
            source.kind == translated.kind and translated.source.strip()
            for source, translated in zip(source_spans, translation_spans, strict=True)
        )
    )


def _translatable_spans(unit: TextUnit) -> list[TextSpan]:
    """翻訳対象となるSpanだけを読み順で返す。

    Args:
        unit (TextUnit): 変換または検証対象のTextUnit。

    Returns:
        list[TextSpan]: 翻訳対象となるSpanだけを読み順で返す。
    """

    return [span for span in unit.spans if span.kind not in {"code", "line_break"}]


def _change(
    index: int,
    new: _Element,
    old: _Element | None,
    translation_ids: list[str],
    kind: ChangeKind,
    action: ChangeAction,
    method: ChangeMethod,
) -> VersionChange:
    """一つの版間対応を永続化modelへ変換する。

    Args:
        index (int): 対象要素の読み順Index。
        new (_Element): 新版の比較要素または現在の要素。
        old (_Element | None): 旧版の比較要素または対応する旧要素。
        translation_ids (list[str]): Upgrade変更へ関連付ける旧訳ID列。
        kind (ChangeKind): 生成する版間変更の種別。
        action (ChangeAction): Task本体として実行するCallable。
        method (ChangeMethod): Docling APIへ送信するHTTP Method。

    Returns:
        VersionChange: 一つの版間対応を永続化modelへ変換する。
    """

    return VersionChange.model_validate(
        {
            "id": f"change-{index + 1:06d}",
            "kind": kind,
            "source_v1_ids": [old.unit.id] if old is not None else [],
            "source_v2_ids": [new.unit.id],
            "translation_v1_ids": translation_ids,
            "action": action,
            "method": method,
        }
    )


def _normalize(value: str) -> str:
    """NFKC化したtextの前後と連続空白を正規化する。

    Args:
        value (str): 版間比較用にUnicodeと空白を正規化するText。

    Returns:
        str: NFKC化したtextの前後と連続空白を正規化する。
    """

    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip())
