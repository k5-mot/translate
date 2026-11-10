"""LOAD: Docling Schema JSONをInternal Documentへ変換する。"""

import json
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path, PurePath
from typing import Any, cast

from docling_core.types.doc import (
    BoundingBox,
    ContentLayer,
    CoordOrigin,
    DocItem,
    DoclingDocument,
    GroupItem,
    GroupLabel,
    ListItem,
    NodeItem,
    PictureItem,
    RichTableCell,
    Script,
    TableItem,
    TextItem,
)
from docling_core.types.doc import TableCell as DoclingCell
from pydantic import AnyUrl

from translate.adapters.artifact_store import temporary_task_directory, write_model
from translate.common.sentences import split_sentences
from translate.models.document import (
    Block,
    BlockKind,
    Document,
    Image,
    Page,
    TableCell,
    TextKind,
    TextMark,
    TextSpan,
    TextUnit,
)

index_refs = import_module("translate.tasks.11_normalize").index_refs

SKIPPED_LABELS = {"page_header", "page_footer"}
LIST_LABELS = {"list_item", "checkbox_selected", "checkbox_unselected"}
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
MARK_FIELDS: tuple[tuple[str, TextMark], ...] = (
    ("bold", "strong"),
    ("italic", "emphasis"),
    ("strikethrough", "strikethrough"),
    ("underline", "underline"),
)


def _label(item: NodeItem) -> str:
    """要素のlabel値を文字列で返す。

    Args:
        item: Docling要素。

    Returns:
        label値。labelを持たない要素では空文字列。
    """

    label = getattr(item, "label", None)
    return label.value if label is not None else ""


def _uri(value: AnyUrl | PurePath) -> str:
    """URIまたは相対pathを、OSに依存しない文字列へ変換する。

    Args:
        value: Docling要素のURIまたはpath。

    Returns:
        pathは`/`区切り、URIは文字列表現。
    """

    return value.as_posix() if isinstance(value, PurePath) else str(value)


def _visible_content(item: NodeItem) -> bool:
    """要素自身が失うべきでない可視内容を持つか判定する。

    Args:
        item: Docling要素。

    Returns:
        text、画像または表dataが存在する場合はTrue。
    """

    if isinstance(item, TextItem):
        return bool(item.text.strip())
    if isinstance(item, PictureItem):
        return item.image is not None
    return isinstance(item, TableItem)


def _page_number(item: NodeItem) -> int:
    """provenanceから1始まりページ番号を得る。

    Args:
        item: Docling要素。

    Returns:
        ページ番号。情報がない場合は1。
    """

    provenance = item.prov if isinstance(item, DocItem) else []
    if provenance and provenance[0].page_no > 0:
        return provenance[0].page_no
    return 1


def _inline(
    ref: str,
    text: str,
    kind: TextKind = "text",
    href: str | None = None,
    marks: list[TextMark] | None = None,
) -> list[TextSpan]:
    """Docling文字列を文境界でInline列へ変換し、原文と書式を保持する。

    Args:
        ref: 安定IDのprefix。
        text: 可視文字列。
        kind: Inline種別。
        href: link URL。
        marks: Inline装飾。

    Returns:
        空文字なら空、それ以外は原文を欠落なく分割したInline列。
    """

    if not text:
        return []
    return [
        TextSpan(
            id=f"{ref}/span-{index:04d}",
            source=part,
            kind=kind,
            href=href,
            marks=marks or [],
        )
        for index, part in enumerate(
            split_sentences(text) if kind == "text" else [text], 1
        )
    ]


def _inline_from_item(
    item: TextItem, ref: str, text: str, kind: TextKind
) -> list[TextSpan]:
    """Docling TextItemのlinkと装飾をInlineへ移す。

    Args:
        item: Docling TextItem。
        ref: 安定IDのprefix。
        text: 可視文字列。
        kind: 基本Inline種別。

    Returns:
        hyperlinkとFormattingを保持したInline列。
    """

    marks: list[TextMark] = []
    if item.formatting is not None:
        marks.extend(
            mark for name, mark in MARK_FIELDS if getattr(item.formatting, name)
        )
        if item.formatting.script == Script.SUB:
            marks.append("subscript")
        elif item.formatting.script == Script.SUPER:
            marks.append("superscript")
    href = _uri(item.hyperlink) if item.hyperlink is not None else None
    inline_kind: TextKind = "link" if href and kind == "text" else kind
    return _inline(ref, text, inline_kind, href, marks)


