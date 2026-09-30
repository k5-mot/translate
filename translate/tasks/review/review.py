"""問題指摘と修正候補を生成するREVIEW Task。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from translate.adapters.embedding import embed
from translate.adapters.llm import (
    LLMClient,
    LLMError,
    LLMInputExceededError,
    LLMOutputExceededError,
)
from translate.adapters.qdrant import search as search_qdrant
from translate.artifact_store import (
    begin_llm_call,
    canonical_hash,
    complete_llm_call,
    fail_llm_call,
    llm_call_id,
    load_model,
    load_reusable_llm_response,
    mark_split_llm_call,
    write_model,
)
from translate.glossary import relevant_glossary
from translate.models.artifacts import (
    CheckResult,
    LLMCallArtifact,
    LLMCallIndex,
    LLMTaskDiagnostics,
    ReviewResult,
)
from translate.models.review import (
    Finding,
    ReviewResponse,
    ReviewTarget,
    Revision,
    TextEdit,
)

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.config import Config
    from translate.models.document import TextSpan


def review(
    targets: list[ReviewTarget],
    checked: CheckResult,
    task_directory: Path,
    processing_directory: Path,
    config: Config,
    rules: str,
    glossary: str,
) -> ReviewResult:
    """ReviewTargetをchunk化し、LLMの指摘と修正候補へ決定的なIDを付ける。"""

    if config.openai_review_model is None:
        raise ValueError("review model is required")
    task_directory.mkdir(parents=True, exist_ok=True)
    diagnostics_path = processing_directory / "task-review.json"
    diagnostics: list[str] = []
    _write_diagnostics(diagnostics_path, diagnostics)
    client = LLMClient(config)
    responses: list[tuple[str, ReviewResponse, list[ReviewTarget]]] = []
    # Schema、message形式および抽出済み用語集へ2,048 bytesを予約する。
    overhead = len(rules.encode("utf-8")) + 2048
    for index, chunk in enumerate(
        _chunks(
            targets, config.review_max_targets, config.review_input_tokens - overhead
        )
    ):
        responses.extend(
            _execute(
                client=client,
                config=config,
                targets=chunk,
                checked=checked,
                task_directory=task_directory,
                rules=rules,
                glossary=glossary,
                lineage=[f"chunk-{index:04d}"],
                depth=0,
            )
        )
    findings: list[Finding] = []
    revisions: list[Revision] = []
    chunks_directory = task_directory / "chunks"
    for call_id, response, chunk in responses:
        write_model(chunks_directory / f"{call_id}.json", response)
        target_ids = {target_id for target in chunk for target_id in target.target_ids}
        span_ids = {span.id for target in chunk for span in target.spans}
        for index, item in enumerate(
            response.findings[: config.review_max_findings], start=1
        ):
            unknown = [
                target_id
                for target_id in item.target_ids
                if target_id not in target_ids
            ]
            diagnostics.extend(
                f"{call_id} unknown_target {target_id}" for target_id in unknown
            )
            findings.append(
                Finding(
                    id=f"review/{call_id}/finding-{index:04d}",
                    origin="review",
                    category=item.category,
                    severity=item.severity,
                    target_ids=item.target_ids,
                    message=item.message,
                )
            )
        if len(response.findings) > config.review_max_findings:
            diagnostics.append(f"{call_id} findings_limit")
        for index, item in enumerate(
            response.revisions[: config.review_max_revisions], start=1
        ):
            if item.target_id not in target_ids:
                diagnostics.append(f"{call_id} unknown_target {item.target_id}")
            edits = item.edits[: config.review_max_edits_per_revision]
            diagnostics.extend(
                f"{call_id} unknown_span {edit.span_id}"
                for edit in edits
                if edit.span_id not in span_ids
            )
            if len(item.edits) > config.review_max_edits_per_revision:
                diagnostics.append(f"{call_id} edits_limit {item.target_id}")
            revisions.append(
                Revision(
                    id=f"review/{call_id}/revision-{index:04d}",
                    target_id=item.target_id,
                    edits=[
                        TextEdit(span_id=edit.span_id, text=edit.text) for edit in edits
                    ],
                )
            )
        if len(response.revisions) > config.review_max_revisions:
            diagnostics.append(f"{call_id} revisions_limit")
    result = ReviewResult(findings=findings, revisions=revisions)
    _write_diagnostics(diagnostics_path, diagnostics)
    write_model(
        task_directory / "call-index.json",
        LLMCallIndex(
            task="REVIEW",
            call_ids=list(dict.fromkeys(call_id for call_id, _, _ in responses)),
        ),
    )
    write_model(task_directory / "review.json", result)
    return result


def _chunks(
    targets: list[ReviewTarget],
    maximum_targets: int,
    maximum_bytes: int,
) -> list[list[ReviewTarget]]:
    """ReviewTargetを件数と保守的UTF-8 byte上限内へchunk化する。"""

    result: list[list[ReviewTarget]] = []
    current: list[ReviewTarget] = []
    for target in targets:
        for part in _split_large_target(target, maximum_bytes):
            if current and (
                len(current) >= maximum_targets
                or _target_bytes([*current, part]) > maximum_bytes
            ):
                result.append(current)
                current = []
            current.append(part)
    if current:
        result.append(current)
    return result


def _split_large_target(target: ReviewTarget, maximum_bytes: int) -> list[ReviewTarget]:
    """長大な比較対象を原文断片と翻訳Span群へ欠落なく分ける。"""

    if _target_bytes([target]) <= maximum_bytes:
        return [target]
    span_groups = _split_spans(target, maximum_bytes) or [[]]
    parts: list[ReviewTarget] = []
    remaining_source = target.source
    for index, spans in enumerate(span_groups):
        remaining_groups = len(span_groups) - index
        source_length = (
            len(remaining_source) + remaining_groups - 1
        ) // remaining_groups
        part = target.model_copy(
            update={
                "id": f"{target.id}/part-{index + 1:04d}",
                "source": "",
                "translation": "".join(
                    "\n" if span.kind == "line_break" else span.text() for span in spans
                )
                if spans
                else "",
                "spans": spans,
            },
            deep=True,
        )
        source = _source_prefix(part, remaining_source[:source_length], maximum_bytes)
        parts.append(part.model_copy(update={"source": source}))
        remaining_source = remaining_source[len(source) :]
    while remaining_source:
        index = len(parts)
        part = target.model_copy(
            update={
                "id": f"{target.id}/part-{index + 1:04d}",
                "source": "",
                "translation": "",
                "spans": [],
            },
            deep=True,
        )
        source = _source_prefix(part, remaining_source, maximum_bytes)
        if not source:
            raise ValueError(
                f"single ReviewTarget exceeds review input limit: {target.id}"
            )
        parts.append(part.model_copy(update={"source": source}))
        remaining_source = remaining_source[len(source) :]
    return parts


def _source_prefix(target: ReviewTarget, source: str, maximum_bytes: int) -> str:
    """ReviewTargetへ収まる最長の原文prefixをUnicode文字境界で返す。"""

    low = 0
    high = len(source)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = target.model_copy(update={"source": source[:middle]})
        if _target_bytes([candidate]) <= maximum_bytes:
            low = middle
        else:
            high = middle - 1
    return source[:low]


def _split_spans(target: ReviewTarget, maximum_bytes: int) -> list[list[TextSpan]]:
    """修正単位のSpanを壊さず、REVIEW payloadのbyte上限へ分ける。"""

    groups: list[list[TextSpan]] = []
    current: list[TextSpan] = []
    for span in target.spans:
        projected = [*current, span]
        candidate = target.model_copy(
            update={
                "id": f"{target.id}/part-9999",
                "source": "",
                "spans": projected,
            }
        )
        if current and _target_bytes([candidate]) > maximum_bytes:
            groups.append(current)
            projected = [span]
            candidate = target.model_copy(
                update={
                    "id": f"{target.id}/part-9999",
                    "source": "",
                    "spans": projected,
                }
            )
        if _target_bytes([candidate]) > maximum_bytes:
            raise ValueError(
                f"single ReviewTarget span exceeds review input limit: {span.id}"
            )
        current = projected
    if current:
        groups.append(current)
    return groups


def _target_bytes(targets: list[ReviewTarget]) -> int:
    """REVIEW promptへ渡す対象の保守的byte数を返す。"""

    value = [_target_payload(target) for target in targets]
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _target_payload(target: ReviewTarget) -> dict[str, object]:
    """重複本文と書式情報を除き、REVIEWに必要な対象情報だけを返す。"""

    return {
        "id": target.id,
        "source": target.source,
        "target_ids": target.target_ids,
        "spans": [{"span_id": span.id, "text": span.text()} for span in target.spans],
    }


def _execute(
    *,
    client: LLMClient,
    config: Config,
    targets: list[ReviewTarget],
    checked: CheckResult,
    task_directory: Path,
    rules: str,
    glossary: str,
    lineage: list[str],
    depth: int,
) -> list[tuple[str, ReviewResponse, list[ReviewTarget]]]:
    """一つのREVIEW Callを再利用または送信し、出力超過時は分割する。"""

    target_ids = [target.id for target in targets]
    call_id = llm_call_id("REVIEW", target_ids, lineage)
    call_directory = task_directory / "calls" / call_id
    source = "\n".join(target.source for target in targets)
    payload_budget = config.review_input_tokens - len(rules.encode("utf-8")) - 2048
    selected_glossary = relevant_glossary(
        glossary,
        source,
        maximum_bytes=max(0, payload_budget // 3),
    )
    rag = _rag_context(config, source)
    relevant_findings = [
        finding.model_dump(mode="json")
        for finding in checked.findings
        if any(
            target_id in {item for target in targets for item in target.target_ids}
            for target_id in finding.target_ids
        )
    ]
    fingerprint = canonical_hash(
        {
            "task": "REVIEW",
            "schema": 2,
            "targets": [target.model_dump(mode="json") for target in targets],
            "check": relevant_findings,
            "rules": canonical_hash(rules),
            "glossary": canonical_hash(selected_glossary),
            "rag": [(item.get("id"), item.get("content_sha256")) for item in rag],
            "model": config.openai_review_model,
            "mode": config.llm_structured_output_mode,
            "thinking": "disabled",
            "input_tokens": config.review_input_tokens,
            "output_tokens": config.review_output_tokens,
        }
    )
    reusable = load_reusable_llm_response(
        call_directory,
        call_id=call_id,
        fingerprint=fingerprint,
        response_type=ReviewResponse,
    )
    if reusable is not None:
        return [(call_id, reusable[1], targets)]
    artifact = begin_llm_call(
        call_directory,
        call_id=call_id,
        task="REVIEW",
        fingerprint=fingerprint,
        target_ids=target_ids,
        previous_attempts=_previous_attempts(call_directory),
    )
    try:
        result = client.structured(
            model=config.openai_review_model or "",
            response_type=ReviewResponse,
            system=(
                "Review English-to-Japanese translations. Return findings and optional "
                "span-level revision suggestions as JSON only.\n\n" + rules
            ),
            user=_user_payload(
                targets,
                relevant_findings,
                selected_glossary,
                rag,
                payload_budget,
            ),
            contract=(
                '{"findings":[{"category":string,"severity":"info|warning|error",'
                '"target_ids":[string],"message":string}],"revisions":[{"target_id":string,'
                '"edits":[{"span_id":string,"text":string}]}]}.'
            ),
            native_schema=_schema(config),
            input_tokens=config.review_input_tokens,
            output_tokens=config.review_output_tokens,
        )
    except (LLMInputExceededError, LLMOutputExceededError) as error:
        if depth >= config.llm_split_max_depth:
            fail_llm_call(call_directory, artifact, error, attempts=1)
            raise
        groups = _retry_groups(targets)
        if not groups:
            fail_llm_call(call_directory, artifact, error, attempts=1)
            raise
        child_ids = [
            llm_call_id(
                "REVIEW", [target.id for target in group], [*lineage, str(index)]
            )
            for index, group in enumerate(groups)
        ]
        mark_split_llm_call(call_directory, artifact, child_ids)
        values: list[tuple[str, ReviewResponse, list[ReviewTarget]]] = []
        for index, group in enumerate(groups):
            values.extend(
                _execute(
                    client=client,
                    config=config,
                    targets=group,
                    checked=checked,
                    task_directory=task_directory,
                    rules=rules,
                    glossary=glossary,
                    lineage=[*lineage, str(index)],
                    depth=depth + 1,
                )
            )
        return values
    except LLMError as error:
        fail_llm_call(call_directory, artifact, error, attempts=1)
        raise
    complete_llm_call(
        call_directory,
        artifact,
        result.response,
        attempts=result.attempts,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    return [(call_id, result.response, targets)]


def _retry_groups(targets: list[ReviewTarget]) -> tuple[list[ReviewTarget], ...]:
    """上限超過したCallを、単一の事前分割済み対象も含めて縮小する。"""

    if len(targets) >= 2:
        middle = len(targets) // 2
        return (targets[:middle], targets[middle:])
    if not targets:
        return ()
    maximum_bytes = max(1, _target_bytes(targets) // 2)
    try:
        parts = _split_large_target(targets[0], maximum_bytes)
    except ValueError:
        return ()
    if len(parts) < 2:
        return ()
    return tuple([part] for part in parts)


def _schema(config: Config) -> dict[str, object]:
    """REVIEW専用の浅いnative JSON Schemaを作る。"""

    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "maxItems": config.review_max_findings,
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["info", "warning", "error"],
                        },
                        "target_ids": {
                            "type": "array",
                            "maxItems": config.review_max_targets,
                            "items": {"type": "string"},
                        },
                        "message": {"type": "string"},
                    },
                    "required": ["category", "severity", "target_ids", "message"],
                    "additionalProperties": False,
                },
            },
            "revisions": {
                "type": "array",
                "maxItems": config.review_max_revisions,
                "items": {
                    "type": "object",
                    "properties": {
                        "target_id": {"type": "string"},
                        "edits": {
                            "type": "array",
                            "maxItems": config.review_max_edits_per_revision,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "span_id": {"type": "string"},
                                    "text": {"type": "string"},
                                },
                                "required": ["span_id", "text"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["target_id", "edits"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["findings", "revisions"],
        "additionalProperties": False,
    }


def _rag_context(config: Config, query: str) -> list[dict[str, object]]:
    """設定済みの場合だけ英語原文をEmbeddingし、上位5件の参照文脈を得る。"""

    if not query.strip() or not config.qdrant_enabled():
        return []
    vector = embed([query], config)[0]
    return search_qdrant(config, vector, limit=5)


def _user_payload(
    targets: list[ReviewTarget],
    findings: list[dict[str, object]],
    glossary: str,
    rag: list[dict[str, object]],
    maximum_bytes: int,
) -> str:
    """低順位RAGを必要に応じて除外し、入力上限内のJSON payloadを作る。"""

    selected = list(rag)
    while True:
        value = json.dumps(
            {
                "glossary": glossary,
                "references": selected,
                "check_findings": findings,
                "targets": [_target_payload(target) for target in targets],
            },
            ensure_ascii=False,
        )
        if len(value.encode("utf-8")) <= maximum_bytes:
            return value
        if not selected:
            raise LLMInputExceededError("review prompt exceeds input limit")
        selected.pop()


def _previous_attempts(directory: Path) -> int:
    """Resume前の累計試行数を読める場合だけ引き継ぐ。"""

    path = directory / "call.json"
    if not path.is_file():
        return 0
    try:
        return load_model(path, LLMCallArtifact).attempts
    except Exception:  # noqa: BLE001
        return 0


def _write_diagnostics(path: Path, diagnostics: list[str]) -> None:
    """REVIEWの適用外項目を処理ディレクトリ直下へ保存する。"""

    write_model(
        path,
        LLMTaskDiagnostics(
            task="REVIEW",
            diagnostics=diagnostics,
            updated_at=datetime.now(UTC),
        ),
    )
