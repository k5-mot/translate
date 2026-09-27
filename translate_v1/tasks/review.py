"""REVIEW: rules、用語集、RAGを使いFindingだけを生成する。"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from translate_v1.adapters.llm import LLMContextExceededError, LLMError, structured
from translate_v1.adapters.qdrant import search
from translate_v1.common.workspace import atomic_directory, atomic_write_json
from translate_v1.document import Document, Finding, block_text_units
from translate_v1.tasks.base import BaseTask
from translate_v1.tasks.check import GlossaryEntry, matching_glossary

if TYPE_CHECKING:
    from pathlib import Path

    from translate_v1.common.settings import Settings


class ReviewResponse(BaseModel):
    """LLM査読結果。"""

    findings: list[Finding] = Field(default_factory=list)


_MAX_TRUNCATION_SPLIT_DEPTH = 3
_MAX_REVIEW_ITEMS = 8
_REVIEW_CHARS_PER_TOKEN = 2
_REVIEW_FIXED_OVERHEAD_TOKENS = 2_048


def _review_chunks(
    pairs: list[dict[str, str]],
    *,
    available_input_tokens: int,
    max_items: int = _MAX_REVIEW_ITEMS,
) -> list[list[dict[str, str]]]:
    """入力順を保って概算文字量と件数で分割する。単独pairが上限を超えても分断しない。"""

    budget = max(
        1_024,
        max(1_024, available_input_tokens - _REVIEW_FIXED_OVERHEAD_TOKENS)
        * _REVIEW_CHARS_PER_TOKEN,
    )
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


def _partition_findings(
    findings: list[dict[str, object]], chunks: list[list[dict[str, str]]]
) -> list[list[dict[str, object]]]:
    """Findingを最初の対象一致Chunkへ渡し、一致先のないFindingは順番に振り分ける。"""

    buckets: list[list[dict[str, object]]] = [[] for _ in chunks]
    if not chunks:
        return buckets
    chunk_ids = [
        {item["id"] for item in chunk if isinstance(item.get("id"), str)}
        for chunk in chunks
    ]
    for index, finding in enumerate(findings):
        raw_target_ids = finding.get("target_ids", [])
        target_ids = (
            {item for item in raw_target_ids if isinstance(item, str)}
            if isinstance(raw_target_ids, list)
            else set()
        )
        matching = [
            position
            for position, ids in enumerate(chunk_ids)
            if target_ids and target_ids.intersection(ids)
        ]
        position = matching[0] if matching else index % len(chunks)
        buckets[position].append(finding)
    return buckets


def _filter_glossary_items(
    source: str, glossary_items: list[dict[str, object]]
) -> list[dict[str, object]]:
    """子chunkのsourceに一致する用語だけを残す。"""

    folded = source.casefold()
    result: list[dict[str, object]] = []
    for item in glossary_items:
        term = item.get("source")
        if isinstance(term, str) and term.casefold() in folded:
            result.append(item)
    return result


def _estimated_input_tokens(rules: str, prompt: str) -> int:
    """文字数と固定余裕から入力token数を概算する。Providerの実token上限は保証しない。"""

    return (
        math.ceil((len(rules) + len(prompt)) / _REVIEW_CHARS_PER_TOKEN)
        + _REVIEW_FIXED_OVERHEAD_TOKENS
    )


def _chunk_id(page: int, index: str) -> str:
    """Review chunkの安定した識別子を返す。"""

    return f"page-{page:04d}-review-{index}"


def _is_output_truncated(error: LLMError) -> bool:
    """本文の生成上限による切断だけを識別し、通信・解析・context超過を同じ回復処理へ混ぜない。"""

    return (
        error.stage == "text-output"
        and error.failure_kind == "output-truncated"
        and error.finish_reason == "length"
    )


def _is_request_timeout(error: LLMError) -> bool:
    """Return true for provider/transport timeout failures safe to split."""

    return error.stage in {"text-invoke", "vision-invoke"} and (
        "timeout" in error.cause_type.casefold()
    )


def _is_context_exceeded(error: LLMError) -> bool:
    """Return true for a classified provider or local budget overflow."""

    return (
        error.stage in {"text-invoke", "vision-invoke"}
        and error.failure_kind == "context-exceeded"
    )


def _finding_key(finding: Finding) -> str:
    """Finding全内容を含むJSONを内部の重複判定keyにする。ログや公開診断には出さない。"""

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
    """ページ番号と比較対象の原訳文から、既存のChunk応答再利用を照合するhashを作る。"""

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
        """第1ページ以外を逐次査読し、独自のChunk応答Cacheを正常終了後に削除する。"""

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
                    automatic_findings = [
                        item.model_dump() for item in checks.get(page.number, [])
                    ]
                    # Keep advisory references even when the model returns no finding.
                    page_findings: list[Finding] = [
                        item
                        for item in checks.get(page.number, [])
                        if item.kind == "literal-reference"
                    ]
                    chunks = _review_chunks(
                        pairs, available_input_tokens=settings.available_input_tokens
                    )
                    automatic_by_chunk = _partition_findings(automatic_findings, chunks)
                    for position, chunk in enumerate(chunks, start=1):
                        chunk_source = "\n".join(item["source"] for item in chunk)
                        glossary_items = [
                            item.model_dump()
                            for item in matching_glossary(chunk_source, glossary)
                        ]
                        chunk_findings = _run_chunk(
                            page.number,
                            str(position).zfill(4),
                            chunk,
                            automatic_by_chunk[position - 1],
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
    """既存Cacheを照合して査読し、回復対象の失敗だけ有限回の再送・逐次二分へ回す。"""

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
    estimated_input_tokens = _estimated_input_tokens(rules, prompt)
    if (
        settings.available_input_tokens > _REVIEW_FIXED_OVERHEAD_TOKENS
        and estimated_input_tokens > settings.available_input_tokens
    ):
        last_error = LLMError(
            "text-invoke",
            LLMContextExceededError(),
            failure_kind="context-exceeded",
            input_tokens=estimated_input_tokens,
        )
        if depth >= _MAX_TRUNCATION_SPLIT_DEPTH or len(pairs) <= 1:
            raise last_error
        midpoint = len(pairs) // 2
        child_findings = _partition_findings(
            automatic_findings, [pairs[:midpoint], pairs[midpoint:]]
        )
        left_source = "\n".join(item["source"] for item in pairs[:midpoint])
        right_source = "\n".join(item["source"] for item in pairs[midpoint:])
        left = _run_chunk(
            page,
            f"{index}.0",
            pairs[:midpoint],
            child_findings[0],
            _filter_glossary_items(left_source, glossary_items),
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
            child_findings[1],
            _filter_glossary_items(right_source, glossary_items),
            rules,
            settings,
            temporary,
            cache_dir,
            depth=depth + 1,
        )
        return _merge_findings(left + right)
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
            if not (
                _is_output_truncated(error)
                or _is_request_timeout(error)
                or _is_context_exceeded(error)
            ):
                raise
        else:
            return findings
    if last_error is None:
        raise RuntimeError("review chunk exhausted without response")
    if depth >= _MAX_TRUNCATION_SPLIT_DEPTH or len(pairs) <= 1:
        raise last_error
    midpoint = len(pairs) // 2
    child_findings = _partition_findings(
        automatic_findings, [pairs[:midpoint], pairs[midpoint:]]
    )
    left_source = "\n".join(item["source"] for item in pairs[:midpoint])
    right_source = "\n".join(item["source"] for item in pairs[midpoint:])
    left = _run_chunk(
        page,
        f"{index}.0",
        pairs[:midpoint],
        child_findings[0],
        _filter_glossary_items(left_source, glossary_items),
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
        child_findings[1],
        _filter_glossary_items(right_source, glossary_items),
        rules,
        settings,
        temporary,
        cache_dir,
        depth=depth + 1,
    )
    return _merge_findings(left + right)