@dataclass
class _CellSource:
    """LOAD呼出中だけ、論理セルとDoclingの同一位置セルを対応させる。"""

    cell: TableCell
    rowspan: int = 1
    colspan: int = 1
    variants: list[DoclingCell] = field(default_factory=list)


class TableImageOwnershipError(ValueError):
    """本文やasset pathを公開せず、所属失敗の対象だけを診断へ渡す。"""

    def __init__(self, page: int | None, ref: str) -> None:
        """検証済み形式のDocling IDとページを保持し、任意文字列IDを公開しない。

        Args:
            page (int | None): 処理対象のPageまたはPage番号。
            ref (str): Docling要素を指すJSON参照。
        """

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
    """所属検証の詳細例外を、内容を含まない対象付き診断へ正規化する。

    Args:
        page (int | None): 処理対象のPageまたはPage番号。
        ref (str): Docling要素を指すJSON参照。

    Yields:
        None: 所属検証の詳細例外を、内容を含まない対象付き診断へ正規化する。

    Raises:
        TableImageOwnershipError: Table画像のPage、所有Cellまたは幾何情報が欠損、競合、曖昧な場合。
    """

    try:
        yield
    except ValueError as error:
        raise TableImageOwnershipError(page, ref) from error


def _cell_shape(raw: DoclingCell) -> tuple[int, int, int, int]:
    """半開offsetとspanを照合し、負位置や矛盾を丸めずに拒否する。

    Args:
        raw (DoclingCell): Doclingのtable cell。

    Returns:
        tuple[int, int, int, int]: 開始行、開始列、行span、列spanの組。

    Raises:
        ValueError: `invalid table cell position`、`invalid table cell span`、`conflicting
            table cell span`のいずれかと判定した場合。
    """

    start_row, start_col = raw.start_row_offset_idx, raw.start_col_offset_idx
    if start_row < 0 or start_col < 0:
        raise ValueError("invalid table cell position")
    if raw.row_span < 1 or raw.col_span < 1:
        raise ValueError("invalid table cell span")
    end_row, end_col = raw.end_row_offset_idx, raw.end_col_offset_idx
    # 明示されたspanだけをoffsetと照合し、省略時の既定値では拒否しない。
    if (
        end_row <= start_row
        or end_col <= start_col
        or ("row_span" in raw.model_fields_set and end_row - start_row != raw.row_span)
        or ("col_span" in raw.model_fields_set and end_col - start_col != raw.col_span)
    ):
        raise ValueError("conflicting table cell span")
    return start_row, start_col, end_row - start_row, end_col - start_col


