"""正規化済み文書を決定的にPandoc Markdownへ変換する。"""

from __future__ import annotations

import html
import itertools
import json
import math
import re
import shutil
from typing import TYPE_CHECKING

from translate_v1.adapters.pandoc import table_to_markdown
from translate_v1.common.workspace import atomic_directory, atomic_write_text
from translate_v1.document import Block, Document, Inline, TableCell, inline_text
from translate_v1.tasks.base import BaseTask

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from translate_v1.document import CellImage

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _escape(text: str) -> str:
    """Markdown制御文字をplain textとしてescapeする。

    Args:
        text: 出力する文字列。

    Returns:
        Markdownで同じ文字として表示される文字列。
    """

    return re.sub(r"([\\`*{}\[\]()#+.!_|>~-])", r"\\\1", text)


def _apply_marks(value: str, marks: Sequence[str]) -> str:
    """Doclingのmark順を保ってMarkdown装飾を重ねる。

    Args:
        value: 装飾するMarkdown文字列。
        marks: 適用順の装飾名。

    Returns:
        装飾済みMarkdown文字列。
    """

    wrappers = {
        "strong": ("**", "**"),
        "emphasis": ("*", "*"),
        "strikethrough": ("~~", "~~"),
        "underline": ("[", ']{custom-style="Underline"}'),
        "subscript": ("~", "~"),
        "superscript": ("^", "^"),
    }
    for mark in marks:
        if mark in wrappers:
            prefix, suffix = wrappers[mark]
            value = f"{prefix}{value}{suffix}"
    return value


def render_inlines(values: list[Inline]) -> str:
    """Inline列をPandoc Markdownへ変換する。

    Args:
        values: 文書順のInline列。

    Returns:
        Markdown inline文字列。
    """

    rendered: list[str] = []
    for item in values:
        if item.kind == "line_break":
            rendered.append("  \n")
            continue
        if item.kind == "code":
            value = f"`{item.text.replace('`', '``')}`"
        else:
            value = _escape(item.text)
        value = _apply_marks(value, item.marks)
        if item.kind == "link":
            value = f"[{value}]({_escape(item.href or '')})"
        rendered.append(value)
    return "".join(rendered)


def _current(block: Block) -> list[Inline]:
    """Blockの最終出力に使うInline列を選ぶ。

    Args:
        block: 対象Block。

    Returns:
        最終層、翻訳層、原文の優先順で選ぶ。Noneだけを未設定とし、空列は維持する。
    """

    return (
        block.final
        if block.final is not None
        else block.translated
        if block.translated is not None
        else block.source
    )


def _cell_current(cell: TableCell) -> list[Inline]:
    """TableCellの最終出力に使うInline列を選ぶ。

    Args:
        cell: 対象cell。

    Returns:
        最終層、翻訳層、原文の優先順で選ぶ。Noneだけを未設定とし、空列は維持する。
    """

    return (
        cell.final
        if cell.final is not None
        else cell.translated
        if cell.translated is not None
        else cell.source
    )


def _caption_current(block: Block | CellImage) -> list[Inline]:
    """図表題の最終出力に使うInline列を選ぶ。

    Args:
        block: 図または表Block。

    Returns:
        最終層、翻訳層、原文の優先順で選ぶ。Noneだけを未設定とし、空列は維持する。
    """

    return (
        block.final_caption
        if block.final_caption is not None
        else block.translated_caption
        if block.translated_caption is not None
        else block.caption
    )


def _render_table(block: Block) -> str:
    """Table Blockを結合セル対応のPandoc grid tableへ変換する。

    Args:
        block: table種別のBlock。

    Returns:
        PandocがWordの表として出力できるgrid table。
    """

    _validate_table(block)
    columns = max(cell.column + cell.colspan for cell in block.cells)
    rows = [
        _table_row(block.cells, row, columns)
        for row in range(max(cell.row + cell.rowspan for cell in block.cells))
    ]
    header_rows = 0
    for row in range(len(rows)):
        covering = [
            cell for cell in block.cells if cell.row <= row < cell.row + cell.rowspan
        ]
        if not any(cell.header for cell in covering) or any(
            not cell.header
            and (inline_text(_cell_current(cell)).strip() or cell.images)
            for cell in covering
        ):
            break
        header_rows += 1
    # PandocのTableHead/TableBodyをまたぐ縦結合は同じセルとして扱われない。
    # この場合だけ全行をbodyへ置き、見出しの意味はセルの太字で保持する。
    if any(cell.row < header_rows < cell.row + cell.rowspan for cell in block.cells):
        header_rows = 0
    caption = _table_inlines(_caption_current(block))
    # Pandocの構文木へセルを直接対応付ける。HTMLや独自の表解析は介在させず、
    # 幅計算・Unicodeの折返し・結合境界は導入済みPandocのwriterへ委譲する。
    return table_to_markdown(
        {
            "t": "Table",
            "c": [
                ["", [], []],
                [None, [{"t": "Plain", "c": caption}] if caption else []],
                [
                    [{"t": "AlignDefault"}, {"t": "ColWidthDefault"}]
                    for _ in range(columns)
                ],
                [["", [], []], rows[:header_rows]],
                [[["", [], []], 0, [], rows[header_rows:]]],
                [["", [], []], []],
            ],
        }
    )


