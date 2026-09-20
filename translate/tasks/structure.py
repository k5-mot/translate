"""STRUCTURE: rulesとVLMで見出し、code、captionを補正する。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from translate.adapters import pdf
from translate.adapters.llm import structured
from translate.common.workspace import (
    atomic_directory,
    atomic_write_json,
    atomic_write_text,
)
from translate.document import BlockKind, Document, Page, inline_text

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings


class StructurePatch(BaseModel):
    """一つのblock構造修正。"""

    block_id: str
    kind: BlockKind | None = None
    level: int | None = None
    alert_kind: Literal["note", "tip", "important", "warning", "caution"] | None = None
    caption_source_id: str | None = None
    reason: str = ""


class StructureResponse(BaseModel):
    """ページの構造修正一覧。"""

    patches: list[StructurePatch] = Field(default_factory=list)


def _heading_jumps(page: Page) -> None:
    previous = 0
    for block in page.blocks:
        if block.kind != "heading":
            block.level = None
            continue
        level = block.level or 1
        block.level = min(level, previous + 1) if previous else level
        previous = block.level


def _merge_code(page: Page) -> None:
    merged = []
    for block in page.blocks:
        if merged and merged[-1].kind == block.kind == "code":
            merged[-1].source.extend(block.source)
            continue
        merged.append(block)
    page.blocks = merged
    for order, block in enumerate(page.blocks):
        block.order = order


def _apply(page: Page, response: StructureResponse) -> list[dict[str, object]]:
    blocks = {block.id: block for block in page.blocks}
    audit: list[dict[str, object]] = []
    for patch in response.patches:
        block = blocks.get(patch.block_id)
        if block is None:
            continue
        before = {
            "kind": block.kind,
            "level": block.level,
            "alert_kind": block.alert_kind,
        }
        if patch.kind is not None:
            block.kind = patch.kind
        block.level = patch.level if block.kind == "heading" else None
        block.alert_kind = patch.alert_kind if block.kind == "alert" else None
        caption = blocks.get(patch.caption_source_id or "")
        if caption is not None and caption is not block:
            block.caption = caption.source
            caption.source = []
        audit.append(
            {
                "block_id": block.id,
                "before": before,
                "after": {
                    "kind": block.kind,
                    "level": block.level,
                    "alert_kind": block.alert_kind,
                },
                "reason": patch.reason,
            }
        )
    _heading_jumps(page)
    _merge_code(page)
    return audit


def _run_into(
    document: Document,
    source_pdf: Path,
    rules: str,
    settings: Settings,
    output_dir: Path,
) -> Document:
    """本文ページをVLMで構造補正しpage別Artifactを保存する。"""

    start = time.perf_counter()
    result = document.model_copy(deep=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    for page in result.pages:
        if page.number == 1:
            continue
        image = pdf.render_page(
            source_pdf, page.number, output_dir / f"page-{page.number:04d}.png"
        )
        payload = [
            {
                "id": block.id,
                "kind": block.kind,
                "level": block.level,
                "text": inline_text(block.source),
            }
            for block in page.blocks
        ]
        if not payload:
            response = StructureResponse()
        else:
            # Note 1: The image lets the VLM distinguish layout from plain OCR text.
            user = "次のblock構造を補正してください。\n" + json.dumps(
                payload, ensure_ascii=False
            )
            try:
                response = structured(
                    settings,
                    settings.structure_model or "",
                    StructureResponse,
                    rules,
                    user,
                    reasoning="low",
                    image=image,
                )
            except Exception:  # noqa: BLE001
                # Note 2: Text-only fallback keeps the Task usable on non-vision models.
                response = structured(
                    settings,
                    settings.structure_model or "",
                    StructureResponse,
                    rules,
                    user,
                    reasoning="low",
                )
        audit = _apply(page, response)
        atomic_write_text(
            output_dir / f"page-{page.number:04d}.json",
            page.model_dump_json(indent=2) + "\n",
        )
        atomic_write_json(output_dir / f"audit-{page.number:04d}.json", audit)
        image.unlink(missing_ok=True)
    end = time.perf_counter()
    print(f"[TIME] STRUCTURE page=- group=-: {end - start:.3f} s")  # noqa: T201
    return result


def run(
    document: Document,
    source_pdf: Path,
    rules: str,
    settings: Settings,
    output_dir: Path,
) -> Document:
    """Task directory全体を検証後に公開する。"""

    with atomic_directory(output_dir) as temporary:
        return _run_into(document, source_pdf, rules, settings, temporary)