def _normalized_cells(item: TableItem, ref: str) -> list[_CellSource]:
    """同一論理セルの重複を統合し、span・内容・占有領域の矛盾を拒否する。

    Args:
        item (TableItem): Doclingの表。
        ref (str): Docling要素を指すJSON参照。

    Returns:
        list[_CellSource]: 開始位置順の論理Cell一覧。空セルで表全体を埋める。

    Raises:
        ValueError: `table cell exceeds table dimensions`、`conflicting table cell
            representations`、`conflicting table cell header roles`のいずれかと判定した場合。
    """

    data = item.data
    cells: dict[tuple[int, int], _CellSource] = {}
    occupied: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for raw in data.table_cells:
        start_row, start_col, rowspan, colspan = _cell_shape(raw)
        key = (start_row, start_col)
        if data.num_rows < start_row + rowspan or data.num_cols < start_col + colspan:
            raise ValueError("table cell exceeds table dimensions")
        cell = TableCell(
            id=f"{ref}/cell-r{start_row:04d}-c{start_col:04d}",
            row=start_row,
            column=start_col,
            header=raw.column_header or raw.row_header,
            content=TextUnit(
                id=f"{ref}/cell-r{start_row:04d}-c{start_col:04d}/content",
                spans=_inline(f"{ref}/cell/{start_row}/{start_col}", raw.text),
            ),
        )
        if key in cells:
            previous = cells[key]
            if (
                previous.rowspan,
                previous.colspan,
                previous.cell.header,
                previous.cell.content.text("source"),
            ) != (rowspan, colspan, cell.header, cell.content.text("source")):
                raise ValueError("conflicting table cell representations")
            previous_raw = previous.variants[0]
            if (previous_raw.row_header, previous_raw.column_header) != (
                raw.row_header,
                raw.column_header,
            ):
                raise ValueError("conflicting table cell header roles")
        else:
            cells[key] = _CellSource(cell, rowspan=rowspan, colspan=colspan)
        for r in range(start_row, start_row + rowspan):
            for c in range(start_col, start_col + colspan):
                occupied.setdefault((r, c), set()).add(key)
        cells[key].variants.append(raw)
    conflicting = {
        key for owners in occupied.values() if len(owners) > 1 for key in owners
    }
    # Doclingが矛盾する結合範囲を返しても、各セルの本文と開始位置は保持する。
    for key in conflicting:
        cells[key].rowspan = 1
        cells[key].colspan = 1
    # 保存するDocumentは通常grid。結合範囲の本文は起点だけに置き、残りは空セルにする。
    row_count = data.num_rows or max((row + 1 for row, _ in occupied), default=0)
    column_count = data.num_cols or max(
        (column + 1 for _, column in occupied), default=0
    )
    for row in range(row_count):
        for column in range(column_count):
            if (row, column) not in cells:
                identifier = f"{ref}/cell-r{row:04d}-c{column:04d}"
                cells[(row, column)] = _CellSource(
                    TableCell(
                        id=identifier,
                        row=row,
                        column=column,
                        content=TextUnit(id=f"{identifier}/content", spans=[]),
                    )
                )
    return [cells[key] for key in sorted(cells)]


def _table_cells(item: TableItem, ref: str) -> list[TableCell]:
    """重複を除いた論理セルを内部文書へ渡す。

    Args:
        item (TableItem): Doclingの表。
        ref (str): Docling要素を指すJSON参照。

    Returns:
        list[TableCell]: 開始位置順のTableCell列。
    """

    with _ownership_context(_page_number(item), ref):
        return [source.cell for source in _normalized_cells(item, ref)]


def _top_left_box(
    box: BoundingBox | None, page: Page
) -> tuple[float, float, float, float] | None:
    """存在するbboxは有限の正領域として検査し、ページ高さで原点を統一する。

    Args:
        box (BoundingBox | None): Doclingのbbox。
        page (Page): 処理対象のPage。

    Returns:
        tuple[float, float, float, float] | None: 左上原点の左、上、右、下。bboxがない場合はNone。

    Raises:
        ValueError: `invalid image ownership geometry`、`missing page height for image
            ownership`のいずれかと判定した場合。
    """

    if box is None:
        return None
    if box.coord_origin == CoordOrigin.BOTTOMLEFT:
        if page.height is None or not math.isfinite(page.height) or page.height <= 0:
            raise ValueError("missing page height for image ownership")
        box = box.to_top_left_origin(page.height)
    values = (box.l, box.t, box.r, box.b)
    if (
        not all(math.isfinite(value) for value in values)
        or box.l >= box.r
        or box.t >= box.b
    ):
        raise ValueError("invalid image ownership geometry")
    return values


def _item_box(item: DocItem, page: Page) -> tuple[float, float, float, float] | None:
    """所有関係を判断する同ページのprovenanceだけを取得し、矛盾を拒否する。

    Args:
        item (DocItem): 位置を判定するDocling要素。
        page (Page): 処理対象のPage。

    Returns:
        tuple[float, float, float, float] | None: 左上原点の座標。同Pageのbboxがない場合はNone。

    Raises:
        ValueError: `conflicting image ownership provenance`と判定した場合。
    """

    boxes = {
        _top_left_box(value.bbox, page)
        for value in item.prov
        if value.page_no == page.number
    }
    boxes.discard(None)
    if len(boxes) > 1:
        raise ValueError("conflicting image ownership provenance")
    return next(iter(boxes), None)


