"""DocumentをPandoc Markdownへ変換するMARKDOWN Task。"""

from __future__ import annotations

import html
import re
import shutil
from typing import TYPE_CHECKING

from translate.adapters.pandoc import table_to_markdown
from translate.artifact_store import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from translate.models.document import Block, Document, TableCell, TextSpan, TextUnit

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ALERT_STYLES = {
    "note": "Note / 注記",
    "tip": "Tip / ヒント",
    "important": "Important / 重要",
    "warning": "Warning / 警告",
    "caution": "Caution / 注意",
}


def convert_document(
    document: Document,
    output: Path,
    cover_image: Path,
    asset_root: Path,
    excluded_pages: set[int],
    pandoc_timeout: float,
) -> Path:
    """表紙とassetを含む一つのPandoc Markdown成果を作る。

    Args:
        document (Document): 変換または検証対象のDocument。
        output (Path): 変換結果を書き込むFile Path。
        cover_image (Path): Markdownへ埋め込む表紙画像Path。
        asset_root (Path): 参照先Assetを検証するRoot Directory。
        excluded_pages (set[int]): Markdown出力から除外するPage番号集合。
        pandoc_timeout (float): Pandoc ProcessのTimeout秒数。

    Returns:
        Path: 表紙とassetを含む一つのPandoc Markdown成果を作る。
    """

    output.parent.mkdir(parents=True, exist_ok=True)
    cover_target = output.parent / "assets" / "cover.png"
    cover_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cover_image, cover_target)
    fragments = [
        '![](assets/cover.png){width=100% fig-alt="表紙"}',
        '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:r><w:br w:type="page"/></w:r></w:p>',
    ]
    for page in document.pages:
        if page.number in excluded_pages:
            continue
        fragments.extend(
            convert_block(block, pandoc_timeout)
            for block in sorted(page.blocks, key=lambda item: item.order)
        )
    for source in sorted(asset_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(asset_root)
        if not relative.parts or relative.parts[0] != "assets":
            continue
        target = output.parent / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    value = "\n\n".join(fragment for fragment in fragments if fragment).rstrip()
    atomic_write_text(output, f"{value}\n")
    return output


def convert_block(block: Block, pandoc_timeout: float) -> str:  # noqa: PLR0911
    """一つのBlockをPandoc Markdown断片へ変換する。

    Args:
        block (Block): 変換または検証対象のDocument Block。
        pandoc_timeout (float): Pandoc ProcessのTimeout秒数。

    Returns:
        str: 一つのBlockをPandoc Markdown断片へ変換する。
    """

    text = convert_text_unit(block.content) if block.content is not None else ""
    if block.kind == "heading":
        return (
            f"{'#' * max(1, min(6, block.level or 1))} {text} {{#{_anchor(block.id)}}}"
        )
    if block.kind == "list_item":
        marker = "1." if block.ordered else "-"
        task = "" if block.checked is None else f"[{'x' if block.checked else ' '}] "
        return f"{'    ' * max(0, (block.level or 1) - 1)}{marker} {task}{text}"
    if block.kind == "blockquote":
        return "\n".join(f"> {line}" for line in text.splitlines())
    if block.kind == "alert":
        kind = block.alert_kind or "note"
        label = kind.upper()
        return f'::: {{custom-style="{_ALERT_STYLES[kind]}"}}\n**{label}:** {text}\n:::'
    if block.kind == "code":
        raw = block.content.text() if block.content is not None else ""
        longest = max((len(value) for value in re.findall(r"`+", raw)), default=0)
        fence = "`" * max(3, longest + 1)
        return f"{fence}{block.language or ''}\n{raw}\n{fence}"
    if block.kind == "formula":
        return f"$$\n{block.content.text() if block.content else ''}\n$$"
    if block.kind == "figure" and block.image is not None:
        caption = convert_text_unit(block.image.caption) if block.image.caption else ""
        alt = html.escape(block.image.alt_text, quote=True)
        return f'![{caption}]({_escape_url(block.image.asset_path)}){{fig-alt="{alt}"}}'
    if block.kind == "table":
        return _convert_table(block, pandoc_timeout)
    if block.kind == "footnote":
        anchor = _anchor(block.id)
        return f"[^{anchor}]\n\n[^{anchor}]: {text}"
    if block.kind == "horizontal_rule":
        return "---"
    return text


def convert_text_unit(unit: TextUnit | None) -> str:
    """TextUnitの最終層と書式をPandoc inline記法へ変換する。

    Args:
        unit (TextUnit | None): 変換または検証対象のTextUnit。

    Returns:
        str: TextUnitの最終層と書式をPandoc inline記法へ変換する。
    """

    if unit is None:
        return ""
    return "".join(_convert_span(span) for span in unit.spans)


def _convert_span(span: TextSpan) -> str:
    """一つのTextSpanをescapeし、linkとmarkを適用する。

    Args:
        span (TextSpan): 変換またはPayload作成対象のTextSpan。

    Returns:
        str: 一つのTextSpanをescapeし、linkとmarkを適用する。
    """

    if span.kind == "line_break":
        return "  \n"
    raw = _CONTROL.sub("", span.text())
    value = f"`{raw.replace('`', '``')}`" if span.kind == "code" else _escape(raw)
    wrappers = {
        "strong": ("**", "**"),
        "emphasis": ("*", "*"),
        "strikethrough": ("~~", "~~"),
        "underline": ("[", ']{custom-style="Underline"}'),
        "subscript": ("~", "~"),
        "superscript": ("^", "^"),
    }
    for mark in span.marks:
        prefix, suffix = wrappers[mark]
        value = f"{prefix}{value}{suffix}"
    if span.kind == "link":
        value = f"[{value}]({_escape_url(span.href or '')})"
    return value


def _convert_table(block: Block, timeout: float) -> str:
    """TableCellをPandoc ASTへ対応付けてgrid tableを得る。

    Args:
        block (Block): 変換または検証対象のDocument Block。
        timeout (float): 外部処理のTimeout秒数。

    Returns:
        str: TableCellをPandoc ASTへ対応付けてgrid tableを得る。
    """

    if not block.cells:
        return ""
    columns = max(cell.column + cell.colspan for cell in block.cells)
    row_count = max(cell.row + cell.rowspan for cell in block.cells)
    rows = [_table_row(block.cells, row, columns) for row in range(row_count)]
    header_rows = 0
    for row in range(row_count):
        covering = [
            cell for cell in block.cells if cell.row <= row < cell.row + cell.rowspan
        ]
        if not covering or not all(cell.header for cell in covering):
            break
        header_rows += 1
    table = {
        "t": "Table",
        "c": [
            ["", [], []],
            [None, [_pandoc_plain(block.caption)] if block.caption else []],
            [[{"t": "AlignDefault"}, {"t": "ColWidthDefault"}] for _ in range(columns)],
            [["", [], []], rows[:header_rows]],
            [[["", [], []], 0, [], rows[header_rows:]]],
            [["", [], []], []],
        ],
    }
    return table_to_markdown(table, timeout)


def _table_row(cells: list[TableCell], row: int, columns: int) -> list[object]:
    """指定行の開始cellだけをPandoc Rowへ変換する。

    Args:
        cells (list[TableCell]): Markdownの一行へ配置するTable Cell列。
        row (int): Pandoc Rowへ変換するTableのRow番号。
        columns (int): 出力TableのColumn数。

    Returns:
        list[object]: 指定行の開始cellだけをPandoc Rowへ変換する。
    """

    starts = {cell.column: cell for cell in cells if cell.row == row}
    occupied = {
        column
        for cell in cells
        if cell.row <= row < cell.row + cell.rowspan
        for column in range(cell.column, cell.column + cell.colspan)
    }
    result: list[object] = []
    for column in range(columns):
        cell = starts.get(column)
        if cell is None and column in occupied:
            continue
        result.append(
            [
                ["", [], []],
                {"t": "AlignDefault"},
                cell.rowspan if cell else 1,
                cell.colspan if cell else 1,
                [_pandoc_plain(cell.content)] if cell else [],
            ]
        )
    return [["", [], []], result]


def _pandoc_plain(unit: TextUnit | None) -> dict[str, object]:
    """TextUnitを表cell用の単純なPandoc Plainへ変換する。

    Args:
        unit (TextUnit | None): 変換または検証対象のTextUnit。

    Returns:
        dict[str, object]: TextUnitを表cell用の単純なPandoc Plainへ変換する。
    """

    text = unit.text() if unit is not None else ""
    return {"t": "Plain", "c": [{"t": "Str", "c": text}] if text else []}


def _escape(value: str) -> str:
    """plain textとして解釈させるMarkdown制御文字をescapeする。

    Args:
        value (str): Markdown制御文字をEscapeするPlain Text。

    Returns:
        str: plain textとして解釈させるMarkdown制御文字をescapeする。
    """

    return re.sub(r"([\\`*{}\[\]()#+.!_|>~-])", r"\\\1", value)


def _escape_url(value: str) -> str:
    """Markdown link target内の空白と括弧をpercent表記にする。

    Args:
        value (str): Percent EncodeするMarkdown Link Target。

    Returns:
        str: Markdown link target内の空白と括弧をpercent表記にする。
    """

    return value.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _anchor(value: str) -> str:
    """Document IDをPandocで安全なanchorへ変換する。

    Args:
        value (str): Pandoc Anchorへ変換するDocument ID。

    Returns:
        str: Document IDをPandocで安全なanchorへ変換する。
    """

    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "item"
