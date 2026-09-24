"""翻訳と査読で共有する内部文書モデルを定義する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterator

InlineKind = Literal["text", "code", "link", "line_break"]
InlineMark = Literal[
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
    "list_item",
    "blockquote",
    "alert",
    "code",
    "formula",
    "table",
    "figure",
    "footnote",
    "horizontal_rule",
]
AlertKind = Literal["note", "tip", "important", "warning", "caution"]


class Inline(BaseModel):
    """段落内の文字列と保護対象または装飾を表す。"""

    id: str
    text: str = ""
    kind: InlineKind = "text"
    marks: list[InlineMark] = Field(default_factory=list)
    href: str | None = None
    translated_text: str | None = None
    fixed_text: str | None = None
    fix_status: Literal["unchanged", "fixed", "skipped"] = "unchanged"
    fix_error: str | None = None


class TableCell(BaseModel):
    """表内の一つのセルと翻訳状態を表す。"""

    row: int
    column: int
    rowspan: int = 1
    colspan: int = 1
    header: bool = False
    source: list[Inline] = Field(default_factory=list)
    translated: list[Inline] | None = None
    final: list[Inline] | None = None


class Block(BaseModel):
    """ページ内の意味構造を持つ一つの要素を表す。"""

    id: str
    order: int
    kind: BlockKind
    bbox: tuple[float, float, float, float] | None = None
    source: list[Inline] = Field(default_factory=list)
    translated: list[Inline] | None = None
    final: list[Inline] | None = None
    level: int | None = None
    ordered: bool = False
    checked: bool | None = None
    language: str | None = None
    alert_kind: AlertKind | None = None
    asset_path: str | None = None
    alt_text: str | None = None
    caption: list[Inline] = Field(default_factory=list)
    translated_caption: list[Inline] | None = None
    final_caption: list[Inline] | None = None
    cells: list[TableCell] = Field(default_factory=list)


class Page(BaseModel):
    """PDFの一ページとその文書要素を表す。"""

    number: int
    width: float | None = None
    height: float | None = None
    blocks: list[Block] = Field(default_factory=list)


class Document(BaseModel):
    """翻訳工程が共有する正規化済み文書全体を表す。"""

    pages: list[Page] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    assets: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """原文と訳文の一つの問題指摘。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    severity: Literal["info", "warning", "error"] = "warning"
    target_ids: list[str] = Field(default_factory=list)
    message: str
    evidence: str | None = None
    suggestion: str | None = None


class AlignmentGroup(BaseModel):
    """比較文書間の多対多対応。"""

    source_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    kind: Literal["matched", "source_only", "target_only"] = "matched"
    confidence: float = 1.0


def inline_text(values: list[Inline]) -> str:
    """Inline列から検索やLLM入力に使うplain textを作る。

    Args:
        values: 連結するInline列。

    Returns:
        改行を含めて連結した文字列。
    """

    return "".join("\n" if item.kind == "line_break" else item.text for item in values)


@dataclass(frozen=True)
class TextUnit:
    """本文・caption・セルの既存翻訳層を参照する非永続の検査単位。"""

    id: str
    source: list[Inline]
    translated: list[Inline] | None
    final: list[Inline] | None

    def text(self, layer: Literal["source", "translated", "final"]) -> str:
        """未作成の層だけを前層で補い、空訳や空の修正候補は保持する。"""

        values = self.source
        if layer != "source" and self.translated is not None:
            values = self.translated
        if layer == "final" and self.final is not None:
            values = self.final
        return inline_text(values)


def block_text_units(block: Block) -> Iterator[TextUnit]:
    """本文・caption・行列順のセルを、結合セルの起点につき一度列挙する。"""

    units = [
        TextUnit(block.id, block.source, block.translated, block.final),
        TextUnit(
            f"{block.id}/caption",
            block.caption,
            block.translated_caption,
            block.final_caption,
        ),
    ]
    units.extend(
        TextUnit(
            f"{block.id}/cell/{cell.row}/{cell.column}",
            cell.source,
            cell.translated,
            cell.final,
        )
        # 結合範囲へ展開せず、保存済みの起点セルだけを読む。
        for cell in sorted(block.cells, key=lambda cell: (cell.row, cell.column))
    )
    for unit in units:
        if unit.source or unit.translated or unit.final:
            yield unit


def block_text(block: Block, *, final: bool = True) -> str:
    """Blockから利用可能な最新のplain textを返す。

    Args:
        block: 対象Block。
        final: FIX/VERIFY後の最終採用訳を優先するかどうか。

    Returns:
        最終採用訳、初回訳、原文の優先順で選んだ文字列。
    """

    values = (
        block.final
        if final and block.final is not None
        else block.translated
        if block.translated is not None
        else block.source
    )
    return inline_text(values)


def page_text(page: Page, *, final: bool = True) -> str:
    """ページ内Blockを文書順にplain textへ連結する。

    Args:
        page: 対象ページ。
        final: FIX/VERIFY後の最終採用訳を優先するかどうか。

    Returns:
        空要素を除いて改行連結したページ本文。
    """

    return "\n".join(
        text
        for block in sorted(page.blocks, key=lambda item: item.order)
        if (text := block_text(block, final=final))
    )
