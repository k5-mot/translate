"""DocumentをPandoc Markdownへ変換するMARKDOWN Task。"""

import html
import re
import shutil
from collections import Counter
from pathlib import Path

from translate.adapters.artifact_store import atomic_write_text
from translate.adapters.pandoc import Pandoc
from translate.models.document import (
    Block,
    Document,
    Page,
    TableCell,
    TextSpan,
    TextUnit,
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# PandocとWordが採番する要素だけ、出力用の本文から元の番号を除く。
_HEADING_NUMBER = re.compile(r"^\s*(?:[0-9]{1,3}|[0-9]+\.|[0-9]+(?:\.[0-9]+)+\.?)\s+")
_CAPTION_NUMBER = re.compile(
    r"^\s*(?:Figure|Fig\.|Table|図|表)\s*[0-9]+(?:\.[0-9]+)*"
    r"(?:\s*[:\uFF1A]\s*|\.(?:\s+|$)|\s+|$)",
    re.IGNORECASE,
)
_FOOTNOTE_NUMBER = re.compile(r"^\s*([0-9]+|[*†‡]+)\s+")
_ALERT_STYLES = {
    "note": "Note / 注記",
    "tip": "Tip / ヒント",
    "important": "Important / 重要",
    "warning": "Warning / 警告",
    "caution": "Caution / 注意",
}


class MarkdownTask:
    """文書全体でPandoc接続設定を共有し、画像を含むMarkdownを生成する。"""

    def __init__(self, pandoc: Pandoc) -> None:
        """表構造の変換に利用するPandocを受け取る。

        Args:
            pandoc: Timeoutと機能確認結果を保持する変換Adapter。
        """
        self.pandoc = pandoc
        self.footnote_references: dict[str, str] = {}

    def run(
        self,
        document: Document,
        output: Path,
        cover_image: Path,
        asset_root: Path,
        excluded_pages: set[int],
    ) -> Path:
        """表紙とassetを含む一つのPandoc Markdown成果を作る。

        Args:
            document (Document): 変換または検証対象のDocument。
            output (Path): 変換結果を書き込むFile Path。
            cover_image (Path): Markdownへ埋め込む表紙画像Path。
            asset_root (Path): 参照先Assetを検証するRoot Directory。
            excluded_pages (set[int]): Markdown出力から除外するPage番号集合。

        Returns:
            Path: 表紙とassetを含む一つのPandoc Markdown成果を作る。
        """

        output.parent.mkdir(parents=True, exist_ok=True)
        cover_target = output.parent / "assets" / "cover.png"
        cover_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cover_image, cover_target)
        fragments = [
            '![](assets/cover.png){width=100% fig-alt="表紙"}',
            '```{=openxml}\n<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:r><w:br w:type="page"/></w:r></w:p>\n```',
        ]
        for page in document.pages:
            if page.number in excluded_pages:
                continue
            self._link_footnotes(page)
            fragments.extend(
                self.convert_block(block)
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

    def _link_footnotes(self, page: Page) -> None:
        """同じページで一意に対応する元番号と独立した本文参照だけを結び付ける。

        Args:
            page: 脚注と参照元を含む公開対象ページ。
        """
        self.footnote_references = {}
        notes = [
            (block, block.content, match)
            for block in page.blocks
            if block.kind == "footnote" and block.content is not None
            if (match := _FOOTNOTE_NUMBER.match(block.content.text("source")))
        ]
        counts = Counter(match[1] for _, _, match in notes)
        for note, content, marker in notes:
            current = _FOOTNOTE_NUMBER.match(content.text())
            if counts[marker[1]] != 1 or not current or current[1] != marker[1]:
                continue
            candidates = [
                span
                for block in page.blocks
                if block.kind not in {"footnote", "code", "formula"}
                and block.content is not None
                for index, span in enumerate(block.content.spans)
                if span.kind == "text"
                and (index > 0 or "superscript" in span.marks)
                and span.source.strip() == span.text().strip() == marker[1]
            ]
            if len(candidates) == 1:
                self.footnote_references[candidates[0].id] = _anchor(note.id)

    def convert_block(self, block: Block) -> str:  # noqa: PLR0911
        """一つのBlockをPandoc Markdown断片へ変換する。

        Args:
            block (Block): 変換または検証対象のDocument Block。

        Returns:
            str: 一つのBlockをPandoc Markdown断片へ変換する。
        """

        text = convert_text_unit(block.content, self.footnote_references)
        if block.kind == "heading":
            text = convert_text_unit(
                _without_number(block.content, _HEADING_NUMBER),
                self.footnote_references,
            )
            return f"{'#' * max(1, min(6, block.level or 1))} {text} {{#{_anchor(block.id)}}}"
        if block.kind == "list_item":
            marker = "1." if block.ordered else "-"
            task = (
                "" if block.checked is None else f"[{'x' if block.checked else ' '}] "
            )
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
            caption = convert_text_unit(
                _without_number(block.image.caption, _CAPTION_NUMBER)
            )
            alt = html.escape(block.image.alt_text, quote=True)
            return f'![{caption}]({_escape_url(block.image.asset_path)}){{fig-alt="{alt}"}}'
        if block.kind == "table":
            return self._convert_table(block)
        if block.kind == "footnote":
            anchor = _anchor(block.id)
            if anchor in self.footnote_references.values():
                text = convert_text_unit(
                    _without_number(block.content, _FOOTNOTE_NUMBER)
                )
                return f"[^{anchor}]: " + text.replace("\n", "\n    ")
            # shortcut: 参照が曖昧な脚注は元番号付き段落を保持し、抽出で参照を特定できたら脚注化する。
            return f'::: {{custom-style="Footnote Block Text"}}\n{text}\n:::'
        if block.kind == "horizontal_rule":
            return "---"
        return text

    def _convert_table(self, block: Block) -> str:
        """TableCellをPandoc ASTへ対応付けてgrid tableを得る。

        Args:
            block (Block): 変換または検証対象のDocument Block。

        Returns:
            str: TableCellをPandoc ASTへ対応付けてgrid tableを得る。
        """

        if not block.cells:
            return ""
        columns = max(cell.column + 1 for cell in block.cells)
        row_count = max(cell.row + 1 for cell in block.cells)
        rows = [_table_row(block.cells, row, columns) for row in range(row_count)]
        header_rows = 0
        for row in range(row_count):
            covering = [cell for cell in block.cells if cell.row <= row < cell.row + 1]
            if not covering or not all(cell.header for cell in covering):
                break
            header_rows += 1
        table = {
            "t": "Table",
            "c": [
                ["", [], []],
                [
                    None,
                    [_pandoc_plain(_without_number(block.caption, _CAPTION_NUMBER))]
                    if block.caption
                    else [],
                ],
                [
                    [{"t": "AlignDefault"}, {"t": "ColWidthDefault"}]
                    for _ in range(columns)
                ],
                [["", [], []], rows[:header_rows]],
                [[["", [], []], 0, [], rows[header_rows:]]],
                [["", [], []], []],
            ],
        }
        return self.pandoc.table_to_markdown(table)


def _without_number(unit: TextUnit | None, pattern: re.Pattern[str]) -> TextUnit | None:
    """採番接頭辞を除いた出力用の複製を作り、残りのSpan書式を保つ。

    Args:
        unit: 原文・訳文を変更せずに公開する見出しまたはCaption。
        pattern: 出力側で採番される接頭辞の正規表現。

    Returns:
        TextUnit | None: 一致した接頭辞を除いた複製。一致しなければ入力。
    """
    prefix = pattern.match(unit.text()) if unit is not None else None
    if prefix is None or unit is None:
        return unit
    content = unit.model_copy(deep=True)
    remaining = prefix.end()
    spans = []
    for span in content.spans:
        value = "\n" if span.kind == "line_break" else span.text()
        if remaining >= len(value):
            remaining -= len(value)
            continue
        if remaining:
            span.revised = value[remaining:]
            remaining = 0
        spans.append(span)
    content.spans = spans
    return content


def convert_text_unit(
    unit: TextUnit | None, footnote_references: dict[str, str] | None = None
) -> str:
    """TextUnitの最終層と書式をPandoc inline記法へ変換する。

    Args:
        unit (TextUnit | None): 変換または検証対象のTextUnit。
        footnote_references: 本文Span IDと一意に対応した脚注anchor。

    Returns:
        str: TextUnitの最終層と書式をPandoc inline記法へ変換する。
    """

    if unit is None:
        return ""
    references = footnote_references or {}
    return "".join(
        f"[^{references[span.id]}]" if span.id in references else _convert_span(span)
        for span in unit.spans
    )


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


def _table_row(cells: list[TableCell], row: int, columns: int) -> list[object]:
    """指定行の全cellを結合なしのPandoc Rowへ変換する。

    Args:
        cells (list[TableCell]): Markdownの一行へ配置するTable Cell列。
        row (int): Pandoc Rowへ変換するTableのRow番号。
        columns (int): 出力TableのColumn数。

    Returns:
        list[object]: 指定行の全cellを結合なしのPandoc Rowへ変換する。
    """

    starts = {cell.column: cell for cell in cells if cell.row == row}
    result: list[object] = []
    for column in range(columns):
        cell = starts.get(column)
        result.append(
            [
                ["", [], []],
                {"t": "AlignDefault"},
                1,
                1,
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
    text = re.sub(r"\s+[.…。]{6,}\s*$", "", text)
    # Pandocは単独のem dashを---へ変換し、次の変換で水平線として解釈する。
    if text == "—":
        text = "-"
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
