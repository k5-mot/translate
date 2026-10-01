"""全Taskが共有する文書モデル。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

if TYPE_CHECKING:
    from collections.abc import Iterator

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
            str: 指定層までの値をrevised、translated、sourceの順で選ぶ。
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
            str: Spanの改行種別を保ちながら指定層のplain textを返す。
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
    """表内の結合範囲起点となる一つのセル。"""

    id: str = Field(min_length=1)
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    rowspan: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)
    header: bool = False
    content: TextUnit
    images: list[Image] = Field(default_factory=list)


class Block(DocumentModel):
    """ページ内の一つの意味構造要素。"""

    id: str = Field(min_length=1)
    order: int = Field(ge=0)
    kind: BlockKind
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


def iter_text_units(document: Document) -> Iterator[tuple[str, TextUnit]]:
    """文書内の本文、見出し、Captionおよび表セルを読み順で列挙する。

    Args:
        document (Document): 変換または検証対象のDocument。

    Yields:
        tuple[str: 文書内の本文、見出し、Captionおよび表セルを読み順で列挙する。
    """

    for page in sorted(document.pages, key=lambda item: item.number):
        for block in sorted(page.blocks, key=lambda item: item.order):
            if block.content is not None:
                role = "heading" if block.kind == "heading" else "body"
                yield role, block.content
            if block.caption is not None:
                yield "caption", block.caption
            if block.image is not None and block.image.caption is not None:
                yield "caption", block.image.caption
            for cell in sorted(block.cells, key=lambda item: (item.row, item.column)):
                yield "table_cell", cell.content
                for image in cell.images:
                    if image.caption is not None:
                        yield "caption", image.caption


def text_unit_index(document: Document) -> dict[str, TextUnit]:
    """FIXと検証で使用するTextUnit IDの索引を作る。

    Args:
        document (Document): 変換または検証対象のDocument。

    Returns:
        dict[str, TextUnit]: FIXと検証で使用するTextUnit IDの索引を作る。
    """

    return {unit.id: unit for _, unit in iter_text_units(document)}
