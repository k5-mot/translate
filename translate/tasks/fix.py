"""FIX: Review Findingに基づく修正候補を生成する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from translate.adapters.llm import structured
from translate.common.redaction import safe_failure_reason
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings
    from translate.document import Document, Finding, Inline, Page


class Revision(BaseModel):
    """一つのInline修正。"""

    id: str
    text: str


class FixResponse(BaseModel):
    """ページ内修正候補。"""

    revisions: list[Revision] = Field(default_factory=list)


def _apply(page: Page, mapping: dict[str, str], status: str, error: str | None) -> None:
    """本文・caption・表セルの初回訳から最終層を作り、指定IDの修正と処理状態を付与する。"""

    blocks = page.blocks

    def fixed(values: list[Inline] | None) -> list[Inline] | None:
        """未翻訳層はNoneに保ち、各Inlineの初回訳を基に修正文と修正結果のmetadataを設定する。"""

        if values is None:
            return None
        return [
            item.model_copy(
                update={
                    "text": mapping.get(item.id, item.text),
                    "fixed_text": mapping.get(item.id),
                    "fix_status": status,
                    "fix_error": error,
                }
            )
            for item in values
        ]

    for block in blocks:
        block.final = fixed(block.translated)
        block.final_caption = fixed(block.translated_caption)
        for cell in block.cells:
            cell.final = fixed(cell.translated)


def _translations(page: Page) -> list[tuple[str, str]]:
    """FIXは原文ではなく、初回訳を修正対象としてLLMへ渡す。"""

    values: list[tuple[str, str]] = []
    for block in page.blocks:
        values.extend((item.id, item.text) for item in block.translated or [])
        values.extend((item.id, item.text) for item in block.translated_caption or [])
        for cell in block.cells:
            values.extend((item.id, item.text) for item in cell.translated or [])
    return values


def _validate_mapping(mapping: dict[str, str], valid: set[str]) -> None:
    """修正対象外のIDや空の修正文を拒否し、不正な提案が最終層へ反映されるのを防ぐ。"""

    if not set(mapping) <= valid or any(not value for value in mapping.values()):
        msg = "FIX returned invalid IDs or empty text"
        raise ValueError(msg)


class FixTask(BaseTask):
    """Execute FIX while sharing elapsed-time measurement only."""

    name = "FIX"

    def run(
        self,
        document: Document,
        findings: dict[int, list[Finding]],
        rules: str,
        settings: Settings,
        output_dir: Path,
    ) -> Document:
        """Findingがあるページだけ修正し、errorはskipする。"""

        with self.measure():
            result = document.model_copy(deep=True)
            for page in result.pages:
                page_findings = findings.get(page.number, [])
                if not page_findings:
                    _apply(page, {}, "unchanged", None)
                else:
                    try:
                        response = structured(
                            settings,
                            settings.fix_model or settings.review_model or "",
                            FixResponse,
                            rules,
                            json.dumps(
                                {
                                    "translations": [
                                        {"id": key, "text": text}
                                        for key, text in _translations(page)
                                    ],
                                    "findings": [
                                        item.model_dump() for item in page_findings
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                            reasoning="high",
                        )
                        mapping = {
                            item.id: item.text.strip() for item in response.revisions
                        }
                        valid = {key for key, _ in _translations(page)}
                        _validate_mapping(mapping, valid)
                        _apply(page, mapping, "fixed", None)
                    except Exception as error:  # noqa: BLE001
                        # Note 1: A failed suggestion must not discard the valid initial translation.
                        target_ids = sorted(
                            {
                                target_id
                                for item in page_findings
                                for target_id in item.target_ids
                            }
                        )
                        detail = (
                            f"page={page.number} targets={','.join(target_ids)} "
                            f"cause={safe_failure_reason(error)}"
                        )
                        _apply(page, {}, "skipped", detail)
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
    rules: str,
    settings: Settings,
    output_dir: Path,
) -> Document:
    """Existing function delegates to the typed FixTask operation."""

    return FixTask().run(document, findings, rules, settings, output_dir)
