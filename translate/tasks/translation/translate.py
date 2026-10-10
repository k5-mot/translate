"""TextSpanを生成LLMで翻訳するTRANSLATE Task。"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from translate.adapters.embedding import embed
from translate.adapters.llm import (
    LLMClient,
    LLMError,
    LLMInputExceededError,
    LLMInvalidResponseError,
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
    """対象Spanをchunk化し、Call成果を再利用しながら日本語訳を設定する。

    Args:
        document (Document): 変換または検証対象のDocument。
        task_directory (Path): 対象Taskの成果物Directory。
        processing_directory (Path): 対象処理の成果物Directory。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        rules (str): LLM Promptへ含める追加規則。
        glossary (str): 対象文書へ適用するCSV形式の用語集。
        previous_context (TranslationContext | None): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        Document: 対象Spanをchunk化し、Call成果を再利用しながら日本語訳を設定する。

    Raises:
        ValueError: `translation model is required`と判定した場合。
    """

    if config.openai_translation_model is None:
        raise ValueError("translation model is required")
    task_directory.mkdir(parents=True, exist_ok=True)
    diagnostics_path = processing_directory / "task-translate.json"
    diagnostics: list[str] = []
    _write_diagnostics(diagnostics_path, diagnostics)
    updated = document.model_copy(deep=True)
    client = LLMClient(config)
    context = previous_context or {}
    overhead = len(rules.encode("utf-8")) + 2048
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
        target_ids = set(
            load_model(
                task_directory / "calls" / call_id / "call.json", LLMCallArtifact
            ).target_ids
        )
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
            if item.span_id not in target_ids:
                diagnostics.append(f"{call_id} unexpected_span {item.span_id}")
                continue
            span.translated = _restore_leader(span.source, item.text)
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
    """TextUnitを通常は分断せず、件数と保守的byte上限内へchunk化する。

    Args:
        document (Document): 変換または検証対象のDocument。
        maximum_units (int): 一つのTRANSLATE Callへ含める最大TextUnit数。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。
        previous_context (TranslationContext | None): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        list[list[TextSpan]]: TextUnitを通常は分断せず、件数と保守的byte上限内へchunk化する。
    """

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
    """単一TextUnitだけが上限を超える場合にSpan境界で分割する。

    Args:
        group (list[TextSpan]): 同じTextUnitに属する翻訳対象Span列。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。
        previous_context (TranslationContext): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        list[list[TextSpan]]: 単一TextUnitだけが上限を超える場合にSpan境界で分割する。

    Raises:
        ValueError: `f'single TextSpan exceeds translation input limit: {span.id}'`と判定した場合。
    """

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
    """prompt overheadを含む保守的なUTF-8 byte数を計算する。

    Args:
        spans (list[TextSpan]): 翻訳または分割対象のTextSpan列。
        previous_context (TranslationContext): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        int: prompt overheadを含む保守的なUTF-8 byte数を計算する。
    """

    payload = [_translation_item(span, previous_context) for span in spans]
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 1024


def _plausible_translation(source: str, translation: str) -> bool:
    """CHECKと同じ長さ閾値で空訳・極端な長さ差・長文の丸写しを拒否する。"""

    original, leader = _leader_parts(" ".join(source.split()))
    target, _ = _leader_parts(" ".join(translation.split()))
    if not target:
        return False
    if (
        leader
        and re.search(r"[A-Za-z]", original)
        and not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", target)
    ):
        return False
    if len(original) >= 80 and len(target) < len(original) * 0.15:
        return False
    if (
        len(original) >= 80
        and len(original.split()) >= 8
        and original.casefold() == target.casefold()
    ):
        return False
    return not (
        len(original) > 0 and len(target) >= 100 and len(target) > len(original) * 5
    )


def _leader_parts(value: str) -> tuple[str, str]:
    """末尾の目次用点線を本文と装飾部分に分ける。

    Args:
        value (str): 原文または訳文のText。

    Returns:
        tuple[str, str]: 点線前の本文と、空白を含む点線部分。
    """

    match = re.fullmatch(r"(.*?\S)(\s+[.…。]{6,}\s*)", value, flags=re.DOTALL)
    return (match.group(1), match.group(2)) if match else (value, "")


def _restore_leader(source: str, translation: str) -> str:
    """翻訳した項目名へ原文の目次用点線を戻す。

    Args:
        source (str): 点線を含む可能性がある原文。
        translation (str): LLMから得た項目名の訳文。

    Returns:
        str: 元の点線を末尾へ戻した訳文。
    """

    _, leader = _leader_parts(source)
    return re.sub(r"[ .…。]+$", "", translation) + leader if leader else translation


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
    """一つの論理Callを再利用または送信し、必要時だけ子Callへ分割する。

    Args:
        client (LLMClient): 外部処理を呼び出すClient。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        spans (list[TextSpan]): 翻訳または分割対象のTextSpan列。
        task_directory (Path): 対象Taskの成果物Directory。
        rules (str): LLM Promptへ含める追加規則。
        glossary (str): 対象文書へ適用するCSV形式の用語集。
        lineage (list[str]): 親から子へ連なるLLM Call ID列。
        depth (int): 分割LLM Callの現在の深さ。
        allow_missing_retry (bool): 欠落IDをまとめて再送する初回Callかどうか。
        diagnostics (list[str]): 検証中に追記する診断Message列。
        previous_context (TranslationContext): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        list[tuple[str, TranslationResponse]]: 一つの論理Callを再利用または送信し、必要時だけ子Callへ分割する。
    """

    target_ids = [span.id for span in spans]
    call_id = llm_call_id("TRANSLATE", target_ids, lineage)
    call_directory = task_directory / "calls" / call_id
    source = "\n".join(_leader_parts(span.source)[0] for span in spans)
    leader_only = all(_leader_parts(span.source)[1] for span in spans)
    payload_budget = config.translate_input_tokens - len(rules.encode("utf-8")) - 2048
    selected_glossary = (
        ""
        if leader_only
        else relevant_glossary(
            glossary,
            source,
            maximum_bytes=max(0, payload_budget // 3),
        )
    )
    rag = [] if leader_only else _rag_context(config, source)
    fingerprint = canonical_hash(
        {
            "task": "TRANSLATE",
            "schema": 5 if any(_leader_parts(span.source)[1] for span in spans) else 3,
            "targets": [(span.id, span.source) for span in spans],
            "previous": [(span.id, previous_context.get(span.id)) for span in spans],
            "rules": canonical_hash(rules),
            "glossary": canonical_hash(selected_glossary),
            "rag": [(item.get("id"), item.get("content_sha256")) for item in rag],
            "model": config.openai_translation_model,
            "mode": config.llm_structured_output_mode,
            "reasoning_effort": "none",
            "llm_endpoint": config.openai_llm_base_url or config.openai_base_url,
            "temperature": 0.7,
            "repetition_penalty": 1.01,
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
            task="TRANSLATE",
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
                selected_glossary,
                rag,
                payload_budget,
                previous_context,
            ),
            contract=(
                'Return {"translations":[{"span_id":string,"text":string}]}. '
                f"Return exactly {len(spans)} nonempty items, one for each span_id."
            ),
            native_schema=_schema(len(spans)),
            input_tokens=config.translate_input_tokens,
            output_tokens=config.translate_output_tokens,
        )
    except (LLMInputExceededError, LLMOutputExceededError) as error:
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
    translations: dict[str, str] = {}
    duplicates: set[str] = set()
    for item in response.translations:
        if item.span_id in translations:
            duplicates.add(item.span_id)
        translations[item.span_id] = item.text
    missing = [
        span
        for span in spans
        if span.id in duplicates
        or not _plausible_translation(span.source, translations.get(span.id, ""))
    ]
    suspect = [span for span in missing if translations.get(span.id, "").strip()]
    diagnostics.extend(f"{call_id} untrusted_translation {span.id}" for span in suspect)
    prompt_fallback = bool(suspect) and config.llm_structured_output_mode != "prompt"
    groups: list[list[TextSpan]] = []
    if prompt_fallback:
        groups = [[span] for span in missing]
    elif missing and allow_missing_retry:
        groups = [missing]
    elif missing and len(spans) > 1 and depth < config.llm_split_max_depth:
        if len(missing) == 1:
            groups = [missing]
        else:
            middle = len(missing) // 2
            groups = [missing[:middle], missing[middle:]]
    if prompt_fallback:
        child_lineages = [
            [*lineage, f"quality-{index}"] for index in range(len(groups))
        ]
    else:
        child_lineages = [
            [*lineage, "missing"]
            if allow_missing_retry
            else [*lineage, f"missing-{index}"]
            for index in range(len(groups))
        ]
    child_ids = [
        llm_call_id("TRANSLATE", [span.id for span in group], child_lineage)
        for group, child_lineage in zip(groups, child_lineages, strict=True)
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
    if missing and not groups:
        raise LLMInvalidResponseError(
            f"翻訳対象 {missing[0].id} の完全な訳文が得られません。対策: "
            "翻訳modelとLLM_STRUCTURED_OUTPUT_MODEを確認して再開してください。"
        )
    retry_config = (
        config.model_copy(update={"llm_structured_output_mode": "prompt"})
        if prompt_fallback
        else config
    )
    retry_client = LLMClient(retry_config) if prompt_fallback else client
    for group, child_lineage in zip(groups, child_lineages, strict=True):
        values.extend(
            _execute(
                client=retry_client,
                config=retry_config,
                spans=group,
                task_directory=task_directory,
                rules=rules,
                glossary=glossary,
                lineage=child_lineage,
                depth=depth if allow_missing_retry else depth + 1,
                allow_missing_retry=len(group) == 1 and len(spans) > 1,
                diagnostics=diagnostics,
                previous_context=previous_context,
            )
        )
    return values


def _split_call(
    *,
    artifact: LLMCallArtifact,
    error: LLMInputExceededError | LLMOutputExceededError,
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
    """出力超過した親Callを半分の子Callへ置換する。

    Args:
        artifact (LLMCallArtifact): 状態または応答を更新するLLM Call Artifact。
        error (LLMInputExceededError | LLMOutputExceededError): 記録または分類する例外。
        client (LLMClient): 外部処理を呼び出すClient。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        spans (list[TextSpan]): 翻訳または分割対象のTextSpan列。
        task_directory (Path): 対象Taskの成果物Directory。
        rules (str): LLM Promptへ含める追加規則。
        glossary (str): 対象文書へ適用するCSV形式の用語集。
        lineage (list[str]): 親から子へ連なるLLM Call ID列。
        depth (int): 分割LLM Callの現在の深さ。
        diagnostics (list[str]): 検証中に追記する診断Message列。
        previous_context (TranslationContext): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        list[tuple[str, TranslationResponse]]: 出力超過した親Callを半分の子Callへ置換する。

    Raises:
        LLMInputExceededError | LLMOutputExceededError:
            親Callで分割できない入力上限または出力上限Errorを再送出する場合。
    """

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
    """TRANSLATE専用の浅いnative JSON Schemaを作る。

    Args:
        maximum_items (int): Structured Outputへ含める最大要素数。

    Returns:
        dict[str, object]: TRANSLATE専用の浅いnative JSON Schemaを作る。
    """

    return {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "minItems": maximum_items,
                "maxItems": maximum_items,
                "items": {
                    "type": "object",
                    "properties": {
                        "span_id": {"type": "string"},
                        "text": {"type": "string", "minLength": 1},
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
    """設定済みの場合だけ英語原文をEmbeddingし、上位5件の参照文脈を得る。

    Args:
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        query (str): RAG検索へ使用する原文Query。

    Returns:
        list[dict[str, object]]: 設定済みの場合だけ英語原文をEmbeddingし、上位5件の参照文脈を得る。
    """

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
    """低順位RAGを必要に応じて除外し、入力上限内のJSON payloadを作る。

    Args:
        spans (list[TextSpan]): 翻訳または分割対象のTextSpan列。
        glossary (str): 対象文書へ適用するCSV形式の用語集。
        rag (list[dict[str, object]]): Promptへ含める検索済み参考文列。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。
        previous_context (TranslationContext | None): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        str: 低順位RAGを必要に応じて除外し、入力上限内のJSON payloadを作る。

    Raises:
        LLMInputExceededError: `translation prompt exceeds input limit`と判定した場合。
    """

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
            raise LLMInputExceededError("translation prompt exceeds input limit")
        selected.pop()


def _translation_item(
    span: TextSpan, previous_context: TranslationContext
) -> dict[str, str]:
    """一つの翻訳対象と存在する場合だけ旧英日文脈を組み立てる。

    Args:
        span (TextSpan): 変換またはPayload作成対象のTextSpan。
        previous_context (TranslationContext): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        dict[str, str]: 一つの翻訳対象と存在する場合だけ旧英日文脈を組み立てる。
    """

    item = {"span_id": span.id, "source": _leader_parts(span.source)[0]}
    previous = previous_context.get(span.id)
    if previous is not None:
        item["previous_source"] = previous[0]
        item["previous_translation"] = previous[1]
    return item


def _previous_attempts(directory: Path) -> int:
    """Resume前の累計試行数を読める場合だけ引き継ぐ。

    Args:
        directory (Path): LLM Call Artifactの保存Directory。

    Returns:
        int: Resume前の累計試行数を読める場合だけ引き継ぐ。
    """

    path = directory / "call.json"
    if not path.is_file():
        return 0
    try:
        return load_model(path, LLMCallArtifact).attempts
    except Exception:  # noqa: BLE001
        return 0


def _write_diagnostics(path: Path, diagnostics: list[str]) -> None:
    """TRANSLATEの適用外項目を処理ディレクトリ直下へ保存する。

    Args:
        path (Path): TRANSLATE診断を書き込むJSON FileのPath。
        diagnostics (list[str]): 検証中に追記する診断Message列。
    """

    write_model(
        path,
        LLMTaskDiagnostics(
            task="TRANSLATE",
            diagnostics=diagnostics,
            updated_at=datetime.now(UTC),
        ),
    )