def _contains(
    outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]
) -> bool:
    """距離閾値を使わず矩形全体の包含を判定する。

    Args:
        outer (tuple[float, float, float, float]): 包含判定で外側になる座標矩形。
        inner (tuple[float, float, float, float]): 内側に含まれるか判定する座標矩形。

    Returns:
        bool: outerがinnerを完全に含む場合はTrue。
    """

    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _geometric_cell(
    cells: list[_CellSource], box: tuple[float, float, float, float], page: Page
) -> set[int]:
    """セルbbox包含と行列見出しの交差から候補セルを返す。

    Args:
        cells (list[_CellSource]): Markdownの一行へ配置するTable Cell列。
        box (tuple[float, float, float, float]): 判定対象の座標矩形。
        page (Page): 処理対象のPage。

    Returns:
        set[int]: 画像を含む候補セルのIndex。一意でない場合も候補を保持する。

    Raises:
        ValueError: `conflicting cell ownership geometry`と判定した場合。
    """

    direct: set[int] = set()
    rows: set[int] = set()
    columns: set[int] = set()
    center_x, center_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for index, source in enumerate(cells):
        cell = source.cell
        boxes = {_top_left_box(raw.bbox, page) for raw in source.variants}
        boxes.discard(None)
        if len(boxes) > 1:
            raise ValueError("conflicting cell ownership geometry")
        cell_box = next(iter(boxes), None)
        if cell_box is None:
            continue
        if _contains(cell_box, box):
            direct.add(index)
        if (
            any(raw.column_header for raw in source.variants)
            and cell_box[0] < center_x < cell_box[2]
        ):
            columns.update(range(cell.column, cell.column + source.colspan))
        if (
            any(raw.row_header for raw in source.variants)
            and cell_box[1] < center_y < cell_box[3]
        ):
            rows.update(range(cell.row, cell.row + source.rowspan))
    intersections = {
        index
        for index, source in enumerate(cells)
        if any(
            source.cell.row <= row < source.cell.row + source.rowspan
            and source.cell.column <= column < source.cell.column + source.colspan
            for row in rows
            for column in columns
        )
    }
    return direct | intersections


def _explicit_image_owners(
    sources: dict[str, list[_CellSource]], pictures: dict[str, PictureItem]
) -> dict[str, set[tuple[str, int]]]:
    """セル側参照と画像の親参照を統合し、不正セル参照を幾何推測で隠さない。

    Args:
        sources (dict[str, list[_CellSource]]): 表参照別の論理セル。
        pictures (dict[str, PictureItem]): 参照別の画像。

    Returns:
        dict[str, set[tuple[str, int]]]: Picture参照から所有元のTable参照とCell Indexの集合への辞書。

    Raises:
        TableImageOwnershipError: Table画像のPage、所有Cellまたは幾何情報が欠損、競合、曖昧な場合。
    """

    owners: dict[str, set[tuple[str, int]]] = {}
    for table_ref, cells in sources.items():
        for index, source in enumerate(cells):
            for raw in source.variants:
                if not isinstance(raw, RichTableCell):
                    continue
                ref = raw.ref.cref
                if ref.startswith("#/pictures/"):
                    if ref not in pictures:
                        raise TableImageOwnershipError(None, table_ref)
                    owners.setdefault(ref, set()).add((table_ref, index))
    for picture_ref, picture in pictures.items():
        parent_ref = picture.parent.cref if picture.parent is not None else None
        if (
            parent_ref is not None
            and parent_ref.startswith("#/tables/")
            and parent_ref not in sources
        ):
            raise TableImageOwnershipError(_page_number(picture), picture_ref)
    for ref, value in owners.items():
        if len(value) != 1:
            raise TableImageOwnershipError(_page_number(pictures[ref]), ref)
    return owners


