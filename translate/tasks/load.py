"""LOAD: Docling Schema JSONをInternal Documentへ変換する。"""

from __future__ import annotations

import json
import math
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from translate.common.workspace import atomic_directory, atomic_write_text
from translate.document import (
    Block,
    BlockKind,
    CellImage,
    Document,
    Inline,
    InlineKind,
    InlineMark,
    Page,
    TableCell,
    inline_text,
)
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

COLLECTIONS = ("texts", "tables", "pictures", "key_value_items", "form_items", "groups")
SKIPPED_LABELS = {"page_header", "page_footer", "document_index"}
INDEX_TITLE_RE = re.compile(
    r"^(?:table of contents|contents|list of figures|list of tables|"
    r"目次|図目次|表目次)$",
    re.IGNORECASE,
)
TEXT_KINDS = {
    "title": "heading",
    "section_header": "heading",
    "heading": "heading",
    "header": "heading",
    "paragraph": "paragraph",
    "text": "paragraph",
    "list_item": "list_item",
    "checkbox_selected": "list_item",
    "checkbox_unselected": "list_item",
    "caption": "paragraph",
    "footnote": "footnote",
    "code": "code",
    "program_listing": "code",
    "formula": "formula",
}


def _resolve(document: dict[str, Any], ref: str) -> dict[str, Any]:
    """Docling内部refをobjectへ解決する。

    Args:
        document: Docling document。
        ref: `#/collection/index`形式の参照。

    Returns:
        参照先object。

    Raises:
        ValueError: 参照が不正または解決不能の場合。
    """

    value: Any = document
    try:
        for part in ref.removeprefix("#/").split("/"):
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        msg = f"unresolved Docling ref: {ref}"
        raise ValueError(msg) from error
    if not isinstance(value, dict):
        msg = f"Docling ref is not an object: {ref}"
        raise ValueError(msg)
    return value


def _walk_refs(
    document: dict[str, Any],
    value: Any,
    list_level: int = 0,
    ordered: bool | None = None,
) -> Iterator[tuple[dict[str, Any], int, bool | None]]:
    """tree内refを文書順に展開する。

    Args:
        document: Docling document。
        value: tree nodeまたは値。

    Yields:
        可視内容のない親を平坦化した参照先要素、親list階層、順序付きかどうかの組。
    """

    if isinstance(value, list):
        for child in value:
            yield from _walk_refs(document, child, list_level, ordered)
        return
    if not isinstance(value, dict):
        return
    ref = value.get("$ref")
    target = _resolve(document, ref) if isinstance(ref, str) else value
    label = str(target.get("label", ""))
    children = target.get("children", [])
    # groupは配置情報だけなので平坦化するが、可視内容を持つ親は子より先に残す。
    if children and not _visible_content(target):
        nested_level = (
            list_level + 1 if label in {"list", "ordered_list"} else list_level
        )
        nested_ordered = (
            label == "ordered_list" if label in {"list", "ordered_list"} else ordered
        )
        yield from _walk_refs(document, children, nested_level, nested_ordered)
    elif isinstance(ref, str):
        yield target, list_level, ordered
        if children:
            yield from _walk_refs(document, children, list_level, ordered)
    else:
        yield from _walk_refs(document, children, list_level, ordered)


def _visible_content(item: dict[str, Any]) -> bool:
    """要素自身が失うべきでない可視内容を持つか判定する。

    Args:
        item: Docling要素。

    Returns:
        text、画像、表dataまたは数式が存在する場合はTrue。
    """

    text = item.get("text")
    return bool(
        (isinstance(text, str) and text.strip())
        or item.get("image")
        or item.get("data")
        or item.get("latex")
    )


def _page_number(item: dict[str, Any]) -> int:
    """provenanceから1始まりページ番号を得る。

    Args:
        item: Docling要素。

    Returns:
        ページ番号。情報がない場合は1。
    """

    provenance = item.get("prov")
    if isinstance(provenance, list) and provenance and isinstance(provenance[0], dict):
        value = provenance[0].get("page_no", 1)
        if isinstance(value, int) and value > 0:
            return value
    return 1


