"""REVIEW: rules、用語集、RAGを使いFindingだけを生成する。"""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from translate.adapters.llm import LLMError, structured
from translate.adapters.qdrant import search
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.document import Document, Finding, block_text_units
from translate.tasks.base import BaseTask
from translate.tasks.check import GlossaryEntry, matching_glossary

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings


class ReviewResponse(BaseModel):
    """LLM査読結果。"""

    findings: list[Finding] = Field(default_factory=list)


_MAX_TRUNCATION_SPLIT_DEPTH = 3
_MAX_REVIEW_ITEMS = 8


def _review_chunks(
    pairs: list[dict[str, str]],
    *,
    available_input_tokens: int,
    max_items: int = _MAX_REVIEW_ITEMS,
) -> list[list[dict[str, str]]]:
    """入力順を保ったまま、有限の入力budget境界でpairsを分割する。"""

    budget = max(1_024, available_input_tokens * 4)
    chunks: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_size = 2
    for pair in pairs:
        item_size = len(json.dumps(pair, ensure_ascii=False, separators=(",", ":"))) + 1
        if current and (current_size + item_size > budget or len(current) >= max_items):
            chunks.append(current)
            current = []
            current_size = 2
        current.append(pair)
        current_size += item_size
    if current:
        chunks.append(current)
    return chunks


def _chunk_id(page: int, index: str) -> str:
    """Review chunkの安定した識別子を返す。"""

    return f"page-{page:04d}-review-{index}"


def _is_output_truncated(error: LLMError) -> bool:
    return (
        error.stage == "text-output"
        and error.failure_kind == "output-truncated"
        and error.finish_reason == "length"
    )


def _finding_key(finding: Finding) -> str:
    """Findingを本文を露出しない内部dedupe keyへ正規化する。"""

    return json.dumps(
        finding.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
    )


def _merge_findings(findings: list[Finding]) -> list[Finding]:
    """chunk順を維持し、同一Findingを一度だけ返す。"""

    merged: list[Finding] = []
    seen: set[str] = set()
    for finding in findings:
        key = _finding_key(finding)
        if key not in seen:
            seen.add(key)
            merged.append(finding)
    return merged


def _cache_key(page: int, pairs: list[dict[str, str]]) -> str:
    payload = json.dumps(
        pairs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(f"{page}:".encode() + payload.encode()).hexdigest()


class ReviewTask(BaseTask):
    """Execute REVIEW while sharing elapsed-time measurement only."""

    name = "REVIEW"

    def run(
        self,
        document: Document,
        checks: dict[int, list[Finding]],
        rules: str,
        glossary: list[GlossaryEntry],
        settings: Settings,
        output_dir: Path,
    ) -> dict[int, list[Finding]]:
        """各ページを高推論modelで査読する。"""

        with self.measure():
            results: dict[int, list[Finding]] = {}
            cache_dir = output_dir.parent / f".{output_dir.name}.chunks"
            cache_dir.mkdir(parents=True, exist_ok=True)
            with atomic_directory(output_dir) as temporary:
                for page in document.pages:
                    if page.number == 1:
                        continue
                    pairs = [
                        {
                            "id": unit.id,
                            "source": unit.text("source"),
                            "translation": unit.text("translated"),
                        }
                        for block in page.blocks
                        for unit in block_text_units(block)
                    ]
                    if not pairs:
                        results[page.number] = []
                        continue
                    source = "\n".join(str(item["source"]) for item in pairs)
                    automatic_findings = [
                        item.model_dump() for item in checks.get(page.number, [])
                    ]
                    glossary_items = [
                        item.model_dump()
                        for item in matching_glossary(source, glossary)
                    ]
                    page_findings: list[Finding] = []
                    chunks = _review_chunks(
                        pairs, available_input_tokens=settings.available_input_tokens
                    )
                    for position, chunk in enumerate(chunks, start=1):
                        chunk_findings = _run_chunk(
                            page.number,
                            str(position).zfill(4),
                            chunk,
                            automatic_findings,
                            glossary_items,
                            rules,
                            settings,
                            temporary,
                            cache_dir,
                            depth=0,
                        )
                        page_findings.extend(chunk_findings)
                    results[page.number] = _merge_findings(page_findings)
                for number, page_findings in results.items():
                    atomic_write_json(
                        temporary / f"page-{number:04d}.json",
                        [item.model_dump() for item in page_findings],
                    )
            shutil.rmtree(cache_dir, ignore_errors=True)
            return results


def run(
    document: Document,
    checks: dict[int, list[Finding]],
    rules: str,
    glossary: list[GlossaryEntry],
    settings: Settings,
    output_dir: Path,
) -> dict[int, list[Finding]]:
    """Existing function delegates to the typed ReviewTask operation."""

    return ReviewTask().run(document, checks, rules, glossary, settings, output_dir)


def _run_chunk(
    page: int,
    index: str,
    pairs: list[dict[str, str]],
    automatic_findings: list[dict[str, object]],
    glossary_items: list[dict[str, object]],
    rules: str,
    settings: Settings,
    temporary: Path,
    cache_dir: Path,
    *,
    depth: int,
) -> list[Finding]:
    """一つのReview chunkを実行し、枯渇時だけ決定的に二分する。"""

    chunk_id = _chunk_id(page, index)
    digest = _cache_key(page, pairs)
    cache_path = cache_dir / f"{chunk_id.replace('.', '-')}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("digest") == digest:
            return [Finding.model_validate(item) for item in cached.get("findings", [])]

    source = "\n".join(item["source"] for item in pairs)
    references = search(
        settings,
        source[:2_000],
        artifact_path=temporary / "qdrant" / f"{chunk_id}.json",
    )
    prompt = json.dumps(
        {
            "pairs": pairs,
            "automatic_findings": automatic_findings,
            "glossary": glossary_items,
            "references": references,
        },
        ensure_ascii=False,
    )
    last_error: LLMError | None = None
    for _attempt in range(max(1, settings.retry_attempts)):
        try:
            response = structured(
                settings,
                settings.review_model or "",
                ReviewResponse,
                rules,
                prompt,
                reasoning="high",
            )
            findings = response.findings
            atomic_write_json(
                cache_path,
                {
                    "digest": digest,
                    "findings": [item.model_dump() for item in findings],
                },
            )
            atomic_write_json(
                temporary / f"{chunk_id}.json",
                [item.model_dump() for item in findings],
            )
        except LLMError as error:
            last_error = error
            if not _is_output_truncated(error):
                raise
        else:
            return findings
    if last_error is None:
        raise RuntimeError("review chunk exhausted without response")
    if depth >= _MAX_TRUNCATION_SPLIT_DEPTH or len(pairs) <= 1:
        raise last_error
    midpoint = len(pairs) // 2
    left = _run_chunk(
        page,
        f"{index}.0",
        pairs[:midpoint],
        automatic_findings,
        glossary_items,
        rules,
        settings,
        temporary,
        cache_dir,
        depth=depth + 1,
    )
    right = _run_chunk(
        page,
        f"{index}.1",
        pairs[midpoint:],
        automatic_findings,
        glossary_items,
        rules,
        settings,
        temporary,
        cache_dir,
        depth=depth + 1,
    )
    return _merge_findings(left + right)
