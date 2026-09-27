"""最終Documentとassetの構造を検査するLINT Task。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from translate.artifact_store import canonical_hash
from translate.models.artifacts import LintDiagnostic, LintResult

if TYPE_CHECKING:
    from translate.models.document import Block, Document, Image, TextUnit


def lint(document: Document, asset_root: Path) -> LintResult:
    """公開に必要な構造条件を検査し、すべての診断を返す。"""

    diagnostics: list[LintDiagnostic] = []
    ids: dict[str, str] = {}
    page_numbers = [page.number for page in document.pages]
    if page_numbers != sorted(set(page_numbers)):
        _add(
            diagnostics, "page_order", "pages", "Page番号が昇順かつ一意ではありません。"
        )
    for page_index, page in enumerate(document.pages):
        orders = [block.order for block in page.blocks]
        if orders != sorted(set(orders)):
            _add(
                diagnostics,
                "block_order",
                f"pages/{page_index}/blocks",
                "Blockのorderが昇順かつ一意ではありません。",
            )
        for block_index, block in enumerate(page.blocks):
            path = f"pages/{page_index}/blocks/{block_index}"
            _record_id(ids, block.id, "Block", path, diagnostics)
            _validate_block(block, path, ids, asset_root, diagnostics)
    return LintResult(
        valid=not diagnostics,
        document_sha256=canonical_hash(document),
        diagnostics=diagnostics,
    )


def _validate_block(
    block: Block,
    path: str,
    ids: dict[str, str],
    asset_root: Path,
    diagnostics: list[LintDiagnostic],
) -> None:
    """一つのBlockが種類別の必須fieldと内部制約を満たすか検査する。"""

    content_kinds = {
        "paragraph",
        "heading",
        "blockquote",
        "list_item",
        "alert",
        "code",
        "formula",
        "footnote",
    }
    if block.kind in content_kinds and block.content is None:
        _add(
            diagnostics, "missing_content", path, f"{block.kind}にcontentがありません。"
        )
    if block.kind == "heading" and block.level is None:
        _add(diagnostics, "missing_level", path, "headingにlevelがありません。")
    if block.kind == "alert" and block.alert_kind is None:
        _add(diagnostics, "missing_alert_kind", path, "alertにalert_kindがありません。")
    if block.kind == "figure" and block.image is None:
        _add(diagnostics, "missing_image", path, "figureにimageがありません。")
    if block.kind == "table" and not block.cells:
        _add(diagnostics, "missing_cells", path, "tableにcellがありません。")
    for label, unit in (("content", block.content), ("caption", block.caption)):
        if unit is not None:
            _validate_unit(unit, f"{path}/{label}", ids, diagnostics)
    if block.image is not None:
        _validate_image(block.image, f"{path}/image", ids, asset_root, diagnostics)
    occupied: set[tuple[int, int]] = set()
    for cell_index, cell in enumerate(block.cells):
        cell_path = f"{path}/cells/{cell_index}"
        _record_id(ids, cell.id, "TableCell", cell_path, diagnostics)
        _validate_unit(cell.content, f"{cell_path}/content", ids, diagnostics)
        positions = {
            (row, column)
            for row in range(cell.row, cell.row + cell.rowspan)
            for column in range(cell.column, cell.column + cell.colspan)
        }
        if occupied & positions:
            _add(
                diagnostics,
                "overlapping_cell",
                cell_path,
                "表のcell領域が重複しています。",
            )
        occupied.update(positions)
        for image_index, image in enumerate(cell.images):
            _validate_image(
                image,
                f"{cell_path}/images/{image_index}",
                ids,
                asset_root,
                diagnostics,
            )


def _validate_unit(
    unit: TextUnit,
    path: str,
    ids: dict[str, str],
    diagnostics: list[LintDiagnostic],
) -> None:
    """TextUnitと配下SpanのID一意性を検査する。"""

    _record_id(ids, unit.id, "TextUnit", path, diagnostics)
    for index, span in enumerate(unit.spans):
        _record_id(ids, span.id, "TextSpan", f"{path}/spans/{index}", diagnostics)


def _validate_image(
    image: Image,
    path: str,
    ids: dict[str, str],
    asset_root: Path,
    diagnostics: list[LintDiagnostic],
) -> None:
    """Image ID、asset pathおよびCaptionを検査する。"""

    _record_id(ids, image.id, "Image", path, diagnostics)
    relative = PurePosixPath(image.asset_path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in image.asset_path:
        _add(
            diagnostics,
            "unsafe_asset_path",
            path,
            "asset pathが安全な相対pathではありません。",
        )
    elif not (asset_root / Path(*relative.parts)).is_file():
        _add(diagnostics, "missing_asset", path, "参照するassetが存在しません。")
    if image.caption is not None:
        _validate_unit(image.caption, f"{path}/caption", ids, diagnostics)


def _record_id(
    ids: dict[str, str],
    value: str,
    kind: str,
    path: str,
    diagnostics: list[LintDiagnostic],
) -> None:
    """IDの最初の所有者を記録し、重複を診断する。"""

    if value in ids:
        _add(
            diagnostics,
            "duplicate_id",
            path,
            f"{kind} IDが{ids[value]}と重複しています。",
        )
    else:
        ids[value] = path


def _add(
    diagnostics: list[LintDiagnostic],
    code: str,
    path: str,
    message: str,
) -> None:
    """一つのLINT診断を順序どおり追加する。"""

    diagnostics.append(LintDiagnostic(code=code, path=path, message=message))
