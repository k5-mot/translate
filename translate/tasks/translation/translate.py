"""TextSpanを生成LLMで翻訳するTRANSLATE Task。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from translate.adapters.embedding import embed
from translate.adapters.llm import LLMClient, LLMError, LLMOutputExceededError
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
from translate.models.artifacts import LLMCallArtifact, LLMCallIndex, LLMTaskDiagnostics
from translate.models.document import Document, TextSpan, iter_text_units

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.config import Config

TranslationContext = dict[str, tuple[str, str]]


class TranslationModel(BaseModel):
    """未知fieldを無視するTRANSLATE応答モデルの設定。"""

    model_config = ConfigDict(extra="ignore")


class TranslationItem(TranslationModel):
    """一つのSpan IDと日本語訳。"""

    span_id: str
    text: str


class TranslationResponse(TranslationModel):
    """一回のTRANSLATE Callが返す翻訳一覧。"""

    translations: list[TranslationItem] = Field(default_factory=list)


def translate(
    document: Document,
    task_directory: Path,
    processing_directory: Path,
    config: Config,
    rules: str,
    glossary: str,
    previous_context: TranslationContext | None = None,
) -> Document:
    """対象Spanをchunk化し、Call成果を再利用しながら日本語訳を設定する。"""

    if config.openai_translation_model is None:
        raise ValueError("translation model is required")
    task_directory.mkdir(parents=True, exist_ok=True)
    diagnostics_path = processing_directory / "task-translate.json"
    diagnostics: list[str] = []
    _write_diagnostics(diagnostics_path, diagnostics)
    updated = document.model_copy(deep=True)
    client = LLMClient(config)
    context = previous_context or {}
    overhead = len((rules + glossary).encode("utf-8")) + 2048
    chunks = _chunks(
        updated,
        config.translate_max_units,
        config.translate_input_tokens - overhead,
        context,
    )
    responses: list[tuple[str, TranslationResponse]] = []
    for index, spans in enumerate(chunks):
        responses.extend(
            _execute(
                client=client,
                config=config,
                spans=spans,
                task_directory=task_directory,
                rules=rules,
                glossary=glossary,
                lineage=[f"chunk-{index:04d}"],
                depth=0,
                allow_missing_retry=True,
                diagnostics=diagnostics,
                previous_context=context,
            )
        )
    span_index = {
        span.id: span
        for _, unit in iter_text_units(updated)
        for span in unit.spans
        if span.kind not in {"code", "line_break"}
    }
    for call_id, response in responses:
        seen: set[str] = set()
        for item in response.translations:
            if item.span_id in seen:
                diagnostics.append(f"{call_id} duplicate_span {item.span_id}")
                continue
            seen.add(item.span_id)
            span = span_index.get(item.span_id)
            if span is None:
                diagnostics.append(f"{call_id} unknown_span {item.span_id}")
                continue
            span.translated = item.text
    _write_diagnostics(diagnostics_path, diagnostics)
    write_model(
        task_directory / "call-index.json",
        LLMCallIndex(
            task="TRANSLATE",
            call_ids=list(dict.fromkeys(call_id for call_id, _ in responses)),
        ),
    )
    write_model(task_directory / "document.json", updated)
    chunks_directory = task_directory / "chunks"
    for call_id, response in responses:
        write_model(chunks_directory / f"{call_id}.json", response)
    return updated


def _chunks(
    document: Document,
    maximum_units: int,
    maximum_bytes: int,
    previous_context: TranslationContext | None = None,
) -> list[list[TextSpan]]:
    """TextUnitを通常は分断せず、件数と保守的byte上限内へchunk化する。"""

    context = previous_context or {}
    groups = [
        [
            span
            for span in unit.spans
            if span.kind not in {"code", "line_break"}
            and span.translated is None
            and span.revised is None
        ]
        for _, unit in iter_text_units(document)
    ]
    groups = [group for group in groups if group]
    chunks: list[list[TextSpan]] = []
    current: list[TextSpan] = []
    current_units = 0
    for group in groups:
        parts = _split_large_group(group, maximum_bytes, context)
        for part in parts:
            projected = [*current, *part]
            if current and (
                current_units >= maximum_units
                or _span_bytes(projected, context) > maximum_bytes
            ):
                chunks.append(current)
                current = []
                current_units = 0
            current.extend(part)
            current_units += 1
    if current:
        chunks.append(current)
    return chunks


def _split_large_group(
    group: list[TextSpan],
    maximum_bytes: int,
    previous_context: TranslationContext,
) -> list[list[TextSpan]]:
    """単一TextUnitだけが上限を超える場合にSpan境界で分割する。"""

    if _span_bytes(group, previous_context) <= maximum_bytes:
        return [group]
    parts: list[list[TextSpan]] = []
    current: list[TextSpan] = []
    for span in group:
        if _span_bytes([span], previous_context) > maximum_bytes:
            raise ValueError(
                f"single TextSpan exceeds translation input limit: {span.id}"
            )
        if current and _span_bytes([*current, span], previous_context) > maximum_bytes:
            parts.append(current)
            current = []
        current.append(span)
    if current:
        parts.append(current)
    return parts


def _span_bytes(spans: list[TextSpan], previous_context: TranslationContext) -> int:
    """prompt overheadを含む保守的なUTF-8 byte数を計算する。"""

    payload = [_translation_item(span, previous_context) for span in spans]
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 1024


def _execute(
    *,
    client: LLMClient,
    config: Config,
    spans: list[TextSpan],
    task_directory: Path,
    rules: str,
    glossary: str,
    lineage: list[str],
    depth: int,
    allow_missing_retry: bool,
    diagnostics: list[str],
    previous_context: TranslationContext,
) -> list[tuple[str, TranslationResponse]]:
    """一つの論理Callを再利用または送信し、必要時だけ子Callへ分割する。"""

    target_ids = [span.id for span in spans]
    call_id = llm_call_id("TRANSLATE", target_ids, lineage)
    call_directory = task_directory / "calls" / call_id
    rag = _rag_context(config, "\n".join(span.source for span in spans))
    fingerprint = canonical_hash(
        {
            "task": "TRANSLATE",
            "schema": 1,
            "targets": [(span.id, span.source) for span in spans],
            "previous": [(span.id, previous_context.get(span.id)) for span in spans],
            "rules": canonical_hash(rules),
            "glossary": canonical_hash(glossary),
            "rag": [(item.get("id"), item.get("content_sha256")) for item in rag],
            "model": config.openai_translation_model,
            "mode": config.llm_structured_output_mode,
            "thinking": "disabled",
            "input_tokens": config.translate_input_tokens,
            "output_tokens": config.translate_output_tokens,
        }
    )
    reusable = load_reusable_llm_response(
        call_directory,
        call_id=call_id,
        fingerprint=fingerprint,
        response_type=TranslationResponse,
    )
    if reusable is not None:
        response = reusable[1]
        return [(call_id, response)]
    previous = _previous_attempts(call_directory)
    artifact = begin_llm_call(
        call_directory,
        call_id=call_id,
        task="TRANSLATE",
        fingerprint=fingerprint,
        target_ids=target_ids,
        previous_attempts=previous,
    )
    try:
        result = client.structured(
            model=config.openai_translation_model or "",
            response_type=TranslationResponse,
            system=(
                "Translate each English source into natural Japanese. Preserve IDs and "
                "return JSON only. When previous_source and previous_translation are "
                "present, use them only as context for translating the current source."
                "\n\n" + rules
            ),
            user=_user_payload(
                spans,
                glossary,
                rag,
                config.translate_input_tokens,
                previous_context,
            ),
            contract=(
                'Return {"translations":[{"span_id":string,"text":string}]}. '
                f"At most {len(spans)} items."
            ),
            native_schema=_schema(len(spans)),
            output_tokens=config.translate_output_tokens,
        )
    except LLMOutputExceededError as error:
        return _split_call(
            artifact=artifact,
            error=error,
            client=client,
            config=config,
            spans=spans,
            task_directory=task_directory,
            rules=rules,
            glossary=glossary,
            lineage=lineage,
            depth=depth,
            diagnostics=diagnostics,
            previous_context=previous_context,
        )
    except LLMError as error:
        fail_llm_call(call_directory, artifact, error, attempts=1)
        raise
    response = result.response
    valid_ids = {item.span_id for item in response.translations if item.text.strip()}
    missing = [span for span in spans if span.id not in valid_ids]
    child_ids: list[str] = []
    if missing and allow_missing_retry:
        child_ids = [
            llm_call_id(
                "TRANSLATE", [span.id for span in missing], [*lineage, "missing"]
            )
        ]
    status: Literal["succeeded", "partial"] = "partial" if missing else "succeeded"
    complete_llm_call(
        call_directory,
        artifact,
        response,
        attempts=result.attempts,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        status=status,
        child_call_ids=child_ids,
    )
    values = [(call_id, response)]
    if missing and allow_missing_retry:
        values.extend(
            _execute(
                client=client,
                config=config,
                spans=missing,
                task_directory=task_directory,
                rules=rules,
                glossary=glossary,
                lineage=[*lineage, "missing"],
                depth=depth,
                allow_missing_retry=False,
                diagnostics=diagnostics,
                previous_context=previous_context,
            )
        )
    elif missing:
        present = {item.span_id for item in response.translations}
        for span in missing:
            if span.id not in present:
                response.translations.append(TranslationItem(span_id=span.id, text=""))
            diagnostics.append(f"{call_id} empty_translation {span.id}")
    return values


def _split_call(
    *,
    artifact: LLMCallArtifact,
    error: LLMOutputExceededError,
    client: LLMClient,
    config: Config,
    spans: list[TextSpan],
    task_directory: Path,
    rules: str,
    glossary: str,
    lineage: list[str],
    depth: int,
    diagnostics: list[str],
    previous_context: TranslationContext,
) -> list[tuple[str, TranslationResponse]]:
    """出力超過した親Callを半分の子Callへ置換する。"""

    parent_directory = task_directory / "calls" / artifact.call_id
    if len(spans) < 2 or depth >= config.llm_split_max_depth:
        fail_llm_call(parent_directory, artifact, error, attempts=1)
        raise error
    middle = len(spans) // 2
    groups = (spans[:middle], spans[middle:])
    child_ids = [
        llm_call_id("TRANSLATE", [span.id for span in group], [*lineage, str(index)])
        for index, group in enumerate(groups)
    ]
    mark_split_llm_call(parent_directory, artifact, child_ids)
    results: list[tuple[str, TranslationResponse]] = []
    for index, group in enumerate(groups):
        results.extend(
            _execute(
                client=client,
                config=config,
                spans=group,
                task_directory=task_directory,
                rules=rules,
                glossary=glossary,
                lineage=[*lineage, str(index)],
                depth=depth + 1,
                allow_missing_retry=True,
                diagnostics=diagnostics,
                previous_context=previous_context,
            )
        )
    return results


def _schema(maximum_items: int) -> dict[str, object]:
    """TRANSLATE専用の浅いnative JSON Schemaを作る。"""

    return {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "maxItems": maximum_items,
                "items": {
                    "type": "object",
                    "properties": {
                        "span_id": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["span_id", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["translations"],
        "additionalProperties": False,
    }


def _rag_context(config: Config, query: str) -> list[dict[str, object]]:
    """設定済みの場合だけ英語原文をEmbeddingし、上位5件の参照文脈を得る。"""

    if not query.strip() or not config.qdrant_enabled():
        return []
    vector = embed([query], config)[0]
    return search_qdrant(config, vector, limit=5)


def _user_payload(
    spans: list[TextSpan],
    glossary: str,
    rag: list[dict[str, object]],
    maximum_bytes: int,
    previous_context: TranslationContext | None = None,
) -> str:
    """低順位RAGを必要に応じて除外し、入力上限内のJSON payloadを作る。"""

    selected = list(rag)
    context = previous_context or {}
    while True:
        value = json.dumps(
            {
                "glossary": glossary,
                "references": selected,
                "items": [_translation_item(span, context) for span in spans],
            },
            ensure_ascii=False,
        )
        if len(value.encode("utf-8")) <= maximum_bytes:
            return value
        if not selected:
            raise ValueError("translation prompt exceeds input limit")
        selected.pop()


def _translation_item(
    span: TextSpan, previous_context: TranslationContext
) -> dict[str, str]:
    """一つの翻訳対象と存在する場合だけ旧英日文脈を組み立てる。"""

    item = {"span_id": span.id, "source": span.source}
    previous = previous_context.get(span.id)
    if previous is not None:
        item["previous_source"] = previous[0]
        item["previous_translation"] = previous[1]
    return item


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
    """TRANSLATEの適用外項目を処理ディレクトリ直下へ保存する。"""

    write_model(
        path,
        LLMTaskDiagnostics(
            task="TRANSLATE",
            diagnostics=diagnostics,
            updated_at=datetime.now(UTC),
        ),
    )
