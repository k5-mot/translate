"""POSITION: 座標に基づきDocling要素の読み順を補正する。"""

from __future__ import annotations

import copy
import json
import statistics
from typing import TYPE_CHECKING, Any

from translate.common.workspace import atomic_directory, atomic_write_json
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path


def _key(item: dict[str, Any], fallback: int) -> tuple[int, float, float, int]:
    """先頭bboxの座標原点を補正して読み順keyを作り、座標欠落要素は末尾で元の順序を保つ。"""

    provenance = item.get("prov")
    entry = provenance[0] if isinstance(provenance, list) and provenance else None
    if not isinstance(entry, dict):
        return 10**9, 0, 0, fallback
    box = entry.get("bbox")
    if not isinstance(box, dict):
        return 10**9, 0, 0, fallback
    page = int(entry.get("page_no", 10**9))
    top = float(box.get("t", box.get("top", 0)))
    bottom = float(box.get("b", box.get("bottom", 0)))
    left = float(box.get("l", box.get("left", 0)))
    origin = str(box.get("coord_origin", "BOTTOMLEFT")).upper()
    # Note 1: Normalize top-left and bottom-left coordinate systems to reading order.
    vertical = min(top, bottom) if origin == "TOPLEFT" else -max(top, bottom)
    return page, vertical, left, fallback


def _resolve(document: dict[str, Any], ref: str) -> dict[str, Any] | None:
    """Doclingの文書内参照を辞書へ解決し、参照不正や辞書以外の値ではNoneを返す。"""

    value: Any = document
    try:
        for part in ref.removeprefix("#/").split("/"):
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _geometry(item: dict[str, Any]) -> tuple[int, float, float, float, float] | None:
    """bboxを左、右、上、下が同じ向きの比較値へ正規化する。"""

    provenance = item.get("prov")
    entry = provenance[0] if isinstance(provenance, list) and provenance else None
    box = entry.get("bbox") if isinstance(entry, dict) else None
    if not isinstance(entry, dict) or not isinstance(box, dict):
        return None
    try:
        left, right = sorted((float(box["l"]), float(box["r"])))
        first, second = float(box["t"]), float(box["b"])
        if str(box.get("coord_origin", "BOTTOMLEFT")).upper() == "TOPLEFT":
            top, bottom = sorted((first, second))
        else:
            top, bottom = sorted((-first, -second))
        return int(entry.get("page_no", 1)), left, right, top, bottom
    except (KeyError, TypeError, ValueError):
        return None


