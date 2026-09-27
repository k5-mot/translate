"""POSITION: 座標に基づきDocling要素の読み順を補正する。"""

from __future__ import annotations

import copy
import json
import re
import statistics
from collections import defaultdict
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
    first_box, second_box = _tail_geometry(first), _geometry(second)
    if first_box is None or second_box is None or first_box[0] != second_box[0]:
        return False
    _, left_a, right_a, _, bottom_a = first_box
    _, left_b, right_b, top_b, _ = second_box
    overlap = max(0.0, min(right_a, right_b) - max(left_a, left_b))
    narrow = max(1.0, min(right_a - left_a, right_b - left_b))
    # Note 3: Require strong horizontal overlap and a small vertical gap.
    return overlap / narrow >= 0.7 and -2 <= top_b - bottom_a <= 20


def _tail_geometry(
    item: dict[str, Any],
) -> tuple[int, float, float, float, float] | None:
    """連鎖結合では最後の断片の座標を使い、先頭bboxとの距離で後続を取り残さない。"""

    provenance = item.get("prov")
    return (
        _geometry({"prov": provenance[-1:]}) if isinstance(provenance, list) else None
    )


def _mapped_ref(ref: str, mapping: dict[str, str]) -> str:
    """完全なIDを優先し、残るcollection参照はindex segment単位で一度だけ写す。"""

    if ref in mapping:
        return mapping[ref]
    pieces = ref.split("/")
    root = "/".join(pieces[:3])
    return "/".join([mapping[root], *pieces[3:]]) if root in mapping else ref


def _rewrite_ref(value: Any, mapping: dict[str, str]) -> Any:
    """構造上の参照だけを更新し、本文やURL等の一般文字列は保持する。"""

    if isinstance(value, list):
        return [_rewrite_ref(item, mapping) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _mapped_ref(item, mapping)
        if key in {"self_ref", "$ref"} and isinstance(item, str)
        else _rewrite_ref(item, mapping)
        for key, item in value.items()
    }


def _unsafe_merge_refs(document: dict[str, Any]) -> set[str]:
    """所有childrenとセルparentの逆参照を区別し、共有・外部参照のある候補を除く。"""

    incoming: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    pending: list[tuple[Any, tuple[str, ...]]] = [(document, ())]
    while pending:
        value, path = pending.pop()
        if isinstance(value, list):
            pending.extend(
                (item, (*path, str(index))) for index, item in enumerate(value)
            )
        elif isinstance(value, dict):
            for key, item in value.items():
                if key == "$ref" and isinstance(item, str):
                    incoming[item].append((*path, key))
                else:
                    pending.append((item, (*path, key)))
    unsafe: set[str] = set()
    for ref, paths in incoming.items():
        parts = ref.removeprefix("#/").split("/")
        if len(parts) > 2:
            # Nested cell references cannot be transferred by collection reindexing alone.
            unsafe.add("#/" + "/".join(parts[:2]))
        owners = [
            path
            for path in paths
            if not (
                len(path) == 7
                and tuple(parts) == path[:2]
                and path[2] == "data"
                and path[3] in {"table_cells", "cells"}
                and path[-2:] == ("parent", "$ref")
            )
        ]
        if len(owners) != 1 or owners[0][-3:-2] != ("children",):
            unsafe.add(ref)
    return unsafe


