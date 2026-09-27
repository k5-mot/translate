"""VALIDATE: 最終Internal Documentの出力可能性を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.common.workspace import atomic_write_json
from translate.document import block_text_units, inline_text
from translate.tasks.base import BaseTask
from translate.tasks.markdown import validate_document

if TYPE_CHECKING:
    from pathlib import Path

    from translate.document import Document


def _translation_warnings(document: Document) -> list[dict[str, str]]:
    """第1ページ以外の修正skip情報を本文・caption・セルから集め、同一Inlineの警告重複を抑える。"""

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
            groups.extend(
                image.final_caption or image.translated_caption
                for cell in block.cells
                for image in cell.images
            )
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
    """本文・Caption・セルの採用訳を検査し、非空白原文に対する空訳の公開を止める。"""

    for page in document.pages:
        if page.number == 1:
            continue
        for block in page.blocks:
            for unit in block_text_units(block):
                if not inline_text(unit.source).strip():
                    continue
                # 描画と同じくNoneだけを未作成とし、空の最終訳を初回訳で隠さない。
                selected = unit.final if unit.final is not None else unit.translated
                if selected is None or not inline_text(selected).strip():
                    msg = f"missing translation: {unit.id}"
                    raise ValueError(msg)


def _canonicalize_assets(document: Document, asset_root: Path) -> None:
    """旧checkpointのstructured/assets URIをMERGE rootへ寄せる。"""

    for page in document.pages:
        for block in page.blocks:
            asset_path = block.asset_path
            if not asset_path or not asset_path.startswith("structured/assets/"):
                continue
            candidate = asset_path.removeprefix("structured/assets/")
            candidate = candidate.removeprefix("assets/")
            candidate = f"assets/{candidate}"
            if (asset_root / candidate).exists():
                block.asset_path = candidate


class ValidateTask(BaseTask):
    """Execute VALIDATE while sharing elapsed-time measurement only."""

    name = "VALIDATE"

    def run(self, document: Document, asset_root: Path, output: Path) -> Document:
        """入力文書の旧asset参照を補正し、出力可能性の検査後にreportを保存する。"""

        with self.measure():
            _canonicalize_assets(document, asset_root)
            _require_translations(document)
            validate_document(document, asset_root)
            warnings = _translation_warnings(document)
            atomic_write_json(output, {"valid": True, "warnings": warnings})
            return document


def run(document: Document, asset_root: Path, output: Path) -> Document:
    """Existing function delegates to the typed ValidateTask operation."""

    return ValidateTask().run(document, asset_root, output)
