"""VERIFY: 修正候補の採否を原文との比較で決める。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from translate.adapters.llm import structured
from translate.common.redaction import safe_failure_reason
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.document import Document, Page, block_text_units
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings
    from translate.document import Finding


class VerifyResponse(BaseModel):
    """修正候補の検証結果。"""

    approved: bool
    issues: list[str] = Field(default_factory=list)


def _revert(page: Page, error: str) -> None:
    """ページの最終訳を初回訳と共有させ、両層のInlineへ修正skip理由を記録する。"""

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
            for image in cell.images:
                image.final_caption = image.translated_caption
                for item in image.final_caption or []:
                    item.fix_status = "skipped"
                    item.fix_error = error


class VerifyTask(BaseTask):
    """Execute VERIFY while sharing elapsed-time measurement only."""

    name = "VERIFY"

    def run(
        self,
        document: Document,
        findings: dict[int, list[Finding]],
        settings: Settings,
        output_dir: Path,
    ) -> Document:
        """指摘のあるページを検証し、不承認・検証失敗ならページ全体を初回訳へ戻す。"""

        with self.measure():
            result = document.model_copy(deep=True)
            for page in result.pages:
                if findings.get(page.number):
                    pairs = [
                        {
                            "id": unit.id,
                            "source": unit.text("source"),
                            "before": unit.text("translated"),
                            "candidate": unit.text("final"),
                        }
                        for block in page.blocks
                        for unit in block_text_units(block)
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
                                        item.model_dump()
                                        for item in findings[page.number]
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                            reasoning="high",
                        )
                        if not response.approved:
                            _revert(
                                page,
                                "; ".join(response.issues) or "verification failed",
                            )
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
            return result


def run(
    document: Document,
    findings: dict[int, list[Finding]],
    settings: Settings,
    output_dir: Path,
) -> Document:
    """Existing function delegates to the typed VerifyTask operation."""

    return VerifyTask().run(document, findings, settings, output_dir)