def _bbox(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """provenanceのbboxを数値tupleへ変換する。

    Args:
        item: Docling要素。

    Returns:
        left、top、right、bottom。利用不能ならNone。
    """

    provenance = item.get("prov")
    if (
        not isinstance(provenance, list)
        or not provenance
        or not isinstance(provenance[0], dict)
    ):
        return None
    box = provenance[0].get("bbox")
    if not isinstance(box, dict):
        return None
    try:
        return (
            float(box["l"]),
            float(box["t"]),
            float(box["r"]),
            float(box["b"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _inline(
    ref: str,
    text: str,
    kind: InlineKind = "text",
    href: str | None = None,
    marks: list[InlineMark] | None = None,
) -> list[Inline]:
    """Docling文字列を一つのInline列へ変換する。

    Args:
        ref: 安定IDのprefix。
        text: 可視文字列。
        kind: Inline種別。
        href: link URL。
        marks: Inline装飾。

    Returns:
        空文字なら空、それ以外は一要素のInline列。
    """

    if not text:
        return []
    return [
        Inline(
            id=f"{ref}/inline/0",
            text=text,
            kind=kind,
            href=href,
            marks=marks or [],
        )
    ]


def _inline_from_item(
    item: dict[str, Any], ref: str, text: str, kind: InlineKind
) -> list[Inline]:
    """Docling TextItemのlinkと装飾をInlineへ移す。

    Args:
        item: Docling TextItem。
        ref: 安定IDのprefix。
        text: 可視文字列。
        kind: 基本Inline種別。

    Returns:
        hyperlinkとFormattingを保持したInline列。
    """

    formatting = item.get("formatting")
    marks: list[InlineMark] = []
    if isinstance(formatting, dict):
        mark_fields: tuple[tuple[str, InlineMark], ...] = (
            ("bold", "strong"),
            ("italic", "emphasis"),
            ("strikethrough", "strikethrough"),
            ("underline", "underline"),
        )
        marks.extend(mark for field, mark in mark_fields if formatting.get(field))
        script = formatting.get("script")
        if script == "sub":
            marks.append("subscript")
        elif script == "super":
            marks.append("superscript")
    hyperlink = item.get("hyperlink")
    href = str(hyperlink) if hyperlink is not None else None
    inline_kind: InlineKind = "link" if href and kind == "text" else kind
    return _inline(ref, text, inline_kind, href, marks)


def _caption_inlines(
    document: dict[str, Any], item: dict[str, Any], ref: str
) -> list[Inline]:
    """Doclingの新旧caption表現をInline列へ変換する。

    Args:
        document: ref解決元のDocling document。
        item: TableItemまたはPictureItem。
        ref: caption IDのprefix。

    Returns:
        参照先の装飾も保持したcaption Inline列。
    """

    raw = item.get("captions")
    if not raw:
        raw = item.get("caption") or item.get("title") or []
    values = raw if isinstance(raw, list) else [raw]
    result: list[Inline] = []
    for index, value in enumerate(values):
        caption_item: dict[str, Any] | None = None
        if isinstance(value, dict):
            nested_ref = value.get("$ref")
            caption_item = (
                _resolve(document, nested_ref) if isinstance(nested_ref, str) else value
            )
        if caption_item is not None:
            text = str(caption_item.get("text") or "")
            result.extend(
                _inline_from_item(caption_item, f"{ref}/caption/{index}", text, "text")
            )
        elif isinstance(value, str):
            result.extend(_inline(f"{ref}/caption/{index}", value))
    return result


def _owned_caption_refs(document: dict[str, Any]) -> set[str]:
    """図表Blockへ内包するcaption TextItemのrefを集める。

    Args:
        document: Docling document。

    Returns:
        standalone本文として重複出力しないcaption ref集合。
    """

    # captionは図表Blockへ所有させ、body側TextItemとの二重出力を防ぐ。
    refs: set[str] = set()
    for collection in ("tables", "pictures"):
        for item in document.get(collection, []):
            if not isinstance(item, dict):
                continue
            raw = item.get("captions") or item.get("caption") or []
            values = raw if isinstance(raw, list) else [raw]
            refs.update(
                str(value["$ref"])
                for value in values
                if isinstance(value, dict) and isinstance(value.get("$ref"), str)
            )
    return refs


def _index_pages(document: dict[str, Any]) -> set[int]:
    """元文書の目次類として本文から除くページを特定する。

    Args:
        document: Docling document。

    Returns:
        document index labelまたは既知の目次見出しを持つページ番号集合。
    """

    return {
        _page_number(item)
        for collection in COLLECTIONS
        for item in document.get(collection, [])
        if isinstance(item, dict)
        and (
            item.get("label") == "document_index"
            or (
                item.get("label") in {"title", "section_header", "heading", "header"}
                and INDEX_TITLE_RE.fullmatch(str(item.get("text") or "").strip())
            )
        )
    }


def _picture_content_refs(document: dict[str, Any]) -> set[str]:
    """picture配下でcaptionではない重複textのrefを集める。

    Args:
        document: Docling document。

    Returns:
        Figure asset側に任せて本文出力しないtext ref集合。
    """

    parents: dict[str, str] = {}
    picture_refs = {
        str(item.get("self_ref"))
        for item in document.get("pictures", [])
        if isinstance(item, dict) and item.get("self_ref")
    }
    for collection in COLLECTIONS:
        for item in document.get(collection, []):
            if not isinstance(item, dict) or not item.get("self_ref"):
                continue
            parent = item.get("parent")
            if isinstance(parent, dict) and isinstance(parent.get("$ref"), str):
                parents[str(item["self_ref"])] = str(parent["$ref"])
    # 親chainを辿るのは、picture直下にgroupを挟むDocling出力にも対応するため。
    result: set[str] = set()
    for item in document.get("texts", []):
        if (
            not isinstance(item, dict)
            or item.get("label") == "caption"
            or not item.get("self_ref")
        ):
            continue
        ref = str(item["self_ref"])
        parent = parents.get(ref, "")
        visited: set[str] = set()
        while parent and parent not in visited:
            if parent in picture_refs:
                result.add(ref)
                break
            visited.add(parent)
            parent = parents.get(parent, "")
    return result


def _cell_text(cell: dict[str, Any]) -> str:
    """Docling table cellから文字列を得る。

    Args:
        cell: table cell object。

    Returns:
        textまたは空文字列。
    """

    value = cell.get("text") or cell.get("text_content") or ""
    return str(value)


@dataclass
class _CellSource:
    """LOAD呼出中だけ、論理セルとDoclingの別表現・参照根拠を対応させる。"""

    cell: TableCell
    variants: list[dict[str, Any]] = field(default_factory=list)
    refs: set[str] = field(default_factory=set)


class TableImageOwnershipError(ValueError):
    """本文やasset pathを公開せず、所属失敗の対象だけを診断へ渡す。"""

    def __init__(self, page: int | None, ref: str) -> None:
        """検証済み形式のDocling IDとページを保持し、任意文字列IDを公開しない。"""

        self.page = page
        self.target_id = (
            ref if re.fullmatch(r"#/(?:tables|pictures)/[0-9]+", ref) else "unknown"
        )
        self.cause_type = "TableImageOwnership"
        super().__init__(
            f"table image ownership validation failed: page={page} target={self.target_id}"
        )


@contextmanager
def _ownership_context(page: int | None, ref: str) -> Iterator[None]:
    """所属検証の詳細例外を、内容を含まない対象付き診断へ正規化する。"""

    try:
        yield
    except ValueError as error:
        raise TableImageOwnershipError(page, ref) from error


def _cell_shape(
    raw: dict[str, Any], row: int, column: int
) -> tuple[int, int, int, int]:
    """半開offsetとspanを照合し、負位置や矛盾を丸めずに拒否する。"""

    start_row = raw.get("start_row_offset_idx", raw.get("row", row))
    start_col = raw.get("start_col_offset_idx", raw.get("col", column))
    if any(type(value) is not int or value < 0 for value in (start_row, start_col)):
        raise ValueError("invalid table cell position")
    row_span, col_span = raw.get("row_span", 1), raw.get("col_span", 1)
    if any(type(value) is not int or value < 1 for value in (row_span, col_span)):
        raise ValueError("invalid table cell span")
    end_row = raw.get("end_row_offset_idx", start_row + row_span)
    end_col = raw.get("end_col_offset_idx", start_col + col_span)
    if (
        any(type(value) is not int for value in (end_row, end_col))
        or end_row <= start_row
        or end_col <= start_col
        or ("row_span" in raw and end_row - start_row != row_span)
        or ("col_span" in raw and end_col - start_col != col_span)
    ):
        raise ValueError("conflicting table cell span")
    return start_row, start_col, end_row - start_row, end_col - start_col


def _raw_cells(
    data: dict[str, Any], ref: str
) -> Iterator[tuple[dict[str, Any], int, int, str, str]]:
    """gridとoffset配列の実在セルを、その参照pathと既存Inline ID付きで列挙する。"""

    grid = data.get("grid")
    if isinstance(grid, list):
        for row_index, row in enumerate(grid):
            if not isinstance(row, list):
                raise ValueError("invalid table grid row")
            for column_index, raw in enumerate(row):
                if not isinstance(raw, dict):
                    raise ValueError("invalid table grid cell")
                yield (
                    raw,
                    row_index,
                    column_index,
                    f"{ref}/data/grid/{row_index}/{column_index}",
                    f"{ref}/cell/{row_index}/{column_index}",
                )
    has_cells = isinstance(grid, list)
    for name in ("table_cells", "cells"):
        values = data.get(name)
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValueError("invalid table cells")
        has_cells = True
        for index, raw in enumerate(values):
            if not isinstance(raw, dict):
                raise ValueError("invalid table cell")
            yield raw, 0, 0, f"{ref}/data/{name}/{index}", f"{ref}/cell/{index}"
    if not has_cells:
        raise ValueError("unsupported Docling table cells")


def _normalized_cells(item: dict[str, Any], ref: str) -> list[_CellSource]:
    """同一論理セルの別表現を統合し、span・内容・占有領域の矛盾を拒否する。"""

    data = item.get("data")
    if not isinstance(data, dict):
        raise ValueError("unsupported Docling table")
    cells: dict[tuple[int, int], _CellSource] = {}
    occupied: dict[tuple[int, int], tuple[int, int]] = {}
    for raw, row, column, path, inline_ref in _raw_cells(data, ref):
        start_row, start_col, rowspan, colspan = _cell_shape(raw, row, column)
        key = (start_row, start_col)
        for size, end in (
            (data.get("num_rows"), start_row + rowspan),
            (data.get("num_cols"), start_col + colspan),
        ):
            if size is not None and (type(size) is not int or size < end):
                raise ValueError("table cell exceeds table dimensions")
        cell = TableCell(
            row=start_row,
            column=start_col,
            rowspan=rowspan,
            colspan=colspan,
            header=bool(raw.get("column_header") or raw.get("row_header")),
            source=_inline(inline_ref, _cell_text(raw)),
        )
        if key in cells:
            previous = cells[key].cell
            if (
                previous.rowspan,
                previous.colspan,
                previous.header,
                inline_text(previous.source),
            ) != (rowspan, colspan, cell.header, inline_text(cell.source)):
                raise ValueError("conflicting table cell representations")
            previous_raw = cells[key].variants[0]
            if any(
                bool(previous_raw.get(name)) != bool(raw.get(name))
                for name in ("row_header", "column_header")
            ):
                raise ValueError("conflicting table cell header roles")
        else:
            cells[key] = _CellSource(cell)
        if "/data/grid/" in path and not (
            start_row <= row < start_row + rowspan
            and start_col <= column < start_col + colspan
        ):
            raise ValueError("grid cell lies outside its span")
        for r in range(start_row, start_row + rowspan):
            for c in range(start_col, start_col + colspan):
                if (r, c) in occupied and occupied[r, c] != key:
                    raise ValueError("overlapping table cell spans")
                occupied[r, c] = key
        cells[key].variants.append(raw)
        cells[key].refs.add(path)
        if isinstance(raw.get("self_ref"), str):
            cells[key].refs.add(raw["self_ref"])
    return list(cells.values())


def _table_cells(item: dict[str, Any], ref: str) -> list[TableCell]:
    """別表現の重複を除いた論理セルを内部文書へ渡す。"""

    with _ownership_context(_page_number(item), ref):
        return [source.cell for source in _normalized_cells(item, ref)]


def _top_left_box(raw: Any, page: Page) -> tuple[float, float, float, float] | None:
    """存在するbboxは有限の正領域として検査し、ページ高さで原点を統一する。"""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("invalid image ownership geometry")
    try:
        left, top, right, bottom = (float(raw[key]) for key in ("l", "t", "r", "b"))
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("invalid image ownership geometry") from error
    if raw.get("coord_origin") == "BOTTOMLEFT":
        if page.height is None or not math.isfinite(page.height) or page.height <= 0:
            raise ValueError("missing page height for image ownership")
        top, bottom = page.height - top, page.height - bottom
    elif raw.get("coord_origin") != "TOPLEFT":
        raise ValueError("unknown image ownership coordinate origin")
    if (
        not all(math.isfinite(value) for value in (left, top, right, bottom))
        or left >= right
        or top >= bottom
    ):
        raise ValueError("invalid image ownership geometry")
    return left, top, right, bottom


def _item_box(
    item: dict[str, Any], page: Page
) -> tuple[float, float, float, float] | None:
    """所有関係を判断する同ページのprovenanceだけを取得し、矛盾を拒否する。"""

    provenance = item.get("prov") or []
    boxes = {
        _top_left_box(value.get("bbox"), page)
        for value in provenance
        if isinstance(value, dict) and value.get("page_no") == page.number
    }
    boxes.discard(None)
    if len(boxes) > 1:
        raise ValueError("conflicting image ownership provenance")
    return next(iter(boxes), None)


def _contains(
    outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]
) -> bool:
    """距離閾値を使わず矩形全体の包含を判定する。"""

    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _cell_box(
    raw: dict[str, Any], page: Page
) -> tuple[float, float, float, float] | None:
    """セル側ページ指定とbbox/provenanceの整合を検査して座標を返す。"""

    if ("page_no" in raw and raw["page_no"] != page.number) or any(
        not isinstance(value, dict) or value.get("page_no") != page.number
        for value in raw.get("prov", []) or []
    ):
        raise ValueError("cell ownership references another page")
    box = _top_left_box(raw.get("bbox"), page)
    provenance = _item_box(raw, page)
    if box is not None and provenance is not None and box != provenance:
        raise ValueError("conflicting cell ownership provenance")
    return box or provenance


def _geometric_cell(
    cells: list[_CellSource], box: tuple[float, float, float, float], page: Page
) -> set[int]:
    """セルbbox包含と行列見出しの一意交差を照合し、結合セル起点へ正規化する。"""

    direct: set[int] = set()
    rows: set[int] = set()
    columns: set[int] = set()
    center_x, center_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for index, source in enumerate(cells):
        cell = source.cell
        boxes = {_cell_box(raw, page) for raw in source.variants}
        boxes.discard(None)
        if len(boxes) > 1:
            raise ValueError("conflicting cell ownership geometry")
        cell_box = next(iter(boxes), None)
        if cell_box is None:
            continue
        if _contains(cell_box, box):
            direct.add(index)
        if (
            any(raw.get("column_header") for raw in source.variants)
            and cell_box[0] < center_x < cell_box[2]
        ):
            columns.update(range(cell.column, cell.column + cell.colspan))
        if (
            any(raw.get("row_header") for raw in source.variants)
            and cell_box[1] < center_y < cell_box[3]
        ):
            rows.update(range(cell.row, cell.row + cell.rowspan))
    intersections = {
        index
        for index, source in enumerate(cells)
        if any(
            source.cell.row <= row < source.cell.row + source.cell.rowspan
            and source.cell.column <= column < source.cell.column + source.cell.colspan
            for row in rows
            for column in columns
        )
    }
    if (
        len(direct) > 1
        or len(intersections) > 1
        or (direct and intersections and direct != intersections)
    ):
        raise ValueError("ambiguous table image cell")
    return direct or intersections


def _explicit_image_owners(
    sources: dict[str, list[_CellSource]], pictures: dict[str, dict[str, Any]]
) -> dict[str, set[tuple[str, int]]]:
    """セル側参照と画像の親参照を統合し、不正セル参照を幾何推測で隠さない。"""

    owners: dict[str, set[tuple[str, int]]] = {}
    refs: dict[str, set[tuple[str, int]]] = {}
    for table_ref, cells in sources.items():
        for index, source in enumerate(cells):
            owner = (table_ref, index)
            for ref in source.refs:
                refs.setdefault(ref, set()).add(owner)
            for raw in source.variants:
                children = raw.get("children", [])
                if not isinstance(children, list):
                    raise TableImageOwnershipError(None, table_ref)
                for value in children:
                    ref = value.get("$ref") if isinstance(value, dict) else None
                    if not isinstance(ref, str):
                        raise TableImageOwnershipError(None, table_ref)
                    if isinstance(ref, str) and ref.startswith("#/pictures/"):
                        if ref not in pictures:
                            raise TableImageOwnershipError(None, table_ref)
                        owners.setdefault(ref, set()).add(owner)
    for picture_ref, picture in pictures.items():
        parent = picture.get("parent")
        parent_ref = parent.get("$ref") if isinstance(parent, dict) else None
        if parent is not None and not isinstance(parent_ref, str):
            raise TableImageOwnershipError(_page_number(picture), picture_ref)
        if parent_ref in refs:
            owners.setdefault(picture_ref, set()).update(refs[parent_ref])
        elif (
            isinstance(parent_ref, str)
            and parent_ref.startswith("#/tables/")
            and parent_ref not in sources
        ):
            raise TableImageOwnershipError(_page_number(picture), picture_ref)
    for ref, value in owners.items():
        if len(value) != 1:
            raise TableImageOwnershipError(_page_number(pictures[ref]), ref)
    return owners


def _assign_cell_images(document: dict[str, Any], pages: dict[int, Page]) -> None:
    """一意に確定した画像だけを表セルへ移し、body/collection由来の独立図を除く。"""

    tables = {
        str(item.get("self_ref")): item
        for item in document.get("tables", [])
        if isinstance(item, dict)
    }
    pictures = {
        str(item.get("self_ref")): item
        for item in document.get("pictures", [])
        if isinstance(item, dict)
    }
    sources = {ref: _normalized_cells(item, ref) for ref, item in tables.items()}
    explicit = _explicit_image_owners(sources, pictures)
    for page in pages.values():
        page_tables = {
            block.id: block for block in page.blocks if block.kind == "table"
        }
        consumed: set[str] = set()
        for figure in (block for block in page.blocks if block.kind == "figure"):
            declared = explicit.get(figure.id, set())
            if not page_tables and not declared:
                continue
            picture = pictures[figure.id]
            parent = picture.get("parent")
            parent_ref = parent.get("$ref") if isinstance(parent, dict) else None
            declared_ref = next(iter(declared))[0] if declared else None
            if declared_ref is not None and declared_ref not in page_tables:
                raise TableImageOwnershipError(page.number, figure.id)
            with _ownership_context(page.number, figure.id):
                box = _item_box(picture, page)
            if box is None:
                raise TableImageOwnershipError(page.number, figure.id)
            containing = []
            for ref in page_tables:
                with _ownership_context(page.number, ref):
                    table_box = _item_box(tables[ref], page)
                if table_box is None:
                    if declared_ref is None:
                        raise TableImageOwnershipError(page.number, ref)
                    if ref == declared_ref:
                        containing.append(ref)
                    continue
                if _contains(table_box, box):
                    containing.append(ref)
                elif max(table_box[0], box[0]) < min(table_box[2], box[2]) and max(
                    table_box[1], box[1]
                ) < min(table_box[3], box[3]):
                    raise TableImageOwnershipError(page.number, figure.id)
            if len(containing) > 1:
                raise TableImageOwnershipError(page.number, figure.id)
            if parent_ref in sources and containing != [parent_ref]:
                raise TableImageOwnershipError(page.number, figure.id)
            if not containing:
                if declared:
                    raise TableImageOwnershipError(page.number, figure.id)
                continue
            ref = containing[0]
            with _ownership_context(page.number, figure.id):
                candidates = _geometric_cell(sources[ref], box, page)
            if declared:
                declared_ref, index = next(iter(declared))
                if declared_ref != ref or (candidates and candidates != {index}):
                    raise TableImageOwnershipError(page.number, figure.id)
                for raw in sources[ref][index].variants:
                    with _ownership_context(page.number, figure.id):
                        cell_box = _cell_box(raw, page)
                    if cell_box is not None and not _contains(cell_box, box):
                        raise TableImageOwnershipError(page.number, figure.id)
            elif len(candidates) == 1:
                index = next(iter(candidates))
            else:
                raise TableImageOwnershipError(page.number, figure.id)
            sources[ref][index].cell.images.append(
                CellImage(
                    id=figure.id,
                    asset_path=figure.asset_path or "",
                    width_pt=box[2] - box[0],
                    height_pt=box[3] - box[1],
                    alt_text=figure.alt_text or "",
                    caption=figure.caption,
                )
            )
            consumed.add(figure.id)
        for ref, block in page_tables.items():
            block.cells = [source.cell for source in sources[ref]]
        page.blocks = [block for block in page.blocks if block.id not in consumed]
        for order, block in enumerate(page.blocks):
            block.order = order


def _block(
    document: dict[str, Any],
    item: dict[str, Any],
    order: int,
    list_level: int = 0,
    parent_ordered: bool | None = None,
) -> Block | None:
    """一つのDocling要素をBlockへ変換する。

    Args:
        document: ref解決元のDocling document。
        item: Docling要素。
        order: ページ内の文書順。
        list_level: 親ListGroupから得た1始まり階層。
        parent_ordered: 親ListGroupが順序付きかどうか。

    Returns:
        対応Block。仕様上除外する要素はNone。

    Raises:
        ValueError: 内容を持つ未知要素または欠損assetの場合。
    """

    ref = str(item.get("self_ref") or f"#/unknown/{order}")
    label = str(item.get("label", ""))
    if label in SKIPPED_LABELS:
        return None
    if label == "table":
        return Block(
            id=ref,
            order=order,
            kind="table",
            bbox=_bbox(item),
            caption=_caption_inlines(document, item, ref),
            cells=_table_cells(item, ref),
        )
    if label == "picture":
        image = item.get("image")
        uri = image.get("uri") if isinstance(image, dict) else None
        uri = uri or item.get("uri")
        if not isinstance(uri, str) or not uri:
            msg = f"picture asset is missing: ref={ref} label={label}"
            raise ValueError(msg)
        relative = uri.removeprefix("artifacts/").removeprefix("assets/")
        # MERGE publishes the contents of each structured/assets directory
        # under the run-level assets root; keep the Internal Document path
        # relative to that root so VALIDATE/Markdown resolve the same file.
        uri = f"assets/{relative}"
        caption = _caption_inlines(document, item, ref)
        return Block(
            id=ref,
            order=order,
            kind="figure",
            bbox=_bbox(item),
            asset_path=uri,
            alt_text=str(item.get("alt_text") or inline_text(caption)),
            caption=caption,
        )
    kind = TEXT_KINDS.get(label)
    if kind is None:
        if not _visible_content(item):
            return None
        # 内容のある未知要素をparagraphへ丸めると欠損に気付けないためfail-fastする。
        msg = f"unsupported content-bearing Docling element: ref={ref} label={label}"
        raise ValueError(msg)
    text = str(item.get("text") or item.get("latex") or "")
    inline_kind = "code" if kind in {"code", "formula"} else "text"
    level = item.get("level") if kind == "heading" else None
    checked = (
        True
        if label == "checkbox_selected"
        else False
        if label == "checkbox_unselected"
        else None
    )
    return Block(
        id=ref,
        order=order,
        kind=cast("BlockKind", kind),
        bbox=_bbox(item),
        source=_inline_from_item(item, ref, text, inline_kind),
        level=int(level)
        if isinstance(level, int)
        else 1
        if kind == "heading"
        else max(1, list_level)
        if kind == "list_item"
        else None,
        ordered=bool(item.get("enumerated"))
        if "enumerated" in item
        else bool(parent_ordered),
        checked=checked,
        language=str(item.get("language")) if item.get("language") else None,
    )


def _normalized_pages(document: dict[str, Any]) -> dict[int, Page]:
    """Docling page mapを検証して内部Page mapへ変換する。

    Args:
        document: Docling document。

    Returns:
        ページ番号をkeyとする内部Page map。
    """

    raw_pages = document.get("pages")
    if not isinstance(raw_pages, dict):
        msg = "Docling pages must be a non-empty object"
        raise ValueError(msg)
    if not raw_pages:
        origin = document.get("origin", {})
        mimetype = origin.get("mimetype") if isinstance(origin, dict) else None
        office_types = {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        if mimetype not in office_types:
            msg = "Docling pages must be a non-empty object"
            raise ValueError(msg)
        # Office文書はDoclingがpageを返さないため、全要素を仮想ページへ載せる。
        raw_pages = {"1": {}}
    pages: dict[int, Page] = {}
    for raw_number, raw_page in raw_pages.items():
        number = int(raw_number)
        size = raw_page.get("size", {}) if isinstance(raw_page, dict) else {}
        pages[number] = Page(
            number=number,
            width=float(size["width"])
            if isinstance(size, dict) and "width" in size
            else None,
            height=float(size["height"])
            if isinstance(size, dict) and "height" in size
            else None,
        )
    return pages


def load_document(document: dict[str, Any]) -> Document:
    """Docling documentをページ順のv5 Documentへ変換する。

    Args:
        document: Docling Serveが返したJSON object。

    Returns:
        正規化済みDocument。

    Raises:
        ValueError: schema、ページ、参照、要素が契約を満たさない場合。
    """

    if document.get("schema_name") != "DoclingDocument":
        msg = f"unsupported Docling schema: {document.get('schema_name')!r}"
        raise ValueError(msg)
    pages = _normalized_pages(document)
    seen: set[str] = set()
    caption_refs = _owned_caption_refs(document)
    index_pages = _index_pages(document)
    picture_content_refs = _picture_content_refs(document)
    # bodyの文書順を正本とし、bodyに現れないcollection要素だけを後段で補完する。
    ordered_items = list(_walk_refs(document, document.get("body", {})))
    for collection in COLLECTIONS[:-1]:
        values = document.get(collection, [])
        if not isinstance(values, list):
            msg = f"Docling collection must be a list: {collection}"
            raise ValueError(msg)
        ordered_items.extend(
            (
                item,
                1
                if str(item.get("label", ""))
                in {"list_item", "checkbox_selected", "checkbox_unselected"}
                else 0,
                None,
            )
            for item in values
            if isinstance(item, dict)
        )
    page_orders: dict[int, int] = dict.fromkeys(pages, 0)
    for item, list_level, parent_ordered in ordered_items:
        ref = str(item.get("self_ref") or "")
        if ref in seen:
            continue
        seen.add(ref)
        if ref in caption_refs or ref in picture_content_refs:
            continue
        number = _page_number(item)
        if number not in pages:
            msg = f"Docling element references missing page: ref={ref} page={number}"
            raise ValueError(msg)
        if number in index_pages:
            continue
        block = _block(document, item, page_orders[number], list_level, parent_ordered)
        if block is not None:
            pages[number].blocks.append(block)
            page_orders[number] += 1
    _assign_cell_images(document, pages)
    return Document(pages=[pages[number] for number in sorted(pages)])


class LoadTask(BaseTask):
    """Execute LOAD while sharing elapsed-time measurement only."""

    name = "LOAD"

    def run(self, source: Path, output_dir: Path) -> Document:
        """JSONをInternal Documentへ変換して保存する。"""

        with self.measure():
            document = load_document(json.loads(source.read_text(encoding="utf-8")))
            with atomic_directory(output_dir) as temporary:
                atomic_write_text(
                    temporary / "document.json",
                    document.model_dump_json(indent=2) + "\n",
                )
            return document


def run(source: Path, output_dir: Path) -> Document:
    """Existing function delegates to the typed LoadTask operation."""

    return LoadTask().run(source, output_dir)
