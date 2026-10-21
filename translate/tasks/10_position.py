"""POSITION: 座標に基づきDocling要素の読み順を補正する。"""

import copy
import json
import re
import statistics
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from translate.adapters.artifact_store import temporary_task_directory, write_json


def _key(item: dict[str, Any], fallback: int) -> tuple[int, float, float, int]:
    """先頭bboxの座標原点を補正して読み順keyを作り、座標欠落要素は末尾で元の順序を保つ。

    Args:
        item (dict[str, Any]): 変換または位置計算対象の要素Data。
        fallback (int): 幾何情報がない場合の読み順。

    Returns:
        tuple[int, float, float, int]: 先頭bboxの座標原点を補正して読み順keyを作り、座標欠落要素は末尾で元の順序を保つ。
    """

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


def _geometry(item: dict[str, Any]) -> tuple[int, float, float, float, float] | None:
    """bboxを左、右、上、下が同じ向きの比較値へ正規化する。

    Args:
        item (dict[str, Any]): 変換または位置計算対象の要素Data。

    Returns:
        tuple[int, float, float, float, float] | None: bboxを左、右、上、下が同じ向きの比較値へ正規化する。
    """

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


def _continuous(
    first: dict[str, Any], second: dict[str, Any], *, same_line: bool = False
) -> bool:
    """同じページ・本文種別の断片が、領域に応じた結合方向で隣接するか調べる。

    Args:
        first (dict[str, Any]): 連続性を判定する先行要素。
        second (dict[str, Any]): 連続性を判定する後続要素。
        same_line: キー・値領域では同行の左右だけを判定し、それ以外は縦の連続性を調べる。

    Returns:
        結合方向の座標条件と本文種別が一致する場合にTrue。
    """

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
    _, left_a, right_a, top_a, bottom_a = first_box
    _, left_b, right_b, top_b, bottom_b = second_box
    if same_line:
        overlap = max(0.0, min(bottom_a, bottom_b) - max(top_a, top_b))
        height = max(1.0, min(bottom_a - top_a, bottom_b - top_b))
        # 小さい方の文字高さの7割以上が重なる、左から右への本文断片だけを結合する。
        return (
            labels <= {"text", "paragraph"}
            and overlap / height >= 0.7
            and right_a <= left_b
        )
    overlap = max(0.0, min(right_a, right_b) - max(left_a, left_b))
    narrow = max(1.0, min(right_a - left_a, right_b - left_b))
    # Note 3: Require strong horizontal overlap and a small vertical gap.
    return overlap / narrow >= 0.7 and -2 <= top_b - bottom_a <= 20


def _tail_geometry(
    item: dict[str, Any],
) -> tuple[int, float, float, float, float] | None:
    """連鎖結合では最後の断片の座標を使い、先頭bboxとの距離で後続を取り残さない。

    Args:
        item (dict[str, Any]): 変換または位置計算対象の要素Data。

    Returns:
        tuple[int, float, float, float, float] | None: 連鎖結合では最後の断片の座標を使い、先頭bboxとの距離で後続を取り残さない。
    """

    provenance = item.get("prov")
    return (
        _geometry({"prov": provenance[-1:]}) if isinstance(provenance, list) else None
    )


def _mapped_ref(ref: str, mapping: dict[str, str]) -> str:
    """完全なIDを優先し、残るcollection参照はindex segment単位で一度だけ写す。

    Args:
        ref (str): Docling要素を指すJSON参照。
        mapping (dict[str, str]): 旧参照から新参照への対応表。

    Returns:
        str: 完全なIDを優先し、残るcollection参照はindex segment単位で一度だけ写す。
    """

    if ref in mapping:
        return mapping[ref]
    pieces = ref.split("/")
    root = "/".join(pieces[:3])
    return "/".join([mapping[root], *pieces[3:]]) if root in mapping else ref


def _rewrite_ref(value: Any, mapping: dict[str, str]) -> Any:
    """構造上の参照だけを更新し、本文やURL等の一般文字列は保持する。

    Args:
        value (Any): 内部参照を書き換えるDocument要素。
        mapping (dict[str, str]): 旧参照から新参照への対応表。

    Returns:
        Any: 構造上の参照だけを更新し、本文やURL等の一般文字列は保持する。
    """

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


