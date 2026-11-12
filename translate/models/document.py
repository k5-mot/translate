"""全Taskが共有する文書モデル。"""

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

TextKind = Literal["text", "code", "link", "line_break"]
TextMark = Literal[
    "strong",
    "emphasis",
    "strikethrough",
    "underline",
    "subscript",
    "superscript",
]
BlockKind = Literal[
    "paragraph",
    "heading",
    "blockquote",
    "list_item",
    "alert",
    "code",
    "formula",
    "figure",
    "table",
    "footnote",
    "horizontal_rule",
]
AlertKind = Literal["note", "tip", "important", "warning", "caution"]
TextLayer = Literal["source", "translated", "revised"]


class DocumentModel(BaseModel):
    """未知fieldを無視する文書モデルの共通設定。"""

    model_config = ConfigDict(extra="ignore")


class TextSpan(DocumentModel):
    """書式と参照先を共有する最小の翻訳単位。"""

    id: str = Field(min_length=1)
    kind: TextKind = "text"
    source: str = ""
    translated: str | None = None
    revised: str | None = None
    marks: list[TextMark] = Field(default_factory=list)
    href: str | None = None

    def text(self, layer: TextLayer = "revised") -> str:
        """指定層までの値をrevised、translated、sourceの順で選ぶ。

        Args:
            layer (TextLayer): 取得するTextの優先Layer。

        Returns:
            str: 最も後の層に値があるText。
        """

        if layer == "revised" and self.revised is not None:
            return self.revised
        if layer != "source" and self.translated is not None:
            return self.translated
        return self.source


class TextUnit(DocumentModel):
    """本文、Captionまたは表セル内の書式付き文字列。"""

    id: str = Field(min_length=1)
    spans: list[TextSpan] = Field(default_factory=list)

    def text(self, layer: TextLayer = "revised") -> str:
        """Spanの改行種別を保ちながら指定層のplain textを返す。

        Args:
            layer (TextLayer): 取得するTextの優先Layer。

        Returns:
            str: Span順に連結したText。line_breakは改行になる。
        """

        return "".join(
            "\n" if span.kind == "line_break" else span.text(layer)
            for span in self.spans
        )


class Image(DocumentModel):
    """文書assetと任意のCaptionを参照する画像。"""

    id: str = Field(min_length=1)
    asset_path: str = Field(min_length=1)
    alt_text: str = ""
    width_pt: float | None = None
    height_pt: float | None = None
    caption: TextUnit | None = None


class TableCell(DocumentModel):
    """結合を展開した通常gridの一つのセル。"""

    id: str = Field(min_length=1)
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    header: bool = False
    content: TextUnit
    images: list[Image] = Field(default_factory=list)


class Block(DocumentModel):
    """ページ内の一つの意味構造要素。"""

    id: str = Field(min_length=1)
    order: int = Field(ge=0)
    kind: BlockKind
    # LOADは表示ページの左上原点へ正規化し、left/top/right/bottomをptで保持する。
    bbox: tuple[float, float, float, float] | None = None
    content: TextUnit | None = None
    caption: TextUnit | None = None
    image: Image | None = None
    cells: list[TableCell] = Field(default_factory=list)
    level: int | None = None
    ordered: bool = False
    checked: bool | None = None
    language: str | None = None
    alert_kind: AlertKind | None = None


class Page(DocumentModel):
    """PDFの一ページと読み順に並ぶBlock。"""

    number: int = Field(ge=1)
    width: float | None = None
    height: float | None = None
    blocks: list[Block] = Field(default_factory=list)


