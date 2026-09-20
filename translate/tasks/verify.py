"""VERIFY: 修正候補の採否を原文との比較で決める。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from translate.adapters.llm import structured
from translate.common.redaction import safe_failure_reason
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.document import Document, Page, inline_text

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings
    from translate.document import Finding


class VerifyResponse(BaseModel):
    """修正候補の検証結果。"""

    approved: bool
    issues: list[str] = Field(default_factory=list)


def _revert(page: Page, error: str) -> None:
    for block in page.blocks:
        block.final = block.translated
        block.final_caption = block.translated_caption
        for values in (block.final, block.final_caption):
            for item in values or []:
                item.fix_status = "skipped"
                item.fix_error = error
        for cell in block.cells:
            cell.final = cell.translated
            for item in cell.final or []:
                item.fix_status = "skipped"
                item.fix_error = error


def run(
    document: Document,
    findings: dict[int, list[Finding]],
    settings: Settings,
    output_dir: Path,
) -> Document:
    """修正済みページだけ検証し、不合格なら修正前へ戻す。"""

    start = time.perf_counter()
    result = document.model_copy(deep=True)
    for page in result.pages:
        if findings.get(page.number):
            pairs = [
                {
                    "id": block.id,
                    "source": inline_text(block.source),
                    "before": inline_text(block.translated or block.source),
                    "candidate": inline_text(
                        block.final or block.translated or block.source
                    ),
                }
                for block in page.blocks
                if block.source
            ]
            try:
                response = structured(
                    settings,
                    settings.review_model or "",
                    VerifyResponse,
                    "原文と修正候補を比較し、指摘を解消し新しい誤りがなければapprovedにする。",
                    json.dumps(
                        {
                            "pairs": pairs,
                            "findings": [
                                item.model_dump() for item in findings[page.number]
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    reasoning="high",
                )
                if not response.approved:
                    _revert(page, "; ".join(response.issues) or "verification failed")
            except Exception as error:  # noqa: BLE001
                target_ids = sorted(
                    {
                        target_id
                        for item in findings[page.number]
                        for target_id in item.target_ids
                    }
                )
                _revert(
                    page,
                    f"page={page.number} targets={','.join(target_ids)} "
                    f"cause={safe_failure_reason(error)}",
                )
    with atomic_directory(output_dir) as temporary:
        for page in result.pages:
            atomic_write_json(
                temporary / f"page-{page.number:04d}.json",
                page.model_dump(mode="json"),
            )
    end = time.perf_counter()
    print(f"[TIME] VERIFY page=- group=-: {end - start:.3f} s")  # noqa: T201
    return result