def _table_row(cells: list[TableCell], row: int, columns: int) -> list[object]:
    """開始位置と結合済み領域を保ち、1行をPandocのRowへ対応付ける。"""

    result: list[object] = []
    occupied = {
        column
        for cell in cells
        if cell.row <= row < cell.row + cell.rowspan
        for column in range(cell.column, cell.column + cell.colspan)
    }
    starts = {cell.column: cell for cell in cells if cell.row == row}
    for column in range(columns):
        cell = starts.get(column)
        if cell is None and column in occupied:
            continue
        inlines: list[dict[str, object]] = (
            _table_inlines(_cell_current(cell)) if cell else []
        )
        if cell is not None and cell.header and inlines:
            inlines = [{"t": "Strong", "c": inlines}]
        result.append(
            [
                ["", [], []],
                {"t": "AlignDefault"},
                cell.rowspan if cell else 1,
                cell.colspan if cell else 1,
                _cell_blocks(cell, inlines) if cell else [],
            ]
        )
    return [["", [], []], result]


def _cell_blocks(
    cell: TableCell, inlines: list[dict[str, object]]
) -> list[dict[str, object]]:
    """既存Pandoc Cell内に本文・画像・採用Captionを置き、画像をFigureへ昇格させない。"""

    blocks = [{"t": "Plain", "c": inlines}] if inlines else []
    for image in cell.images:
        attributes = [
            ["width", f"{image.width_pt}pt"],
            ["height", f"{image.height_pt}pt"],
            ["fig-alt", image.alt_text],
        ]
        # Empty image caption avoids Pandoc's implicit Figure/list numbering.
        # The actual translated caption is a separate paragraph in this cell.
        blocks.append(
            {
                "t": "Plain",
                "c": [
                    {
                        "t": "Image",
                        "c": [["", [], attributes], [], [image.asset_path, ""]],
                    }
                ],
            }
        )
        caption = _caption_current(image)
        if caption:
            blocks.append({"t": "Plain", "c": _table_inlines(caption)})
    return blocks


def _table_inlines(values: list[Inline]) -> list[dict[str, object]]:
    """表と表題のInline型・装飾を既存Pandocの構文木へ対応付ける。"""

    result: list[dict[str, object]] = []
    mark_types = {
        "strong": "Strong",
        "emphasis": "Emph",
        "strikethrough": "Strikeout",
        "underline": "Underline",
        "subscript": "Subscript",
        "superscript": "Superscript",
    }
    for item in values:
        if item.kind == "line_break":
            result.append({"t": "LineBreak"})
            continue
        content: list[dict[str, object]]
        if item.kind == "code":
            content = [{"t": "Code", "c": [["", [], []], item.text]}]
        else:
            content = [
                {"t": "LineBreak"}
                if part == "\n"
                else {"t": "Space"}
                if part.isspace()
                else {"t": "Str", "c": part}
                for part in re.split(r"(\n|[^\S\n]+)", item.text)
                if part
            ]
        for mark in item.marks:
            content = [{"t": mark_types[mark], "c": content}]
        if item.kind == "link":
            content = [
                {"t": "Link", "c": [["", [], []], content, [item.href or "", ""]]}
            ]
        result.extend(content)
    return result


def _render_structural_block(block: Block, text: str) -> str | None:
    """見出し、リスト、引用、alertを描画する。

    Args:
        block: 描画するBlock。
        text: 描画済みinline本文。

    Returns:
        対応するMarkdown。対象外ならNone。
    """

    if block.kind == "heading":
        return (
            f"{'#' * max(1, min(6, block.level or 1))} {text} {{#{_anchor(block.id)}}}"
        )
    if block.kind == "list_item":
        marker = "1." if block.ordered else "-"
        task = "" if block.checked is None else f"[{'x' if block.checked else ' '}] "
        # Pandocの入れ子listは一階層4空白に固定するとDOCXでもlistを維持する。
        return f"{'    ' * max(0, (block.level or 1) - 1)}{marker} {task}{text}"
    if block.kind == "blockquote":
        return "\n".join(f"> {line}" for line in text.splitlines())
    if block.kind == "alert":
        label = (block.alert_kind or "note").upper()
        return f"> [!{label}]\n" + "\n".join(f"> {line}" for line in text.splitlines())
    return None