class DocumentLoader:
    """Docling文書を保持し、参照・Caption・図表を共通Documentへ変換する。"""

    def __init__(self, document: dict[str, Any]) -> None:
        """Docling JSONを検証し、構造変換の対象として保持する。

        Args:
            document: Docling Serveが返したJSON object。元の値は書き換えない。

        Raises:
            ValueError: DoclingDocumentのschemaを満たさない場合。
        """
        self.raw = document
        self.document = DoclingDocument.model_validate(document)

    def load(self) -> Document:
        """Docling documentをページ順のv5 Documentへ変換する。

        Returns:
            正規化済みDocument。

        Raises:
            ValueError: ページ、参照、要素が契約を満たさない場合。
        """

        pages = self._normalized_pages()
        seen: set[str] = set()
        caption_refs = self._owned_caption_refs()
        excluded_indexes = index_refs(self.raw)
        picture_content_refs = self._picture_content_refs()
        # bodyの文書順を正本とし、bodyに現れないcollection要素だけを後段で補完する。
        ordered_items: list[tuple[NodeItem, int, bool | None]] = [
            (item, *self._list_context(item))
            for item, _ in self.document.iterate_items(
                with_groups=False,
                traverse_pictures=True,
                included_content_layers=set(ContentLayer),
            )
        ]
        for collection in (
            self.document.texts,
            self.document.tables,
            self.document.pictures,
            self.document.key_value_items,
            self.document.form_items,
        ):
            ordered_items.extend(
                (item, 1 if _label(item) in LIST_LABELS else 0, None)
                for item in collection
            )
        page_orders: dict[int, int] = dict.fromkeys(pages, 0)
        for item, list_level, parent_ordered in ordered_items:
            ref = item.self_ref
            if ref in seen:
                continue
            seen.add(ref)
            if ref in caption_refs or ref in picture_content_refs:
                continue
            if ref in excluded_indexes:
                continue
            number = _page_number(item)
            if number not in pages:
                msg = (
                    f"Docling element references missing page: ref={ref} page={number}"
                )
                raise ValueError(msg)
            block = self._block(item, page_orders[number], list_level, parent_ordered)
            if block is not None:
                if isinstance(item, DocItem) and item.prov:
                    block.bbox = _top_left_box(item.prov[0].bbox, pages[number])
                pages[number].blocks.append(block)
                page_orders[number] += 1
        self._assign_cell_images(pages)
        return Document(
            pages=[pages[number] for number in sorted(pages)],
            metadata={
                "source_schema": "DoclingDocument",
                "source_name": self.document.name,
            },
        )

    def _list_context(self, item: NodeItem) -> tuple[int, bool | None]:
        """祖先のList groupから、箇条書きの階層と番号付きかどうかを求める。

        Args:
            item: Docling要素。

        Returns:
            List groupの祖先数と、最も近いList groupが番号付きかどうか。List外ではNone。
        """

        level, ordered = 0, None
        parent = item.parent
        while parent is not None:
            node = parent.resolve(self.document)
            if isinstance(node, GroupItem) and node.label in {
                GroupLabel.LIST,
                GroupLabel.ORDERED_LIST,
            }:
                level += 1
                if ordered is None:
                    ordered = node.label == GroupLabel.ORDERED_LIST
            parent = node.parent
        return level, ordered

    def _caption_inlines(
        self, item: TableItem | PictureItem, ref: str
    ) -> TextUnit | None:
        """図表のcaption参照をInline列へ変換する。

        Args:
            item: TableItemまたはPictureItem。
            ref: caption IDのprefix。

        Returns:
            参照先の装飾も保持したcaption Inline列。
        """

        result: list[TextSpan] = []
        for index, caption in enumerate(item.captions):
            caption_item = caption.resolve(self.document)
            if isinstance(caption_item, TextItem):
                result.extend(
                    _inline_from_item(
                        caption_item,
                        f"{ref}/caption/{index}",
                        caption_item.text,
                        "text",
                    )
                )
        return TextUnit(id=f"{ref}/caption", spans=result) if result else None

    def _owned_caption_refs(self) -> set[str]:
        """図表Blockへ内包するcaption TextItemのrefを集める。

        Returns:
            standalone本文として重複出力しないcaption ref集合。
        """

        # captionは図表Blockへ所有させ、body側TextItemとの二重出力を防ぐ。
        return {
            caption.cref
            for item in [*self.document.tables, *self.document.pictures]
            for caption in item.captions
        }

    def _picture_content_refs(self) -> set[str]:
        """picture配下でcaptionではない重複textのrefを集める。

        Returns:
            Figure asset側に任せて本文出力しないtext ref集合。
        """

        picture_refs = {item.self_ref for item in self.document.pictures}
        parents = {
            item.self_ref: item.parent.cref
            for collection in (
                self.document.texts,
                self.document.tables,
                self.document.pictures,
                self.document.key_value_items,
                self.document.form_items,
                self.document.groups,
            )
            for item in collection
            if item.parent is not None
        }
        # 親chainを辿るのは、picture直下にgroupを挟むDocling出力にも対応するため。
        result: set[str] = set()
        for item in self.document.texts:
            if _label(item) == "caption":
                continue
            parent = parents.get(item.self_ref, "")
            visited: set[str] = set()
            while parent and parent not in visited:
                if parent in picture_refs:
                    result.add(item.self_ref)
                    break
                visited.add(parent)
                parent = parents.get(parent, "")
        return result

    def _assign_cell_images(self, pages: dict[int, Page]) -> None:
        """一意に確定した画像だけを表セルへ移し、body/collection由来の独立図を除く。

        Args:
            pages (dict[int, Page]): Page番号または参照別のPage Data。

        Raises:
            TableImageOwnershipError: Table画像のPage、所有Cellまたは幾何情報が欠損、競合、曖昧な場合。
        """

        tables = {item.self_ref: item for item in self.document.tables}
        pictures = {item.self_ref: item for item in self.document.pictures}
        sources = {ref: _normalized_cells(item, ref) for ref, item in tables.items()}
        explicit = _explicit_image_owners(sources, pictures)
        for page in pages.values():
            page_tables = {
                block.id: block for block in page.blocks if block.kind == "table"
            }
            consumed: set[str] = set()
            for figure in (block for block in page.blocks if block.kind == "figure"):
                if figure.image is None:
                    raise TableImageOwnershipError(page.number, figure.id)
                declared = explicit.get(figure.id, set())
                if not page_tables and not declared:
                    continue
                picture = pictures[figure.id]
                parent_ref = picture.parent.cref if picture.parent is not None else None
                declared_ref = next(iter(declared))[0] if declared else None
                if declared_ref is not None and declared_ref not in page_tables:
                    raise TableImageOwnershipError(page.number, figure.id)
                with _ownership_context(page.number, figure.id):
                    box = _item_box(picture, page)
                if box is None:
                    raise TableImageOwnershipError(page.number, figure.id)
                containing = []
                unknown_table = False
                ambiguous_overlap = False
                for ref in page_tables:
                    with _ownership_context(page.number, ref):
                        table_box = _item_box(tables[ref], page)
                    if table_box is None:
                        if declared_ref is None:
                            unknown_table = True
                            continue
                        if ref == declared_ref:
                            containing.append(ref)
                        continue
                    if _contains(table_box, box):
                        containing.append(ref)
                    elif max(table_box[0], box[0]) < min(table_box[2], box[2]) and max(
                        table_box[1], box[1]
                    ) < min(table_box[3], box[3]):
                        if declared_ref is not None or parent_ref in sources:
                            raise TableImageOwnershipError(page.number, figure.id)
                        ambiguous_overlap = True
                # 所属根拠のない部分重複は推測せず、独立した図として保持する。
                if ambiguous_overlap or unknown_table:
                    continue
                if len(containing) > 1:
                    if declared_ref is None and parent_ref not in sources:
                        continue
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
                            cell_box = _top_left_box(raw.bbox, page)
                        if cell_box is not None and not _contains(cell_box, box):
                            raise TableImageOwnershipError(page.number, figure.id)
                elif len(candidates) == 1:
                    index = next(iter(candidates))
                else:
                    # 帰属先セルを推測できない画像は独立した図として残す。
                    continue
                sources[ref][index].cell.images.append(
                    Image(
                        id=figure.image.id,
                        asset_path=figure.image.asset_path,
                        width_pt=box[2] - box[0],
                        height_pt=box[3] - box[1],
                        alt_text=figure.image.alt_text,
                        caption=figure.image.caption,
                    )
                )
                consumed.add(figure.id)
            for ref, block in page_tables.items():
                block.cells = [source.cell for source in sources[ref]]
            page.blocks = [block for block in page.blocks if block.id not in consumed]
            for order, block in enumerate(page.blocks):
                block.order = order

    def _block(
        self,
        item: NodeItem,
        order: int,
        list_level: int = 0,
        parent_ordered: bool | None = None,
    ) -> Block | None:
        """一つのDocling要素をBlockへ変換する。

        Args:
            item: Docling要素。
            order: ページ内の文書順。
            list_level: 祖先のList groupから得た1始まり階層。
            parent_ordered: 最も近いList groupが順序付きかどうか。

        Returns:
            対応Block。仕様上除外する要素はNone。

        Raises:
            ValueError: 内容を持つ未知要素または欠損assetの場合。
        """

        ref = item.self_ref
        label = _label(item)
        if label in SKIPPED_LABELS:
            return None
        if label == "document_index":
            # 内容から目次と確認できなかった要素は、所属collectionの表・画像・本文として残す。
            label = {"tables": "table", "pictures": "picture"}.get(
                ref.removeprefix("#/").split("/")[0], "text"
            )
        if label == "table" and isinstance(item, TableItem):
            return Block(
                id=ref,
                order=order,
                kind="table",
                caption=self._caption_inlines(item, ref),
                cells=_table_cells(item, ref),
            )
        if label == "picture" and isinstance(item, PictureItem):
            if item.image is None:
                msg = f"picture asset is missing: ref={ref} label={label}"
                raise ValueError(msg)
            relative = (
                _uri(item.image.uri).removeprefix("artifacts/").removeprefix("assets/")
            )
            # MERGE publishes the contents of each structured/assets directory
            # under the run-level assets root; keep the Internal Document path
            # relative to that root so VALIDATE/Markdown resolve the same file.
            caption = self._caption_inlines(item, ref)
            return Block(
                id=ref,
                order=order,
                kind="figure",
                image=Image(
                    id=f"{ref}/image-0001",
                    asset_path=f"assets/{relative}",
                    alt_text=caption.text("source") if caption is not None else "",
                    caption=caption,
                ),
            )
        kind = TEXT_KINDS.get(label)
        if kind is None or not isinstance(item, TextItem):
            if not _visible_content(item):
                return None
            # 内容のある未知要素をparagraphへ丸めると欠損に気付けないためfail-fastする。
            msg = (
                f"unsupported content-bearing Docling element: ref={ref} label={label}"
            )
            raise ValueError(msg)
        inline_kind: TextKind = "code" if kind in {"code", "formula"} else "text"
        level = getattr(item, "level", None) if kind == "heading" else None
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
            content=TextUnit(
                id=f"{ref}/content",
                spans=_inline_from_item(item, f"{ref}/content", item.text, inline_kind),
            ),
            level=level
            if isinstance(level, int)
            else 1
            if kind == "heading"
            else max(1, list_level)
            if kind == "list_item"
            else None,
            ordered=item.enumerated
            if isinstance(item, ListItem)
            else bool(parent_ordered),
            checked=checked,
        )

    def _normalized_pages(self) -> dict[int, Page]:
        """Docling page mapを内部Page mapへ変換する。

        Returns:
            Page番号をkeyとする内部Page map。

        Raises:
            ValueError: Docling page mapが空の場合。
        """

        if not self.document.pages:
            msg = "Docling pages must be a non-empty object"
            raise ValueError(msg)
        return {
            number: Page(number=number, width=page.size.width, height=page.size.height)
            for number, page in self.document.pages.items()
        }


def load(source: Path, output_dir: Path) -> Document:
    """Docling JSONを共通Documentへ変換して原子的に保存する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        output_dir (Path): Task成果物の出力Directory。

    Returns:
        Document: 保存したDocument。
    """

    document = DocumentLoader(json.loads(source.read_text(encoding="utf-8"))).load()
    with temporary_task_directory(output_dir) as temporary:
        write_model(temporary / "document.json", document, atomic=False)
    return document
