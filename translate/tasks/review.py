"""REVIEW: rules、用語集、RAGを使いFindingだけを生成する。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from translate.adapters.llm import structured
from translate.adapters.qdrant import search
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.document import Document, Finding, inline_text
from translate.tasks.check import GlossaryEntry, matching_glossary

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings


class ReviewResponse(BaseModel):
    """LLM査読結果。"""

    findings: list[Finding] = Field(default_factory=list)


def run(
    document: Document,
    checks: dict[int, list[Finding]],
    rules: str,
    glossary: list[GlossaryEntry],
    settings: Settings,
    output_dir: Path,
) -> dict[int, list[Finding]]:
    """各ページを高推論modelで査読する。"""

    start = time.perf_counter()
    results: dict[int, list[Finding]] = {}
    with atomic_directory(output_dir) as temporary:
        for page in document.pages:
            if page.number == 1:
                continue
            pairs = [
                {
                    "id": block.id,
                    "source": inline_text(block.source),
                    "translation": inline_text(block.translated or block.source),
                }
                for block in page.blocks
                if block.source
            ]
            if not pairs:
                results[page.number] = []
                continue
            source = "\n".join(str(item["source"]) for item in pairs)
            # Note 1: REVIEW only emits findings; mutation is isolated in FIX.
            response = structured(
                settings,
                settings.review_model or "",
                ReviewResponse,
                rules,
                json.dumps(
                    {
                        "pairs": pairs,
                        "automatic_findings": [
                            item.model_dump() for item in checks.get(page.number, [])
                        ],
                        "glossary": [
                            item.model_dump()
                            for item in matching_glossary(source, glossary)
                        ],
                        "references": search(
                            settings,
                            source[:2_000],
                            artifact_path=(
                                temporary / "qdrant" / f"page-{page.number:04d}.json"
                            ),
                        ),
                    },
                    ensure_ascii=False,
                ),
                reasoning="high",
            )
            results[page.number] = response.findings
        for number, page_findings in results.items():
            atomic_write_json(
                temporary / f"page-{number:04d}.json",
                [item.model_dump() for item in page_findings],
            )
    end = time.perf_counter()
    print(f"[TIME] REVIEW page=- group=-: {end - start:.3f} s")  # noqa: T201
    return results