class Document(DocumentModel):
    """翻訳工程で共有し、JSONとして永続化する文書。"""

    schema_version: Literal[1] = 1
    pages: list[Page] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    def text_units(self) -> Iterator[tuple[str, TextUnit]]:
        """文書内の本文、見出し、Captionおよび表セルを読み順で列挙する。

        Yields:
            tuple[str, TextUnit]: 文書内の本文、見出し、Captionおよび表セルを読み順で列挙する。
        """

        for page in sorted(self.pages, key=lambda item: item.number):
            for block in sorted(page.blocks, key=lambda item: item.order):
                if block.content is not None:
                    role = "heading" if block.kind == "heading" else "body"
                    yield role, block.content
                if block.caption is not None:
                    yield "caption", block.caption
                if block.image is not None and block.image.caption is not None:
                    yield "caption", block.image.caption
                for cell in sorted(
                    block.cells, key=lambda item: (item.row, item.column)
                ):
                    yield "table_cell", cell.content
                    for image in cell.images:
                        if image.caption is not None:
                            yield "caption", image.caption

    def unit_index(self) -> dict[str, TextUnit]:
        """FIXと検証で使用するTextUnit IDの索引を作る。

        Returns:
            dict[str, TextUnit]: TextUnit IDからTextUnitへの索引。
        """

        return {unit.id: unit for _, unit in self.text_units()}

    def unit_contexts(self) -> dict[str, dict[str, str]]:
        """照合対象の種別、節、表の行・列見出しと隣接行を本文とは別に取得する。

        Returns:
            TextUnit IDごとの構造上の文脈。位置は候補順位の補助情報としてのみ含む。
        """
        contexts: dict[str, dict[str, str]] = {}
        section = ""
        pages = sorted(self.pages, key=lambda item: item.number)
        last_page = max((page.number for page in pages), default=1)
        for page in pages:
            position = str((page.number - 1) / max(1, last_page - 1))
            for block in sorted(page.blocks, key=lambda item: item.order):
                if block.kind == "heading" and block.content is not None:
                    section = block.content.text("source")
                base = {"position": position}
                if section:
                    base["section"] = section
                if block.content is not None:
                    contexts[block.content.id] = {**base, "kind": block.kind}
                captions = [block.caption]
                if block.image is not None:
                    captions.append(block.image.caption)
                for caption in captions:
                    if caption is not None:
                        contexts[caption.id] = {**base, "kind": "caption"}
                cells = sorted(block.cells, key=lambda item: (item.row, item.column))
                rows = sorted({cell.row for cell in cells})
                header_rows = {cell.row for cell in cells if cell.header}
                table_row_labels: dict[int, str] = {}
                for value in cells:
                    text = value.content.text("source").strip()
                    if text and any(character.isalnum() for character in text):
                        table_row_labels.setdefault(value.row, text)
                previous_rows = {
                    row: rows[index - 1] if index else None
                    for index, row in enumerate(rows)
                }
                following_rows = {
                    row: rows[index + 1] if index + 1 < len(rows) else None
                    for index, row in enumerate(rows)
                }
                for cell in cells:
                    # Ignore decorative bullets so the text label identifies the row.
                    row_labels = [
                        value.content.text("source")
                        for value in cells
                        if value.row == cell.row
                        and value.column < cell.column
                        and value.content.text("source").strip()
                        and any(
                            character.isalnum()
                            for character in value.content.text("source")
                        )
                    ]
                    headers = [
                        value.content.text("source")
                        for value in cells
                        if value.header
                        and value.column == cell.column
                        and value.row == cells[0].row
                        and value.row < cell.row
                        and value.content.text("source").strip()
                    ]
                    adjacent_rows = [
                        f"{direction}: {table_row_labels[row]}"
                        for direction, row in (
                            ("previous", previous_rows[cell.row]),
                            ("next", following_rows[cell.row]),
                        )
                        if row is not None
                        and row not in header_rows
                        and row in table_row_labels
                    ]
                    contexts[cell.content.id] = {
                        **base,
                        "kind": "table_cell",
                        **({"row_label": row_labels[0]} if row_labels else {}),
                        **({"column_label": headers[-1]} if headers else {}),
                        **(
                            {"adjacent_row_labels": " | ".join(adjacent_rows)}
                            if adjacent_rows
                            else {}
                        ),
                    }
                    for image in cell.images:
                        if image.caption is not None:
                            contexts[image.caption.id] = {**base, "kind": "caption"}
        return contexts
