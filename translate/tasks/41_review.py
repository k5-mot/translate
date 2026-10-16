"""問題指摘と修正候補を生成するREVIEW Task。"""

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from translate.adapters.artifact_store import (
    llm_call_id,
    load_model,
    write_model,
)
from translate.adapters.llm import (
    LLMClient,
    LLMInputExceededError,
    LLMOutputExceededError,
)
from translate.common.config import Config
from translate.models.artifacts import (
    LLMCallArtifact,
    LLMCallIndex,
    LLMTaskDiagnostics,
    ReviewResult,
)
from translate.models.document import TextSpan, TextUnit
from translate.models.review import (
    AlignmentResponse,
    Finding,
    ReviewResponse,
    ReviewTarget,
    Revision,
    TextEdit,
)
from translate.tasks import SavedLLMCalls


class ReviewTask:
    """原文と訳文の対応付け・評価を、共有する規則とCall保存先で実行する。"""

    def __init__(
        self, config: Config, task_directory: Path, rules: str, glossary: str
    ) -> None:
        """比較処理の依存関係と保存済み要求の管理を準備する。

        Args:
            config: LLM接続、応答件数および再試行の上限。
            task_directory: Callと評価結果の保存先。
            rules: 対応付けと品質評価の判断規則。
            glossary: 原文に関連する語を選ぶCSV用語集。
        """
        self.config = config
        self.task_directory = task_directory
        self.rules = rules
        self.calls = SavedLLMCalls("REVIEW", task_directory, rules, glossary)

    def run(
        self,
        targets: list[ReviewTarget],
        processing_directory: Path,
        *,
        operation: str = "evaluate",
        round_number: int = 0,
        publish: bool = True,
        client: LLMClient | None = None,
        span_owners: dict[str, str] | None = None,
    ) -> ReviewResult:
        """ReviewTargetをchunk化し、LLMの指摘と修正候補へ決定的なIDを付ける。

        Args:
            targets (list[ReviewTarget]): CHECKまたはREVIEW対象一覧。
            processing_directory (Path): 対象処理の成果物Directory。
            operation: 評価またはAgentが選んだ再確認。
            round_number: Agent操作の連番。
            publish: Translateの全対象完了時だけ最終結果を公開する。
            client: Agentから共有する接続と期限。省略時はTask用に作成する。
            span_owners: Span IDと所有TextUnit IDの対応。単一要素の対象は入力から補う。

        Returns:
            ReviewResult: ReviewTargetをchunk化し、LLMの指摘と修正候補へ決定的なIDを付ける。

        Raises:
            ValueError: `review model is required`と判定した場合。
        """

        if self.config.openai_review_model is None:
            raise ValueError("review model is required")
        self.task_directory.mkdir(parents=True, exist_ok=True)
        diagnostics_path = processing_directory / "task-review.json"
        diagnostics: list[str] = []
        _write_diagnostics(diagnostics_path, diagnostics)
        owns_client = client is None
        client = client or LLMClient(self.config)
        if owns_client:
            client.deadline = time.monotonic() + self.config.llm_task_deadline_seconds
        try:
            responses: list[tuple[str, ReviewResponse, list[ReviewTarget]]] = []
            owners = dict(span_owners or {})
            for target in targets:
                if len(target.target_ids) == 1:
                    for span in target.spans:
                        owners.setdefault(span.id, target.target_ids[0])
            # System、Schemaおよびmessage形式へ2,048 bytesを予約する。
            overhead = len(self.rules.encode("utf-8")) + 2048
            payload_budget = self.config.review_input_tokens - overhead
            envelope_bytes = len(
                _user_payload([], [], "", [], payload_budget).encode("utf-8")
            ) - _target_bytes([])
            for index, chunk in enumerate(
                _chunks(
                    targets,
                    self.config.review_max_targets,
                    payload_budget - envelope_bytes,
                )
            ):
                responses.extend(
                    self._execute(
                        client=client,
                        targets=chunk,
                        lineage=[f"chunk-{index:04d}"],
                        depth=0,
                        operation=operation,
                        round_number=round_number,
                        span_owners=owners,
                    )
                )
            findings: list[Finding] = []
            revisions: list[Revision] = []
            chunks_directory = self.task_directory / "chunks"
            for call_id, response, chunk in responses:
                write_model(chunks_directory / f"{call_id}.json", response)
                by_id = {target.id: target for target in chunk}
                chunk_findings: list[Finding] = []
                chunk_revisions: list[Revision] = []
                for index, item in enumerate(response.assessments, start=1):
                    if item.category is None or item.severity is None:
                        continue
                    target = by_id[item.target_id]
                    edits_by_unit: dict[str, list[TextEdit]] = {}
                    for edit in item.edits:
                        owner = owners[edit.span_id]
                        edits_by_unit.setdefault(owner, []).append(
                            TextEdit(span_id=edit.span_id, text=edit.text)
                        )
                    chunk_findings.append(
                        Finding(
                            id=f"review/{call_id}/finding-{index:04d}",
                            category=item.category,
                            severity=item.severity,
                            target_ids=list(edits_by_unit) or target.target_ids,
                            message=item.reason,
                        )
                    )
                    for owner, edits in edits_by_unit.items():
                        if len(edits) > self.config.review_max_edits_per_revision:
                            diagnostics.append(f"{call_id} edits_limit {owner}")
                        chunk_revisions.append(
                            Revision(
                                id=f"review/{call_id}/revision-{len(chunk_revisions) + 1:04d}",
                                target_id=owner,
                                edits=edits[
                                    : self.config.review_max_edits_per_revision
                                ],
                            )
                        )
                if len(chunk_findings) > self.config.review_max_findings:
                    diagnostics.append(f"{call_id} findings_limit")
                if len(chunk_revisions) > self.config.review_max_revisions:
                    diagnostics.append(f"{call_id} revisions_limit")
                findings.extend(chunk_findings[: self.config.review_max_findings])
                revisions.extend(chunk_revisions[: self.config.review_max_revisions])
            result = ReviewResult(
                targets=targets,
                reviewed_target_ids=[target.id for target in targets],
                findings=findings,
                revisions=revisions,
            )
            _write_diagnostics(diagnostics_path, diagnostics)
            if publish:
                write_model(
                    self.task_directory / "call-index.json",
                    LLMCallIndex(
                        task="REVIEW",
                        call_ids=list(
                            dict.fromkeys(call_id for call_id, _, _ in responses)
                        ),
                    ),
                )
                write_model(self.task_directory / "review.json", result)
            return result

        finally:
            if owns_client:
                client.client.close()

    def _execute(
        self,
        *,
        client: LLMClient,
        targets: list[ReviewTarget],
        lineage: list[str],
        depth: int,
        operation: str = "evaluate",
        round_number: int = 0,
        span_owners: dict[str, str] | None = None,
    ) -> list[tuple[str, ReviewResponse, list[ReviewTarget]]]:
        """対象を評価し、上限超過時は意味単位を保って分割する。

        Args:
            client: LLM接続。
            targets: 原文と訳文の比較対象。
            lineage: 入力分割の経路。
            depth: 現在の分割深度。
            operation: evaluateまたはrecheck。
            round_number: Agentが選んだ再確認の連番。
            span_owners: 修正対象の所属を検証するSpan IDとTextUnit IDの対応。

        Returns:
            Call ID、応答、対応する入力対象の組。

        Raises:
            LLMError: 要求が失敗、または最小単位で上限を超える場合。
            ValueError: 応答の確認済みIDが要求と一致しない場合。
        """
        target_ids = [target.id for target in targets]

        def validate(response: ReviewResponse) -> None:
            """品質確認済みIDが要求の全対象と一対一に対応することを検証する。

            Args:
                response: Schema検証済み応答。

            Raises:
                ValueError: 対象の欠落・重複、判定の矛盾、または所属外のSpan修正がある場合。
            """
            if sorted(item.target_id for item in response.assessments) != sorted(
                target_ids
            ):
                raise ValueError(
                    "REVIEW response must assess every requested target exactly once"
                )
            by_id = {target.id: target for target in targets}
            for item in response.assessments:
                if item.verdict == "correct":
                    if (
                        item.edits
                        or item.category is not None
                        or item.severity is not None
                    ):
                        raise ValueError(
                            "Correct targets require empty edits and null category and severity"
                        )
                    continue
                if not (item.category or "").strip() or item.severity is None:
                    raise ValueError("Issues require category and severity")
                target = by_id[item.target_id]
                selected_spans = {span.id for span in target.spans}
                if any(
                    edit.span_id not in selected_spans
                    or (span_owners or {}).get(edit.span_id) not in target.target_ids
                    for edit in item.edits
                ):
                    raise ValueError(
                        "Assessment references an unselected or unowned span"
                    )

        try:
            call_id, response = self.calls.request(
                client,
                operation,
                round_number,
                [f"review:{key}" for key in target_ids],
                {
                    "targets": [_target_payload(target) for target in targets],
                    "lineage": lineage,
                },
                "\n".join(target.source for target in targets),
                ReviewResponse,
                "Return assessments, one object for each input targets[].id, in input order. "
                "Each assessment contains target_id (the complete input targets[].id), reason (one brief sentence), "
                "verdict (correct or issue), and edits (span_id and replacement text). "
                "For an issue, also provide category and severity (info, warning or error); for correct use null for both. "
                "Compare the original source with all current spans[].text for that target. "
                "Use correct when the current translation needs no change; then edits must be empty. "
                "Use issue only for a concrete defect, and propose replacements for the affected spans. "
                "A correctly preserved technical identifier is correct, even though it is English. "
                "Ordinary English prose left untranslated is an issue. Explain the conclusion in Japanese.",
                validate,
            )
        except (LLMInputExceededError, LLMOutputExceededError):
            groups = (
                _retry_groups(targets)
                if depth < self.config.llm_split_max_depth
                else ()
            )
            if not groups:
                raise
            parent_id = llm_call_id(
                "REVIEW",
                [f"review:{key}" for key in target_ids],
                [],
                operation=operation,
                round_number=round_number,
            )
            parent_path = self.task_directory / "calls" / parent_id / "call.json"
            parent = load_model(parent_path, LLMCallArtifact)
            parent.status = "split"
            write_model(parent_path, parent)
            result = []
            for index, group in enumerate(groups):
                result.extend(
                    self._execute(
                        client=client,
                        targets=group,
                        lineage=[*lineage, str(index)],
                        depth=depth + 1,
                        operation=operation,
                        round_number=round_number,
                        span_owners=span_owners,
                    )
                )
            return result
        else:
            return [(call_id, response, targets)]

    def match_documents(
        self,
        units: dict[str, list[TextUnit]],
        client: LLMClient,
        round_number: int,
    ) -> tuple[str, AlignmentResponse]:
        """Agentが選んだ原文と訳文の対応候補を取得し、参照と網羅性を検証する。

        Args:
            units: sourceとtranslationの候補TextUnit。
            client: LLM接続。
            round_number: Agent操作の連番。

        Returns:
            成功Call IDと対応付け応答。

        Raises:
            ValueError: 選択対象と対応groupのID・種別・網羅性が矛盾する場合。
            LLMError: LLM要求が失敗した場合。
        """
        expected = {
            role: [unit.id for unit in values] for role, values in units.items()
        }

        def validate(response: AlignmentResponse) -> None:
            """選択した各IDが一つのgroupに属し、未対応には理由があることを確認する。

            Args:
                response: 対応付け応答。

            Raises:
                ValueError: 対応関係が不正、または範囲外の結果を含む場合。
            """
            for role in ("source", "translation"):
                found = [
                    key
                    for group in response.groups
                    for key in getattr(group, f"{role}_ids")
                ]
                if sorted(found) != sorted(expected[role]):
                    raise ValueError(
                        "Correspondence must cover the selected IDs exactly once. "
                        f"{role}: missing={sorted(set(expected[role]) - set(found))}; "
                        f"duplicate={sorted({key for key in found if found.count(key) > 1})}; "
                        f"unknown={sorted(set(found) - set(expected[role]))}"
                    )
            for group in response.groups:
                correct = (
                    "matched"
                    if group.source_ids and group.translation_ids
                    else "source_only"
                    if group.source_ids
                    else "translation_only"
                )
                if group.kind != correct or not (
                    group.source_ids or group.translation_ids
                ):
                    raise ValueError("Invalid correspondence kind")
                if group.kind != "matched" and not (group.reason or "").strip():
                    raise ValueError("Unmatched correspondence requires a reason")

        payload: dict[str, object] = {
            role: [{"id": unit.id, "text": unit.text("source")} for unit in values]
            for role, values in units.items()
        }
        return self.calls.request(
            client,
            "match",
            round_number,
            [f"{role}:{key}" for role, keys in expected.items() for key in keys],
            payload,
            "\n".join(unit.text("source") for unit in units["source"]),
            AlignmentResponse,
            '{"groups":[{"reason":"brief content comparison",'
            '"kind":"matched|source_only|translation_only",'
            '"source_ids":["id"],"translation_ids":["id"]}]}. '
            "Every source ID and every translation ID must appear exactly once, including unmatched IDs. "
            "The source and translation arrays are independent candidate pools, not parallel rows. "
            "For each source, search ALL translation candidates for the same content; "
            "never pair by array position or similar IDs. "
            "Match only the same content, not related topics. "
            "When two texts do not correspond, return two groups: source_only and translation_only, "
            "each with its own IDs and reason. "
            "For every group, first name the actual source text and corresponding translation text in reason, "
            "or briefly state which content has no counterpart. "
            "Then select the kind and the IDs that belong to those texts. "
            "Do not use generic reasons such as matched content. "
            "Keep separate table cells separate: an identifier, its description, and its value are distinct content, even in the same row. "
            "A group with multiple units is valid only when those units are split fragments of the SAME content expressed on the other side. "
            "Account for the content of EVERY selected unit on BOTH sides; do not absorb an unmatched unit into a related match. "
            "If the identifier itself has no counterpart in this candidate pool, leave it source_only or translation_only.",
            validate,
        )


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


def _write_diagnostics(path: Path, diagnostics: list[str]) -> None:
    """REVIEWの適用外項目を処理ディレクトリ直下へ保存する。

    Args:
        path (Path): REVIEW診断を書き込むJSON FileのPath。
        diagnostics (list[str]): 検証中に追記する診断Message列。
    """

    write_model(
        path,
        LLMTaskDiagnostics(
            task="REVIEW",
            diagnostics=diagnostics,
            updated_at=datetime.now(UTC),
        ),
    )
