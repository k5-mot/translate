"""REVIEW対象の分割とLLM payload作成。"""

import json
import re

from translate.adapters.llm import LLMInputExceededError
from translate.models.document import TextSpan
from translate.models.review import ReviewTarget


def _chunks(
    targets: list[ReviewTarget],
    maximum_targets: int,
    maximum_bytes: int,
) -> list[list[ReviewTarget]]:
    """ReviewTargetを件数と保守的UTF-8 byte上限内へchunk化する。

    Args:
        targets (list[ReviewTarget]): CHECKまたはREVIEW対象一覧。
        maximum_targets (int): 一つのREVIEW Callへ含める最大Target数。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        list[list[ReviewTarget]]: ReviewTargetを件数と保守的UTF-8 byte上限内へchunk化する。
    """

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
    """長大な比較対象を原文断片と翻訳Span群へ欠落なく分ける。

    Args:
        target (ReviewTarget): 入力上限へ収めるReview対象。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        list[ReviewTarget]: 長大な比較対象を原文断片と翻訳Span群へ欠落なく分ける。

    Raises:
        ValueError: `f'single ReviewTarget exceeds review input limit: {target.id}'`と判定した場合。
    """

    if _target_bytes([target]) <= maximum_bytes:
        return [target]
    span_groups = _split_spans(target, maximum_bytes) or [[]]
    parts: list[ReviewTarget] = []
    remaining_source = target.source
    for index, spans in enumerate(span_groups):
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
        source = _source_prefix(part, remaining_source, maximum_bytes)
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
    """ReviewTargetへ収まる最長の原文prefixを文・改行の境界で返す。

    Args:
        target (ReviewTarget): 原文Prefixを取得するReview対象。
        source (str): 変換または検証対象の入力Source。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        str: ReviewTargetへ収まる最長の原文prefixを文・改行の境界で返す。
    """

    end = 0
    boundaries = [
        match.end()
        for match in re.finditer(
            r"(?<![A-Z]\.)(?<=[.!?])\s+|(?<=[\u3002\uff01\uff1f])\s*|\n+", source
        )
    ]
    for boundary in [*boundaries, len(source)]:
        candidate = target.model_copy(update={"source": source[:boundary]})
        if _target_bytes([candidate]) > maximum_bytes:
            break
        end = boundary
    return source[:end]


def _split_spans(target: ReviewTarget, maximum_bytes: int) -> list[list[TextSpan]]:
    """修正単位のSpanを壊さず、REVIEW payloadのbyte上限へ分ける。

    Args:
        target (ReviewTarget): Span単位へ分割するReview対象。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        list[list[TextSpan]]: 修正単位のSpanを壊さず、REVIEW payloadのbyte上限へ分ける。

    Raises:
        ValueError: `f'single ReviewTarget span exceeds review input limit:
            {span.id}'`と判定した場合。
    """

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
    """REVIEW promptへ渡す対象の保守的byte数を返す。

    Args:
        targets (list[ReviewTarget]): CHECKまたはREVIEW対象一覧。

    Returns:
        int: REVIEW promptへ渡す対象の保守的byte数を返す。
    """

    value = [_target_payload(target) for target in targets]
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _target_payload(target: ReviewTarget) -> dict[str, object]:
    """重複本文と書式情報を除き、REVIEWに必要な対象情報だけを返す。

    Args:
        target (ReviewTarget): LLM Payloadへ変換するReview対象。

    Returns:
        dict[str, object]: 重複本文と書式情報を除き、REVIEWに必要な対象情報だけを返す。
    """

    return {
        "id": target.id,
        "source": target.source,
        "target_ids": target.target_ids,
        "spans": [{"span_id": span.id, "text": span.text()} for span in target.spans],
    }


def _retry_groups(targets: list[ReviewTarget]) -> tuple[list[ReviewTarget], ...]:
    """上限超過したCallを、単一の事前分割済み対象も含めて縮小する。

    Args:
        targets (list[ReviewTarget]): CHECKまたはREVIEW対象一覧。

    Returns:
        tuple[list[ReviewTarget], ...]: 上限超過したCallを、単一の事前分割済み対象も含めて縮小する。
    """

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


def _user_payload(
    targets: list[ReviewTarget],
    findings: list[dict[str, object]],
    glossary: str,
    rag: list[dict[str, object]],
    maximum_bytes: int,
) -> str:
    """任意の参照情報を必要に応じて除外し、入力上限内のJSON payloadを作る。

    Args:
        targets (list[ReviewTarget]): CHECKまたはREVIEW対象一覧。
        findings (list[dict[str, object]]): LLMへ渡す既存Review指摘。
        glossary (str): 対象文書へ適用するCSV形式の用語集。
        rag (list[dict[str, object]]): Promptへ含める検索済み参考文列。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        str: 低順位RAGを必要に応じて除外し、入力上限内のJSON payloadを作る。

    Raises:
        LLMInputExceededError: `review prompt exceeds input limit`と判定した場合。
    """

    selected = list(rag)
    selected_glossary = glossary
    selected_findings = list(findings)
    while True:
        value = json.dumps(
            {
                "glossary": selected_glossary,
                "references": selected,
                "check_findings": selected_findings,
                "targets": [_target_payload(target) for target in targets],
            },
            ensure_ascii=False,
        )
        if len(value.encode("utf-8")) <= maximum_bytes:
            return value
        if selected:
            selected.pop()
        elif selected_glossary:
            selected_glossary = ""
        elif selected_findings:
            selected_findings = []
        else:
            raise LLMInputExceededError("review prompt exceeds input limit")