def _merge_metadata_safe(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """所有内容や異なる表示属性を黙って捨てる結合を拒否する。

    Args:
        first (dict[str, Any]): Metadataを保持する先行要素。
        second (dict[str, Any]): Metadataを統合する後続要素。

    Returns:
        bool: 所有内容や異なる表示属性を黙って捨てる結合を拒否する。
    """

    first_geometry, second_geometry = _geometry(first), _geometry(second)
    owned = ("children", "captions", "caption", "title", "image")
    # Matching tail coordinates alone must not move a fragment to another page.
    if (
        first_geometry is None
        or second_geometry is None
        or first_geometry[0] != second_geometry[0]
        or any(item.get(key) for item in (first, second) for key in owned)
    ):
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
    """消費元だけを除去して全構造参照を再採番し、reportに出力側IDを残す。

    Args:
        document (dict[str, Any]): 変換または検証対象のDocument。
        merged (list[dict[str, str]]): 統合先または統合済みのDocument要素。

    Returns:
        dict[str, Any]: 消費元だけを除去して全構造参照を再採番し、reportに出力側IDを残す。
    """

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
    """セル範囲と宣言寸法を検査し、不整合や重なるセルを結合対象から外す。

    Args:
        data (dict[str, Any]): 行数または列数を取得するTable Data。
        key (str): Data内で行数または列数を保持するKey。

    Returns:
        tuple[int, int] | None: セル範囲と宣言寸法を検査し、不整合や重なるセルを結合対象から外す。
    """

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
    """同一ページで近接し列数が一致する表を、セル行位置と参照を補正して先頭の表へ結合する。

    Args:
        first (dict[str, Any]): 結合先となる先行Table Fragment。
        second (dict[str, Any]): 結合可否を判定する後続Table Fragment。

    Returns:
        bool: 同一ページで近接し列数が一致する表を、セル行位置と参照を補正して先頭の表へ結合する。
    """

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


class PositionTask:
    """対象文書と診断・走査状態を保持し、読み順補正と断片結合を実行する。"""

    def __init__(self, source: dict[str, Any], pdf_source: Path | None = None) -> None:
        """変更前の文書を保持し、処理時には複製を補正する。

        Args:
            source: 座標と参照を持つDocling文書。元の値は変更しない。
            pdf_source: 見出しの行境界を照合する原本PDF。省略時は分割しない。
        """
        self.source = source
        self.pdf_source = pdf_source

    def run(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """文書を補正し、順序変更・結合・警告の記録を返す。

        Returns:
            補正済みDocling文書と診断JSON用の辞書。
        """
        self.document = copy.deepcopy(self.source)
        self.changed: list[dict[str, Any]] = []
        self.merged: list[dict[str, str]] = []
        self.warnings: list[dict[str, str]] = []
        self.split_headings: list[str] = []
        self.merge_visited: set[int] = set()
        self.unsafe = self._unsafe_merge_refs()
        if self.pdf_source is not None:
            with pdfium.PdfDocument(self.pdf_source) as pdf:
                self._split_headings(pdf)
        self._sort_children(self.document.get("body", {}))
        self._merge_fragments(self.document.get("body", {}))
        self.document = _compact_fragments(self.document, self.merged)
        return self.document, {
            "reordered": self.changed,
            "merged": self.merged,
            "warnings": self.warnings,
            "split_headings": self.split_headings,
        }

    def _split_headings(self, pdf: pdfium.PdfDocument) -> None:
        """PDF上で確認できた番号付き見出しの行を、独立した要素へ戻す。

        Args:
            pdf: Docling文書と同じ原本PDF。
        """
        texts = self.document.get("texts", [])
        for item in list(texts):
            ref = item.get("self_ref", "")
            parent = self._resolve(item.get("parent", {}).get("$ref", ""))
            if (
                item.get("label") != "section_header"
                or item.get("children")
                or ref in self.unsafe
                or re.fullmatch(r"#/texts/(?:0|[1-9][0-9]*)", ref) is None
                or self._resolve(ref) is not item
                or parent is None
                or {"$ref": ref} not in parent.get("children", [])
                or len(item.get("prov", [])) != 1
                or _geometry(item) is None
            ):
                continue
            lines = self._heading_lines(item, pdf)
            if not lines:
                continue
            refs = []
            for index, (line, box, level) in enumerate(lines):
                part = copy.deepcopy(item)
                part["text"] = line
                if "orig" in part:
                    part["orig"] = line
                part["level"] = level
                part["prov"][0].update(bbox=box, charspan=[0, len(line)])
                if index:
                    part["self_ref"] = f"#/texts/{len(texts)}"
                    texts.append(part)
                else:
                    texts[int(ref.rsplit("/", 1)[1])] = part
                refs.append({"$ref": part["self_ref"]})
            offset = parent["children"].index({"$ref": ref})
            parent["children"][offset : offset + 1] = refs
            self.split_headings.append(ref)

    def _heading_lines(
        self, item: dict[str, Any], pdf: pdfium.PdfDocument
    ) -> list[tuple[str, dict[str, Any], int]]:
        """原本の本文・番号・座標が一意に一致する複数行だけを返す。

        Args:
            item: 一ページのbboxを持つ見出し。
            pdf: 行境界と文字座標を読む原本PDF。

        Returns:
            各行の本文・BOTTOMLEFT座標・見出しlevel。不一致なら空配列。
        """
        prov = item["prov"][0]
        if not 1 <= prov["page_no"] <= len(pdf):
            return []
        with (
            closing(pdf[prov["page_no"] - 1]) as page,
            closing(page.get_textpage()) as text,
        ):
            box = prov["bbox"]
            left, right = sorted((box["l"], box["r"]))
            top, bottom = box["t"], box["b"]
            if str(box.get("coord_origin", "BOTTOMLEFT")).upper() == "TOPLEFT":
                top, bottom = page.get_height() - top, page.get_height() - bottom
            top, bottom = max(top, bottom), min(top, bottom)
            lines = [
                line.strip()
                for line in text.get_text_bounded(left, bottom, right, top).splitlines()
                if line.strip()
            ]
            numbers = [
                re.match(r"^([0-9]{1,3}(?:\.[0-9]+)*)[.)、\uFF1A:]?\s+", line)
                for line in lines
            ]
            if (
                len(lines) < 2
                or len({match[1] for match in numbers if match}) != len(lines)
                or " ".join(" ".join(lines).split())
                != " ".join(item.get("text", "").split())
                or " ".join(item.get("orig", item["text"]).split())
                != " ".join(item["text"].split())
            ):
                return []
            result = []
            for line, number in zip(lines, numbers, strict=True):
                if number is None:
                    return []
                boxes = []
                with closing(text.search(line, match_case=True)) as search:
                    while found := search.get_next():
                        rectangles = [
                            text.get_rect(i) for i in range(text.count_rects(*found))
                        ]
                        if not rectangles:
                            continue
                        line_left = min(rect[0] for rect in rectangles)
                        line_bottom = min(rect[1] for rect in rectangles)
                        line_right = max(rect[2] for rect in rectangles)
                        line_top = max(rect[3] for rect in rectangles)
                        # DoclingとPDFiumのglyph境界の丸め差だけを1 pt以内で許容する。
                        if (
                            left - 1 <= line_left < line_right <= right + 1
                            and bottom - 1 <= line_bottom < line_top <= top + 1
                        ):
                            boxes.append(
                                {
                                    "l": line_left,
                                    "b": line_bottom,
                                    "r": line_right,
                                    "t": line_top,
                                    "coord_origin": "BOTTOMLEFT",
                                }
                            )
                if len(boxes) != 1 or (result and boxes[0]["t"] > result[-1][1]["b"]):
                    return []
                result.append((line, boxes[0], min(number[1].count(".") + 1, 6)))
            return result

    def _resolve(self, ref: str) -> dict[str, Any] | None:
        """Doclingの文書内参照を辞書へ解決し、参照不正や辞書以外の値ではNoneを返す。

        Args:
            ref (str): Docling要素を指すJSON参照。

        Returns:
            dict[str, Any] | None: Doclingの文書内参照を辞書へ解決し、参照不正や辞書以外の値ではNoneを返す。
        """

        value: Any = self.document
        try:
            for part in ref.removeprefix("#/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _unsafe_merge_refs(self) -> set[str]:
        """所有childrenとセルparentの逆参照を区別し、共有・外部参照のある候補を除く。

        Returns:
            set[str]: 所有childrenとセルparentの逆参照を区別し、共有・外部参照のある候補を除く。
        """

        incoming: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        pending: list[tuple[Any, tuple[str, ...]]] = [(self.document, ())]
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
        self.unsafe: set[str] = set()
        for ref, paths in incoming.items():
            parts = ref.removeprefix("#/").split("/")
            if len(parts) > 2:
                # Nested cell references cannot be transferred by collection reindexing alone.
                self.unsafe.add("#/" + "/".join(parts[:2]))
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
                self.unsafe.add(ref)
        return self.unsafe

    def _merge_fragments(self, node: Any) -> None:
        """キー・値領域の本文は同行だけを結合し、他の本文・表は縦の連続性から結合する。

        Args:
            node (Any): 再帰的に走査または並べ替えるNode。
        """

        if not isinstance(node, dict) or not isinstance(node.get("children"), list):
            return
        if id(node) in self.merge_visited:
            return
        self.merge_visited.add(id(node))
        children = node["children"]
        index = 0
        while index + 1 < len(children):
            first_ref = (
                children[index].get("$ref")
                if isinstance(children[index], dict)
                else None
            )
            second_ref = (
                children[index + 1].get("$ref")
                if isinstance(children[index + 1], dict)
                else None
            )
            first = self._resolve(first_ref) if isinstance(first_ref, str) else None
            second = self._resolve(second_ref) if isinstance(second_ref, str) else None
            table_pair = (
                first is not None
                and second is not None
                and first.get("label") == second.get("label") == "table"
            )
            text_pair = (
                first is not None
                and second is not None
                and _continuous(
                    first, second, same_line=node.get("label") == "key_value_area"
                )
            )
            collection = "tables" if table_pair else "texts"
            if (table_pair or text_pair) and (
                first_ref == second_ref
                or first_ref in self.unsafe
                or second_ref in self.unsafe
                or first.get("self_ref") != first_ref
                or second.get("self_ref") != second_ref
                or any(
                    re.fullmatch(rf"#/{collection}/(?:0|[1-9][0-9]*)", str(ref)) is None
                    for ref in (first_ref, second_ref)
                )
                or not _merge_metadata_safe(first, second)
            ):
                self.warnings.append(
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
                    self.merged.append(
                        {
                            "into": str(first_ref),
                            "from": str(second_ref),
                            "reason": "table rows and spans reconstructed",
                        }
                    )
                    continue
                self.warnings.append(
                    {
                        "first": str(first_ref),
                        "second": str(second_ref),
                        "reason": "ambiguous table fragments kept separate",
                    }
                )
                index += 1
                continue
            if first is not None and second is not None and text_pair:
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
                self.merged.append({"into": str(first_ref), "from": str(second_ref)})
                continue
            index += 1
        for child in children:
            ref = child.get("$ref") if isinstance(child, dict) else None
            target = self._resolve(ref) if isinstance(ref, str) else None
            if target is not None:
                self._merge_fragments(target)

    def _reading_order(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """座標のある要素をページ・段組・領域ごとに並べ、座標のない要素は元の順で末尾へ残す。

        Args:
            children (list[dict[str, Any]]): 読み順を決定する子要素列。

        Returns:
            list[dict[str, Any]]: 座標のある要素をページ・段組・領域ごとに並べ、座標のない要素は元の順で末尾へ残す。
        """

        positioned: dict[
            int, list[tuple[int, dict[str, Any], dict[str, Any], tuple[float, ...]]]
        ] = {}
        unpositioned: list[tuple[int, dict[str, Any]]] = []
        for index, child in enumerate(children):
            ref = child.get("$ref")
            item = self._resolve(ref) if isinstance(ref, str) else None
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
            # Merges preserve provenance: count every same-page box, including equal boxes,
            # so neither the median width nor the left-edge candidates lose samples.
            samples = [
                geometry
                for _index, _child, item, _representative in entries
                if item.get("label") not in {"page_header", "page_footer", "footnote"}
                for provenance in item["prov"]
                if (geometry := _geometry({"prov": [provenance]})) is not None
                and geometry[0] == page
            ]
            widths = [max(1.0, geometry[2] - geometry[1]) for geometry in samples]
            tolerance = statistics.median(widths or [1.0]) * 0.6
            columns: list[float] = []
            for left in sorted(geometry[1] for geometry in samples):
                if not columns or abs(left - columns[-1]) > tolerance:
                    columns.append(left)
            columns = columns or [0.0]
            column_ranges: dict[float, tuple[float, float]] = {}
            for _page, left, _right, top, bottom in samples:
                column = min(columns, key=lambda position: abs(position - left))
                first, last = column_ranges.get(column, (top, bottom))
                column_ranges[column] = min(first, top), max(last, bottom)
            # 上下に重ならない中央見出しは別の段ではなく、本文より前の領域として読む。
            bands: list[tuple[float, float]] = []
            for top, bottom in sorted(column_ranges.values()):
                if bands and top <= bands[-1][1]:
                    bands[-1] = bands[-1][0], max(bands[-1][1], bottom)
                else:
                    bands.append((top, bottom))

            def order_key(
                entry: tuple[int, dict[str, Any], dict[str, Any], tuple[float, ...]],
                column_positions: tuple[float, ...] = tuple(columns),
                vertical_bands: tuple[tuple[float, float], ...] = tuple(bands),
            ) -> tuple[int, int, int, float, float, float, int]:
                """欄外種別、縦方向の領域、段、縦位置を比較し、同位置では元の順序を保つ。

                Args:
                    entry (tuple[int, dict[str, Any], dict[str, Any], tuple[float, ...]]): 読み順、要素、幾何情報を保持するSort対象。
                    column_positions (tuple[float, ...]): Table Cellを整列するColumn境界。
                    vertical_bands: 縦方向に重なる段をまとめた領域。

                Returns:
                    tuple: 欄外種別、領域、段、座標、元の順序を比較するkey。
                """

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
                band = sum(end < top for _start, end in vertical_bands)
                return region, band, column, top, center, left, index

            ordered.extend(entry[1] for entry in sorted(entries, key=order_key))
        ordered.extend(child for _, child in sorted(unpositioned))
        return ordered

    def _sort_children(self, node: Any, visited: set[int] | None = None) -> None:
        """キー・値領域の順序を保ち、他の子要素の並べ替えをreportへ記録する。

        Args:
            node (Any): 再帰的に走査または並べ替えるNode。
            visited (set[int] | None): 再帰走査済みNodeの識別集合。
        """

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
        # 項目名と値を段組として並べ替えると、行ごとの対応が失われる。
        children[:] = (
            typed_children
            if node.get("label") == "key_value_area"
            else self._reading_order(typed_children)
        )
        after = [child.get("$ref") for child in children if isinstance(child, dict)]
        if before != after:
            self.changed.append(
                {
                    "container": str(node.get("self_ref", "#/body")),
                    "before": before,
                    "after": after,
                    "reason": "multi-column stable reading order",
                }
            )
        for child in children:
            ref = child.get("$ref") if isinstance(child, dict) else None
            target = self._resolve(ref) if isinstance(ref, str) else None
            if target is not None:
                self._sort_children(target, visited)


def position(source: Path, output_dir: Path, pdf_source: Path | None = None) -> Path:
    """読み順を補正してJSONとreportを原子的に保存する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        output_dir (Path): Task成果物の出力Directory。
        pdf_source: 見出しの行境界を照合する原本PDF。省略時は分割しない。

    Returns:
        Path: 読み順を補正してJSONとreportを原子的に保存する。
    """

    document, report = PositionTask(
        json.loads(source.read_text(encoding="utf-8")), pdf_source
    ).run()
    with temporary_task_directory(output_dir) as temporary:
        write_json(temporary / "document.json", document, atomic=False)
        write_json(
            temporary / "report.json",
            report,
            atomic=False,
        )
    return output_dir / "document.json"