def _continuous(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """同じページ・同じ本文種別で、横方向の重なりと縦の間隔が結合条件を満たすか判定する。"""

    labels = {str(first.get("label", "")), str(second.get("label", ""))}
    if len(labels) != 1 or not labels <= {
        "text",
        "paragraph",
        "code",
        "program_listing",
    }:
        return False
    first_box, second_box = _geometry(first), _geometry(second)
    if first_box is None or second_box is None or first_box[0] != second_box[0]:
        return False
    _, left_a, right_a, _, bottom_a = first_box
    _, left_b, right_b, top_b, _ = second_box
    overlap = max(0.0, min(right_a, right_b) - max(left_a, left_b))
    narrow = max(1.0, min(right_a - left_a, right_b - left_b))
    # Note 3: Require strong horizontal overlap and a small vertical gap.
    return overlap / narrow >= 0.7 and -2 <= top_b - bottom_a <= 20


def _rewrite_ref(value: Any, old: str, new: str) -> Any:
    """結合先へ参照を付け替えるため、各文字列内で最初に現れる旧参照を置換する。"""

    if isinstance(value, list):
        return [_rewrite_ref(item, old, new) for item in value]
    if not isinstance(value, dict):
        return value.replace(old, new, 1) if isinstance(value, str) else value
    return {key: _rewrite_ref(item, old, new) for key, item in value.items()}


def _merge_table(  # noqa: PLR0911
    first: dict[str, Any], second: dict[str, Any]
) -> bool:
    """同一ページで近接し列数が一致する表を、セル行位置と参照を補正して先頭の表へ結合する。"""

    if first.get("label") != "table" or second.get("label") != "table":
        return False
    first_box, second_box = _geometry(first), _geometry(second)
    if first_box is None or second_box is None or first_box[0] != second_box[0]:
        return False
    _, left_a, right_a, _, bottom_a = first_box
    _, left_b, right_b, top_b, _ = second_box
    overlap = max(0.0, min(right_a, right_b) - max(left_a, left_b))
    if overlap / max(1.0, min(right_a - left_a, right_b - left_b)) < 0.8:
        return False
    if not -2 <= top_b - bottom_a <= 24:
        return False
    first_data, second_data = first.get("data"), second.get("data")
    if not isinstance(first_data, dict) or not isinstance(second_data, dict):
        return False
    key = "table_cells" if "table_cells" in first_data else "cells"
    if key not in first_data or key not in second_data:
        return False
    first_cells, second_cells = first_data[key], second_data[key]
    if not isinstance(first_cells, list) or not isinstance(second_cells, list):
        return False
    if not all(isinstance(cell, dict) for cell in [*first_cells, *second_cells]):
        return False

    def dimensions(cells: list[dict[str, Any]]) -> tuple[int, int] | None:
        """セル終端の最大値から表の行列数を得て、欠落や数値変換失敗では結合不可とする。"""

        try:
            rows = max(int(cell["end_row_offset_idx"]) for cell in cells)
            columns = max(int(cell["end_col_offset_idx"]) for cell in cells)
        except (KeyError, TypeError, ValueError):
            return None
        return rows, columns

    first_dimensions = dimensions(first_cells)
    second_dimensions = dimensions(second_cells)
    if (
        first_dimensions is None
        or second_dimensions is None
        or first_dimensions[1] != second_dimensions[1]
    ):
        return False
    row_offset = first_dimensions[0]
    old_ref = str(second.get("self_ref", ""))
    new_ref = str(first.get("self_ref", ""))
    adjusted: list[dict[str, Any]] = []
    for cell in second_cells:
        mapped = _rewrite_ref(copy.deepcopy(cell), old_ref, new_ref)
        mapped["start_row_offset_idx"] = (
            int(mapped["start_row_offset_idx"]) + row_offset
        )
        mapped["end_row_offset_idx"] = int(mapped["end_row_offset_idx"]) + row_offset
        adjusted.append(mapped)
    first_data[key] = [*first_cells, *adjusted]
    first_data["num_rows"] = first_dimensions[0] + second_dimensions[0]
    first_data["num_cols"] = first_dimensions[1]
    if isinstance(first.get("prov"), list) and isinstance(second.get("prov"), list):
        first["prov"].extend(second["prov"])
    return True


def _merge_fragments(
    document: dict[str, Any],
    node: Any,
    merged: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    """隣接する本文・表の断片を条件付きで結合し、曖昧な表は残して警告を記録する。"""

    if not isinstance(node, dict) or not isinstance(node.get("children"), list):
        return
    children = node["children"]
    index = 0
    while index + 1 < len(children):
        first_ref = (
            children[index].get("$ref") if isinstance(children[index], dict) else None
        )
        second_ref = (
            children[index + 1].get("$ref")
            if isinstance(children[index + 1], dict)
            else None
        )
        first = _resolve(document, first_ref) if isinstance(first_ref, str) else None
        second = _resolve(document, second_ref) if isinstance(second_ref, str) else None
        if (
            first is not None
            and second is not None
            and first.get("label") == second.get("label") == "table"
        ):
            if _merge_table(first, second):
                children.pop(index + 1)
                merged.append(
                    {
                        "into": str(first_ref),
                        "from": str(second_ref),
                        "reason": "table rows and spans reconstructed",
                    }
                )
                continue
            warnings.append(
                {
                    "first": str(first_ref),
                    "second": str(second_ref),
                    "reason": "ambiguous table fragments kept separate",
                }
            )
            index += 1
            continue
        if first is not None and second is not None and _continuous(first, second):
            separator = (
                "\n" if first.get("label") in {"code", "program_listing"} else " "
            )
            first["text"] = (
                f"{str(first.get('text', '')).rstrip()}{separator}{str(second.get('text', '')).lstrip()}"
            )
            if isinstance(first.get("prov"), list) and isinstance(
                second.get("prov"), list
            ):
                first["prov"].extend(second["prov"])
            children.pop(index + 1)
            merged.append({"into": str(first_ref), "from": str(second_ref)})
            continue
        index += 1
    for child in children:
        ref = child.get("$ref") if isinstance(child, dict) else None
        target = _resolve(document, ref) if isinstance(ref, str) else None
        if target is not None:
            _merge_fragments(document, target, merged, warnings)


def _reading_order(
    document: dict[str, Any], children: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """座標のある要素をページ・段組・領域ごとに並べ、座標のない要素は元の順で末尾へ残す。"""

    positioned: dict[
        int, list[tuple[int, dict[str, Any], dict[str, Any], tuple[float, ...]]]
    ] = {}
    unpositioned: list[tuple[int, dict[str, Any]]] = []
    for index, child in enumerate(children):
        ref = child.get("$ref")
        item = _resolve(document, ref) if isinstance(ref, str) else None
        geometry = _geometry(item or {})
        if item is None or geometry is None:
            unpositioned.append((index, child))
            continue
        positioned.setdefault(int(geometry[0]), []).append(
            (index, child, item, geometry)
        )

    ordered: list[dict[str, Any]] = []
    for page in sorted(positioned):
        entries = positioned[page]
        widths = [max(1.0, entry[3][2] - entry[3][1]) for entry in entries]
        tolerance = statistics.median(widths) * 0.6
        columns: list[float] = []
        for left in sorted(entry[3][1] for entry in entries):
            if not columns or abs(left - columns[-1]) > tolerance:
                columns.append(left)

        def order_key(
            entry: tuple[int, dict[str, Any], dict[str, Any], tuple[float, ...]],
            column_positions: tuple[float, ...] = tuple(columns),
        ) -> tuple[int, int, float, float, float, int]:
            """欄外種別、最寄りの段、縦位置を順に比較し、同位置では元の順序を保つkeyを作る。"""

            index, _child, item, geometry = entry
            _page, left, _right, top, bottom = geometry
            label = str(item.get("label", ""))
            region = (
                0
                if label == "page_header"
                else 2
                if label in {"page_footer", "footnote"}
                else 1
            )
            column = min(
                range(len(column_positions)),
                key=lambda value: abs(column_positions[value] - left),
            )
            center = (top + bottom) / 2
            return region, column, top, center, left, index

        ordered.extend(entry[1] for entry in sorted(entries, key=order_key))
    ordered.extend(child for _, child in sorted(unpositioned))
    return ordered


def _sort_children(
    document: dict[str, Any], node: Any, report: list[dict[str, Any]]
) -> None:
    """各参照treeの子要素を読み順へ並べ替え、変更前後の参照列をreportへ記録する。"""

    if not isinstance(node, dict):
        return
    children = node.get("children")
    if not isinstance(children, list):
        return
    before = [child.get("$ref") for child in children if isinstance(child, dict)]
    typed_children = [child for child in children if isinstance(child, dict)]
    children[:] = _reading_order(document, typed_children)
    after = [child.get("$ref") for child in children if isinstance(child, dict)]
    if before != after:
        report.append(
            {
                "container": str(node.get("self_ref", "#/body")),
                "before": before,
                "after": after,
                "reason": "multi-column stable reading order",
            }
        )
    for child in children:
        ref = child.get("$ref") if isinstance(child, dict) else None
        target = _resolve(document, ref) if isinstance(ref, str) else None
        if target is not None:
            _sort_children(document, target, report)


class PositionTask(BaseTask):
    """Execute POSITION while sharing elapsed-time measurement only."""

    name = "POSITION"

    def run(self, source: Path, output_dir: Path) -> Path:
        """読み順を補正してJSONとreportを保存する。"""

        with self.measure():
            document = copy.deepcopy(json.loads(source.read_text(encoding="utf-8")))
            changed: list[dict[str, Any]] = []
            _sort_children(document, document.get("body", {}), changed)
            merged: list[dict[str, str]] = []
            warnings: list[dict[str, str]] = []
            _merge_fragments(document, document.get("body", {}), merged, warnings)
            with atomic_directory(output_dir) as temporary:
                atomic_write_json(temporary / "document.json", document)
                atomic_write_json(
                    temporary / "report.json",
                    {"reordered": changed, "merged": merged, "warnings": warnings},
                )
            return output_dir / "document.json"


def run(source: Path, output_dir: Path) -> Path:
    """Existing function delegates to the typed PositionTask operation."""

    return PositionTask().run(source, output_dir)
