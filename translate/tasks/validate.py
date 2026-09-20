"""VALIDATE: 最終Internal Documentの出力可能性を検証する。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from translate.common.workspace import atomic_write_json
from translate.tasks.markdown import validate_document

if TYPE_CHECKING:
    from pathlib import Path

    from translate.document import Document


def _translation_warnings(document: Document) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    seen: set[str] = set()
    for page in document.pages:
        if page.number == 1:
            continue
        for block in page.blocks:
            groups = [
                block.final,
                block.translated,
                block.final_caption,
                block.translated_caption,
            ]
            groups.extend(cell.final or cell.translated for cell in block.cells)
            for item in (item for group in groups for item in group or []):
                if item.fix_status == "skipped" and item.id not in seen:
                    warnings.append(
                        {
                            "kind": "fix-skipped",
                            "target_id": item.id,
                            "message": item.fix_error or "FIX/VERIFY was skipped",
                        }
                    )
                    seen.add(item.id)
    return warnings


def _require_translations(document: Document) -> None:
    for page in document.pages:
        if page.number == 1:
            continue
        for block in page.blocks:
            if block.source and not (block.final or block.translated):
                msg = f"missing translation: {block.id}"
                raise ValueError(msg)
            for index, cell in enumerate(block.cells):
                if cell.source and not (cell.final or cell.translated):
                    msg = f"missing table cell translation: {block.id}/cell/{index}"
                    raise ValueError(msg)


def run(document: Document, asset_root: Path, output: Path) -> Document:
    """文書参照とassetを検査しreportを保存する。"""

    start = time.perf_counter()
    _require_translations(document)
    validate_document(document, asset_root)
    warnings = _translation_warnings(document)
    atomic_write_json(output, {"valid": True, "warnings": warnings})
    end = time.perf_counter()
    print(f"[TIME] VALIDATE page=- group=-: {end - start:.3f} s")  # noqa: T201
    return document