def _render_literal_block(block: Block) -> str | None:
    """code、数式、表を描画する。

    Args:
        block: 描画するBlock。

    Returns:
        対応するMarkdown。対象外ならNone。
    """

    if block.kind == "code":
        code = inline_text(_current(block))
        # 本文中のbacktick列より長いfenceを選び、codeを途中で閉じない。
        longest_run = max((len(value) for value in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, longest_run + 1)
        return f"{fence}{block.language or ''}\n{code}\n{fence}"
    if block.kind == "formula":
        return f"$$\n{inline_text(_current(block))}\n$$"
    if block.kind == "table":
        return _render_table(block)
    return None


def _render_media_block(block: Block, text: str) -> str | None:
    """図、脚注、水平線を描画する。

    Args:
        block: 描画するBlock。
        text: 描画済みinline本文。

    Returns:
        対応するMarkdown。対象外ならNone。
    """

    if block.kind == "figure":
        caption = render_inlines(_caption_current(block))
        path = _escape(block.asset_path or "")
        if caption:
            return f"![{caption}]({path})"
        # Pandocではalt textが暗黙のcaptionになるためfig-altへ明示的に分離する。
        alt = html.escape(block.alt_text or "", quote=True)
        return f'![]({path}){{fig-alt="{alt}"}}'
    if block.kind == "footnote":
        anchor = _anchor(block.id)
        return f"[^{anchor}]\n\n[^{anchor}]: {text}"
    if block.kind == "horizontal_rule":
        return "---"
    return None


def render_block(block: Block) -> str:
    """一つのBlockをPandoc Markdownへ変換する。

    Args:
        block: 対象Block。

    Returns:
        Blockに対応するMarkdown断片。
    """

    text = render_inlines(_current(block))
    for rendered in (
        _render_structural_block(block, text),
        _render_literal_block(block),
        _render_media_block(block, text),
    ):
        if rendered is not None:
            return rendered
    return text


def _anchor(value: str) -> str:
    """任意のrefから安全なMarkdown anchorを作る。

    Args:
        value: Docling ref等の安定ID。

    Returns:
        英数字、underscore、hyphenだけのanchor。
    """

    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "item"


def _validate_table(block: Block) -> None:
    """表cellの位置重複とspanを検証する。

    Args:
        block: table Block。

    Returns:
        なし。
    """

    positions: set[tuple[int, int]] = set()
    if not block.cells:
        msg = f"invalid table shape: {block.id}"
        raise ValueError(msg)
    for cell in block.cells:
        occupied = {
            (row, column)
            for row in range(cell.row, cell.row + cell.rowspan)
            for column in range(cell.column, cell.column + cell.colspan)
        }
        if (
            positions & occupied
            or min(cell.rowspan, cell.colspan) < 1
            or min(cell.row, cell.column) < 0
        ):
            msg = f"invalid table shape: {block.id}"
            raise ValueError(msg)
        positions.update(occupied)


def _validate_links(block: Block, anchors: set[str]) -> None:
    """Block配下の内部link参照を検証する。

    Args:
        block: 検証するBlock。
        anchors: 文書内の見出しanchor集合。

    Returns:
        なし。
    """

    inline_groups = [_current(block), _caption_current(block)]
    if block.kind == "table":
        inline_groups.extend(_cell_current(cell) for cell in block.cells)
        inline_groups.extend(
            _caption_current(image) for cell in block.cells for image in cell.images
        )
    for item in (item for group in inline_groups for item in group):
        is_unresolved = (
            item.kind == "link"
            and bool(item.href)
            and item.href.startswith("#")
            and item.href[1:] not in anchors
        )
        if is_unresolved:
            msg = f"unresolved internal reference: {block.id}"
            raise ValueError(msg)


def _validate_block(block: Block, asset_root: Path, anchors: set[str]) -> None:
    """一つのBlockと参照先を検証する。

    Args:
        block: 検証するBlock。
        asset_root: assetの基準directory。
        anchors: 文書内の見出しanchor集合。

    Returns:
        なし。
    """

    if block.cells and block.kind != "table":
        raise ValueError("non-table block contains cells")
    if CONTROL_RE.search(inline_text(_current(block))):
        msg = f"unsupported control character: {block.id}"
        raise ValueError(msg)
    if block.kind == "figure" and (
        not block.asset_path or not (asset_root / block.asset_path).exists()
    ):
        msg = f"unresolved figure asset: {block.id}"
        raise ValueError(msg)
    if block.kind == "table":
        _validate_table(block)
    _validate_links(block, anchors)


def _validate_cell_images(document: Document, asset_root: Path) -> None:
    """セル画像の一意所有、有限pt寸法と領域内assetを公開直前にも確認する。"""

    owned = {
        block.id
        for page in document.pages
        for block in page.blocks
        if block.kind == "figure"
    }
    root = asset_root.resolve()
    for page in document.pages:
        for block in page.blocks:
            for cell in block.cells:
                for image in cell.images:
                    path = (root / image.asset_path).resolve()
                    if (
                        image.id in owned
                        or not image.asset_path.startswith("assets/")
                        or not path.is_relative_to(root)
                        or not path.is_relative_to(root / "assets")
                        or not path.is_file()
                        or not all(
                            math.isfinite(value) and value > 0
                            for value in (image.width_pt, image.height_pt)
                        )
                    ):
                        raise ValueError("invalid cell image ownership or asset")
                    owned.add(image.id)


def validate_document(document: Document, asset_root: Path) -> None:
    """本文の制御文字、図assetの存在、表の位置・spanと内部linkを検査する。

    Args:
        document: 検証する文書。
        asset_root: 相対assetの基準directory。

    Returns:
        なし。

    Raises:
        ValueError: 本文の制御文字、欠損asset、表shapeまたは内部linkが不正な場合。
    """

    _validate_cell_images(document, asset_root)
    # link検証より先に全ページの見出しを集め、後方参照も正しく解決する。
    anchors = {
        _anchor(block.id)
        for page in document.pages
        for block in page.blocks
        if block.kind == "heading"
    }
    for page in document.pages:
        for block in page.blocks:
            _validate_block(block, asset_root, anchors)


def render_document(
    document: Document,
    cover_path: Path | None = None,
    excluded_pages: set[int] | None = None,
) -> str:
    """文書全体を表紙付きPandoc Markdownへ変換する。

    Args:
        document: 変換する正規化済み文書。
        cover_path: 任意の表紙画像path。
        excluded_pages: 本文から除くページ番号。表紙pathだけでは本文を除外しない。

    Returns:
        UTF-8 Markdown文字列。
    """

    parts: list[tuple[str, bool]] = []
    if cover_path is not None:
        # 標準escaped spaceで表紙を通常Imageにし、本文Figureの採番を消費させない。
        parts.extend(
            [
                (f"![表紙]({_escape(cover_path.as_posix())}){{width=100%}}\\ ", False),
                ("```{=openxml}", False),
                ('<w:p><w:r><w:br w:type="page"/></w:r></w:p>', False),
                ("```", False),
            ]
        )
    excluded_pages = excluded_pages or set()
    for page in document.pages:
        if page.number in excluded_pages:
            continue
        for block in sorted(page.blocks, key=lambda value: value.order):
            rendered = render_block(block)
            if rendered:
                parts.append((rendered, block.kind == "list_item"))
    if not parts:
        return "\n"
    # 連続する項目間だけ段落境界を作らず、一つのMarkdown listとして渡す。
    result = parts[0][0]
    for (_, previous_list), (current, current_list) in itertools.pairwise(parts):
        result += ("\n" if previous_list and current_list else "\n\n") + current
    return result + "\n"


def _run_into(
    document: Document,
    output: Path,
    cover_path: Path | None = None,
    asset_root: Path | None = None,
) -> Path:
    """Internal DocumentをMarkdownとして保存する。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    # Note 1: Pandoc resolves relative image paths from the Markdown directory.
    if asset_root is not None and (asset_root / "assets").exists():
        shutil.copytree(
            asset_root / "assets", output.parent / "assets", dirs_exist_ok=True
        )
    excluded_pages: set[int] = set()
    if cover_path is not None:
        manifest_path = cover_path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        excluded_pages = {int(value) for value in manifest["excluded_pages"]}
    atomic_write_text(output, render_document(document, cover_path, excluded_pages))
    return output


class MarkdownTask(BaseTask):
    """Execute MARKDOWN while sharing elapsed-time measurement only."""

    name = "MARKDOWN"

    def run(
        self,
        document: Document,
        output: Path,
        cover_path: Path | None = None,
        asset_root: Path | None = None,
    ) -> Path:
        """Markdownとresource directoryをまとめてatomic公開する。"""

        with self.measure():
            validate_document(document, asset_root or output.parent)
            with atomic_directory(output.parent) as temporary:
                _run_into(document, temporary / output.name, cover_path, asset_root)
            return output


def run(
    document: Document,
    output: Path,
    cover_path: Path | None = None,
    asset_root: Path | None = None,
) -> Path:
    """Existing function delegates to the typed MarkdownTask operation."""

    return MarkdownTask().run(document, output, cover_path, asset_root)