def _merge_metadata_safe(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """所有内容や異なる表示属性を黙って捨てる結合を拒否する。"""

    owned = ("children", "captions", "caption", "title", "image")
    if any(item.get(key) for item in (first, second) for key in owned):
        return False
    ignored = {"self_ref", "prov", "text", "orig"}
    if first.get("label") == "table":
        if any(item.get(key) for item in (first, second) for key in ("text", "orig")):
            return False
        ignored.add("data")
    elif any(
        not isinstance(item.get(key, ""), str)
        for item in (first, second)
        for key in ("text", "orig")
    ):
        return False
    # An optional original-text layer must not be silently added or lost.
    if ("orig" in first) != ("orig" in second):
        return False
    return {key: value for key, value in first.items() if key not in ignored} == {
        key: value for key, value in second.items() if key not in ignored
    }


def _compact_fragments(
    document: dict[str, Any], merged: list[dict[str, str]]
) -> dict[str, Any]:
    """消費元だけを除去して全構造参照を再採番し、reportに出力側IDを残す。"""

    consumed = {item["from"] for item in merged}
    mapping: dict[str, str] = {}
    for collection in ("texts", "tables"):
        if collection not in document:
            continue
        kept = []
        for index, item in enumerate(document[collection]):
            old_ref = f"#/{collection}/{index}"
            if old_ref in consumed:
                continue
            mapping[old_ref] = f"#/{collection}/{len(kept)}"
            kept.append(item)
        document[collection] = kept
    for item in merged:
        item["output_ref"] = mapping[item["into"]]
    return _rewrite_ref(document, mapping)


def _table_shape(data: dict[str, Any], key: str) -> tuple[int, int] | None:  # noqa: PLR0911
    """セル範囲と宣言寸法を検査し、不整合や重なるセルを結合対象から外す。"""

    cells = data[key]
    if not isinstance(cells, list) or not cells:
        return None
    ranges: list[tuple[int, int, int, int]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            return None
        bounds = tuple(
            cell.get(f"{edge}_{axis}_offset_idx")
            for axis in ("row", "col")
            for edge in ("start", "end")
        )
        if any(type(value) is not int for value in bounds):
            return None
        row, end_row, col, end_col = bounds
        if not (0 <= row < end_row and 0 <= col < end_col):
            return None
        if (
            cell.get("row_span", end_row - row) != end_row - row
            or cell.get("col_span", end_col - col) != end_col - col
        ):
            return None
        if any(
            row < b and a < end_row and col < d and c < end_col for a, b, c, d in ranges
        ):
            return None
        ranges.append((row, end_row, col, end_col))
    rows = max(item[1] for item in ranges)
    columns = max(item[3] for item in ranges)
    if data.get("num_rows", rows) != rows or data.get("num_cols", columns) != columns:
        return None
    return rows, columns


def _merge_table(  # noqa: PLR0911
    first: dict[str, Any], second: dict[str, Any]
) -> bool:
    """同一ページで近接し列数が一致する表を、セル行位置と参照を補正して先頭の表へ結合する。"""

    if first.get("label") != "table" or second.get("label") != "table":
        return False
    first_box, second_box = _tail_geometry(first), _geometry(second)
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
    representations = {"table_cells", "cells", "grid"}
    keys = representations.intersection(first_data)
    if (
        len(keys) != 1
        or keys != representations.intersection(second_data)
        or "grid" in keys
    ):
        return False
    key = next(iter(keys))
    ignored = {key, "num_rows", "num_cols"}
    if {name: value for name, value in first_data.items() if name not in ignored} != {
        name: value for name, value in second_data.items() if name not in ignored
    }:
        return False
    first_cells, second_cells = first_data[key], second_data[key]
    first_dimensions = _table_shape(first_data, key)
    second_dimensions = _table_shape(second_data, key)
    if (
        first_dimensions is None
        or second_dimensions is None
        or first_dimensions[1] != second_dimensions[1]
    ):
        return False
    row_offset = first_dimensions[0]
    old_ref = str(second.get("self_ref", ""))
    new_ref = str(first.get("self_ref", ""))
    mapping = {old_ref: new_ref}
    for table, cells in ((first, first_cells), (second, second_cells)):
        ref = table["self_ref"]
        for index, cell in enumerate(cells):
            expected = f"{ref}/cell/{index}"
            if cell.get("self_ref", expected) != expected:
                return False
            if "parent" in cell and cell["parent"] != {"$ref": ref}:
                return False
            if table is second:
                mapping[expected] = f"{new_ref}/cell/{len(first_cells) + index}"
    adjusted: list[dict[str, Any]] = []
    for cell in second_cells:
        mapped = _rewrite_ref(cell, mapping)
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
    unsafe: set[str],
    visited: set[int],
) -> None:
    """隣接する本文・表の断片を条件付きで結合し、曖昧な表は残して警告を記録する。"""

    if not isinstance(node, dict) or not isinstance(node.get("children"), list):
        return
    if id(node) in visited:
        return
    visited.add(id(node))
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
        table_pair = (
            first is not None
            and second is not None
            and first.get("label") == second.get("label") == "table"
        )
        text_pair = (
            first is not None and second is not None and _continuous(first, second)
        )
        collection = "tables" if table_pair else "texts"
        if (table_pair or text_pair) and (
            first_ref == second_ref
            or first_ref in unsafe
            or second_ref in unsafe
            or first.get("self_ref") != first_ref
            or second.get("self_ref") != second_ref
            or any(
                re.fullmatch(rf"#/{collection}/(?:0|[1-9][0-9]*)", str(ref)) is None
                for ref in (first_ref, second_ref)
            )
            or not _merge_metadata_safe(first, second)
        ):
            warnings.append(
                {
                    "first": str(first_ref),
                    "second": str(second_ref),
                    "reason": "ambiguous ownership or metadata kept separate",
                }
            )
            index += 1
            continue
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
            for key in ("text", "orig"):
                if key == "text" or key in first:
                    first[key] = (
                        f"{first.get(key, '').rstrip()}{separator}{second.get(key, '').lstrip()}"
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
            _merge_fragments(document, target, merged, warnings, unsafe, visited)


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
    document: dict[str, Any],
    node: Any,
    report: list[dict[str, Any]],
    visited: set[int] | None = None,
) -> None:
    """各参照treeの子要素を読み順へ並べ替え、変更前後の参照列をreportへ記録する。"""

    if not isinstance(node, dict):
        return
    if visited is None:
        visited = set()
    if id(node) in visited:
        return
    visited.add(id(node))
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
            _sort_children(document, target, report, visited)


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
            _merge_fragments(
                document,
                document.get("body", {}),
                merged,
                warnings,
                _unsafe_merge_refs(document),
                set(),
            )
            document = _compact_fragments(document, merged)
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
