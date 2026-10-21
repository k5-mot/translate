"""TextSpanを生成LLMで翻訳するTRANSLATE Task。"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from translate.adapters.artifact_store import (
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
from translate.adapters.embedding import EmbeddingClient
from translate.adapters.glossary import Glossary
from translate.adapters.llm import (
    LLMClient,
    LLMError,
    LLMInputExceededError,
    LLMInvalidResponseError,
    LLMOutputExceededError,
)
from translate.adapters.qdrant import QdrantStore
from translate.common.config import Config
from translate.models.artifacts import LLMCallArtifact, LLMCallIndex, LLMTaskDiagnostics
from translate.models.document import Document, TextSpan

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


class TranslationTask:
    """翻訳の設定・参照用語と保存先を保持し、分割要求と再開を管理する。"""

    def __init__(
        self,
        config: Config,
        task_directory: Path,
        rules: str,
        glossary: str,
        previous_context: TranslationContext | None = None,
    ) -> None:
        """一つの翻訳Taskに適用する依存関係を保持する。

        Args:
            config: LLM接続、入力予算および再試行の設定。
            task_directory: Callと翻訳結果を保存する場所。
            rules: 翻訳Promptへ追加する規則。
            glossary: 原文と照合するCSV形式の用語集。
            previous_context: 再翻訳で参照するSpanごとの旧原文と旧訳。
        """
        self.config = config
        self.task_directory = task_directory
        self.rules = rules
        self.glossary = Glossary(glossary)
        self.previous_context = dict(previous_context or {})
        self.embedding = EmbeddingClient(config)

    def run(
        self,
        document: Document,
        processing_directory: Path,
    ) -> Document:
        """対象Spanをchunk化し、Call成果を再利用しながら日本語訳を設定する。

        Args:
            document (Document): 変換または検証対象のDocument。
            processing_directory (Path): 対象処理の成果物Directory。

        Returns:
            Document: 対象Spanをchunk化し、Call成果を再利用しながら日本語訳を設定する。

        Raises:
            ValueError: `translation model is required`と判定した場合。
        """

        if self.config.openai_translation_model is None:
            raise ValueError("translation model is required")
        self.task_directory.mkdir(parents=True, exist_ok=True)
        diagnostics_path = processing_directory / "task-translate.json"
        diagnostics: list[str] = []
        _write_diagnostics(diagnostics_path, diagnostics)
        updated = document.model_copy(deep=True)
        client = LLMClient(self.config)
        client.deadline = time.monotonic() + self.config.llm_task_deadline_seconds
        try:
            overhead = len(self.rules.encode("utf-8")) + 2048
            chunks = _chunks(
                updated,
                self.config.translate_max_units,
                self.config.translate_input_tokens - overhead,
                self.previous_context,
            )
            responses: list[tuple[str, TranslationResponse]] = []
            for index, spans in enumerate(chunks):
                responses.extend(
                    self._execute(
                        client=client,
                        spans=spans,
                        lineage=[f"chunk-{index:04d}"],
                        depth=0,
                        allow_missing_retry=True,
                    )
                )
            span_index = {
                span.id: span
                for _, unit in updated.text_units()
                for span in unit.spans
                if span.kind not in {"code", "line_break"}
            }
            for call_id, response in responses:
                target_ids = set(
                    load_model(
                        self.task_directory / "calls" / call_id / "call.json",
                        LLMCallArtifact,
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
                    span.translated = item.text
            _write_diagnostics(diagnostics_path, diagnostics)
            write_model(
                self.task_directory / "call-index.json",
                LLMCallIndex(
                    task="TRANSLATE",
                    call_ids=list(dict.fromkeys(call_id for call_id, _ in responses)),
                ),
            )
            write_model(self.task_directory / "document.json", updated)
            chunks_directory = self.task_directory / "chunks"
            for call_id, response in responses:
                write_model(chunks_directory / f"{call_id}.json", response)
            return updated
        finally:
            client.client.close()

    def _execute(
        self,
        *,
        client: LLMClient,
        spans: list[TextSpan],
        lineage: list[str],
        depth: int,
        allow_missing_retry: bool,
    ) -> list[tuple[str, TranslationResponse]]:
        """一つの論理Callを再利用または送信し、必要時だけ子Callへ分割する。

        Args:
            client (LLMClient): 外部処理を呼び出すClient。
            spans (list[TextSpan]): 翻訳または分割対象のTextSpan列。
            lineage (list[str]): 親から子へ連なるLLM Call ID列。
            depth (int): 分割LLM Callの現在の深さ。
            allow_missing_retry (bool): 欠落IDをまとめて再送する初回Callかどうか。

        Returns:
            list[tuple[str, TranslationResponse]]: 一つの論理Callを再利用または送信し、必要時だけ子Callへ分割する。
        """

        target_ids = [span.id for span in spans]
        call_id = llm_call_id("TRANSLATE", target_ids, lineage)
        call_directory = self.task_directory / "calls" / call_id
        fingerprint = canonical_hash(
            {
                "task": "TRANSLATE",
                "operation": "translate",
                "targets": [(span.id, span.source) for span in spans],
                "previous": [
                    (span.id, self.previous_context.get(span.id)) for span in spans
                ],
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
            returned_ids = [item.span_id for item in response.translations]
            if all(returned_ids.count(span.id) == 1 for span in spans):
                return [(call_id, response)]
        source = "\n".join(span.source for span in spans)
        payload_budget = (
            self.config.translate_input_tokens - len(self.rules.encode("utf-8")) - 2048
        )
        selected_glossary = self.glossary.select(
            source, maximum_bytes=max(0, payload_budget // 3)
        )
        rag = self._rag_context(source)
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
                model=self.config.openai_translation_model or "",
                response_type=TranslationResponse,
                system=(
                    "Translate each English source into natural Japanese. Preserve IDs and "
                    "return JSON only. Translate headings, captions, short labels and sample prose too; "
                    "these are not identifiers to preserve. Keep code, URLs, mathematical notation "
                    "and actual proper names unchanged. When previous_source and previous_translation are "
                    "present, use them only as context for translating the current source."
                    "\n\n" + self.rules
                ),
                user=_user_payload(
                    spans,
                    selected_glossary,
                    rag,
                    payload_budget,
                    self.previous_context,
                ),
                contract=(
                    'Return {"translations":[{"span_id":string,"text":string}]}. '
                    f"Return exactly {len(spans)} items, one for each span_id."
                ),
                native_schema=_schema(len(spans)),
                input_tokens=self.config.translate_input_tokens,
                output_tokens=self.config.translate_output_tokens,
            )
        except (LLMInputExceededError, LLMOutputExceededError) as error:
            return self._split_call(
                artifact=artifact,
                error=error,
                client=client,
                spans=spans,
                lineage=lineage,
                depth=depth,
            )
        except LLMError as error:
            fail_llm_call(call_directory, artifact, error, attempts=1)
            raise
        response = result.response
        # 長いJSON Pointerを生成させず、要求内の連番を保存前に元のSpan IDへ戻す。
        original_ids = {str(index): span.id for index, span in enumerate(spans, 1)}
        for item in response.translations:
            item.span_id = original_ids.get(item.span_id, item.span_id)
        translations: dict[str, str] = {}
        duplicates: set[str] = set()
        for item in response.translations:
            # LLMがJSON Pointerの先頭#だけ落とした場合は、要求済みIDに限って復元する。
            if item.span_id.startswith("/") and f"#{item.span_id}" in target_ids:
                item.span_id = f"#{item.span_id}"
            if item.span_id in translations:
                duplicates.add(item.span_id)
            translations[item.span_id] = item.text
        missing = [
            span
            for span in spans
            if span.id in duplicates or span.id not in translations
        ]
        groups: list[list[TextSpan]] = []
        if missing and allow_missing_retry:
            groups = [missing]
        elif missing and len(spans) > 1 and depth < self.config.llm_split_max_depth:
            if len(missing) == 1:
                groups = [missing]
            else:
                middle = len(missing) // 2
                groups = [missing[:middle], missing[middle:]]
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
        for group, child_lineage in zip(groups, child_lineages, strict=True):
            values.extend(
                self._execute(
                    client=client,
                    spans=group,
                    lineage=child_lineage,
                    depth=depth if allow_missing_retry else depth + 1,
                    allow_missing_retry=(len(group) == 1 and len(spans) > 1),
                )
            )
        return values

    def _split_call(
        self,
        *,
        artifact: LLMCallArtifact,
        error: LLMInputExceededError | LLMOutputExceededError,
        client: LLMClient,
        spans: list[TextSpan],
        lineage: list[str],
        depth: int,
    ) -> list[tuple[str, TranslationResponse]]:
        """出力超過した親Callを半分の子Callへ置換する。

        Args:
            artifact (LLMCallArtifact): 状態または応答を更新するLLM Call Artifact。
            error (LLMInputExceededError | LLMOutputExceededError): 記録または分類する例外。
            client (LLMClient): 外部処理を呼び出すClient。
            spans (list[TextSpan]): 翻訳または分割対象のTextSpan列。
            lineage (list[str]): 親から子へ連なるLLM Call ID列。
            depth (int): 分割LLM Callの現在の深さ。

        Returns:
            list[tuple[str, TranslationResponse]]: 出力超過した親Callを半分の子Callへ置換する。

        Raises:
            LLMInputExceededError | LLMOutputExceededError:
                親Callで分割できない入力上限または出力上限Errorを再送出する場合。
        """

        parent_directory = self.task_directory / "calls" / artifact.call_id
        if len(spans) < 2 or depth >= self.config.llm_split_max_depth:
            fail_llm_call(parent_directory, artifact, error, attempts=1)
            raise error
        middle = len(spans) // 2
        groups = (spans[:middle], spans[middle:])
        child_ids = [
            llm_call_id(
                "TRANSLATE", [span.id for span in group], [*lineage, str(index)]
            )
            for index, group in enumerate(groups)
        ]
        mark_split_llm_call(parent_directory, artifact, child_ids)
        results: list[tuple[str, TranslationResponse]] = []
        for index, group in enumerate(groups):
            results.extend(
                self._execute(
                    client=client,
                    spans=group,
                    lineage=[*lineage, str(index)],
                    depth=depth + 1,
                    allow_missing_retry=True,
                )
            )
        return results

    def _rag_context(self, query: str) -> list[dict[str, object]]:
        """設定済みの場合だけ英語原文をEmbeddingし、上位5件の参照文脈を得る。

        Args:
            query (str): RAG検索へ使用する原文Query。

        Returns:
            list[dict[str, object]]: 設定済みの場合だけ英語原文をEmbeddingし、上位5件の参照文脈を得る。
        """

        if not query.strip() or not bool(
            self.config.qdrant_uri and self.config.openai_embedding_model
        ):
            return []
        vector = self.embedding.embed([query])[0]
        with QdrantStore(self.config) as store:
            return store.search(vector, limit=5)


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
        for _, unit in document.text_units()
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


def _user_payload(
    spans: list[TextSpan],
    glossary: str,
    rag: list[dict[str, object]],
    maximum_bytes: int,
    previous_context: TranslationContext | None = None,
) -> str:
    """要求内の連番でSpanを識別し、低順位RAGを除いて入力枠へ収める。

    Args:
        spans (list[TextSpan]): 翻訳または分割対象のTextSpan列。
        glossary (str): 対象文書へ適用するCSV形式の用語集。
        rag (list[dict[str, object]]): Promptへ含める検索済み参考文列。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。
        previous_context (TranslationContext | None): 再翻訳時に参照する旧原文と旧訳。

    Returns:
        str: span_idを要求内の1始まりの連番にしたJSON payload。

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
                "items": [
                    {**_translation_item(span, context), "span_id": str(index)}
                    for index, span in enumerate(spans, 1)
                ],
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

    item = {"span_id": span.id, "source": span.source}
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
