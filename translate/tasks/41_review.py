"""問題指摘と修正候補を生成するREVIEW Task。"""

import re
import time
from datetime import date
from pathlib import Path

from translate.adapters.artifact_store import (
    llm_call_id,
    load_model,
    write_model,
    write_task_diagnostics,
)
from translate.adapters.llm import (
    LLMClient,
    LLMInputExceededError,
    LLMInvalidResponseError,
    LLMOutputExceededError,
)
from translate.common.config import Config
from translate.models.artifacts import (
    LLMCallArtifact,
    LLMCallIndex,
    ReviewResult,
)
from translate.models.document import TextUnit
from translate.models.review import (
    AlignmentResponse,
    Finding,
    ReviewResponse,
    ReviewTarget,
    Revision,
    TextEdit,
)
from translate.tasks import MATCHING_VERSION, SavedLLMCalls
from translate.tasks.review_alignment import match_documents as _match_documents
from translate.tasks.review_chunks import (
    _chunks,
    _retry_groups,
    _target_bytes,
    _target_payload,
    _user_payload,
)


def _without_extraction_spaces(value: str) -> str:
    """日本語の文字間空白と抽出時の改行を除き、英単語の区切りは保持する。

    Args:
        value: 訳文またはその修正候補。

    Returns:
        CJK文字に接する空白と改行だけを除いた比較用本文。
    """
    cjk = r"[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff]"
    value = re.sub(r"\s+", " ", value)
    return re.sub(rf"(?<={cjk})\s+|\s+(?={cjk})", "", value).strip()


def _date_value(value: str) -> date | None:
    """日付だけの値を区切りの有無に依存しない暦日へ変換する。

    Args:
        value: 4桁年・2桁月・2桁日を持つ値。月日の間の区切りは省略可能。

    Returns:
        有効な暦日。日付以外の値や存在しない日付ではNone。
    """
    match = re.fullmatch(r"(\d{4})[-/.](\d{2})[-/.]?(\d{2})", "".join(value.split()))
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


class ReviewTask:
    """原文と訳文の対応付け・評価を、共有する規則とCall保存先で実行する。"""

    def __init__(
        self,
        config: Config,
        task_directory: Path,
        rules: str,
        glossary: str,
        *,
        contexts: dict[str, dict[str, dict[str, str]]] | None = None,
    ) -> None:
        """比較処理の依存関係と保存済み要求の管理を準備する。

        Args:
            config: LLM接続、応答件数および再試行の上限。
            task_directory: Callと評価結果の保存先。
            rules: 対応付けと品質評価の判断規則。
            glossary: 原文に関連する語を選ぶCSV用語集。
            contexts: 文書roleとTextUnit IDごとの照合用構造情報。
        """
        self.config = config
        self.task_directory = task_directory
        self.rules = rules
        self.calls = SavedLLMCalls("REVIEW", task_directory, rules, glossary)
        self.contexts = contexts or {}

    def run(
        self,
        targets: list[ReviewTarget],
        _processing_directory: Path,
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
            ReviewResult: 全Targetの指摘、修正候補および確認済みID。

        Raises:
            ValueError: `review model is required`と判定した場合。
        """

        if self.config.openai_review_model is None:
            raise ValueError("review model is required")
        self.task_directory.mkdir(parents=True, exist_ok=True)
        diagnostics_path = self.task_directory / "diagnostics.json"
        diagnostics: list[str] = []
        write_task_diagnostics(diagnostics_path, "REVIEW", diagnostics)
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
            output_tokens = min(self.config.review_output_tokens, 8192)
            input_tokens = (
                self.config.review_input_tokens
                + self.config.review_output_tokens
                - output_tokens
            )
            payload_budget = self.config.input_bytes(input_tokens) - overhead
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
            write_task_diagnostics(diagnostics_path, "REVIEW", diagnostics)
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
                if any(
                    re.search(
                        r"\bdate\b|日付",
                        self.contexts.get("translation", {})
                        .get(key, {})
                        .get("row_label", ""),
                        re.IGNORECASE,
                    )
                    for key in target.target_ids
                ):
                    source_date = _date_value(target.source)
                    if source_date is not None and source_date == _date_value(
                        "".join(span.text() for span in target.spans)
                    ):
                        item.reason = "日付の暦日は一致しており、区切り表記の差は不備ではありません。"
                        item.verdict = "correct"
                        item.edits = []
                        item.category = None
                        item.severity = None
                        continue
                translated = "".join(span.text() for span in target.spans)
                source_page_ref = re.fullmatch(
                    r"([IVXLCDM]+-\d)\s*(\d+)", target.source.strip()
                )
                translation_page_ref = re.fullmatch(
                    r"([IVXLCDM]+-\d)\s*(\d+)", translated.strip()
                )
                if (
                    source_page_ref is not None
                    and translation_page_ref is not None
                    and source_page_ref.groups() == translation_page_ref.groups()
                ):
                    item.reason = "原文と訳文のページ参照は同じであり、数字間の空白差は問題ありません。"
                    item.verdict = "correct"
                    item.edits = []
                    item.category = None
                    item.severity = None
                    continue
                same_text = target.source.strip() == translated.strip()
                table_cell = any(
                    self.contexts.get("translation", {}).get(key, {}).get("kind")
                    == "table_cell"
                    for key in target.target_ids
                )
                selected_spans = {span.id: span.text() for span in target.spans}
                dot_leader_only = bool(item.edits) and all(
                    edit.span_id in selected_spans
                    and re.sub(
                        r"\.{2,}",
                        "",
                        selected_spans[edit.span_id],
                    ).strip()
                    == re.sub(r"\.{2,}", "", edit.text).strip()
                    for edit in item.edits
                )
                mentions_dot_leader = (
                    "ドット" in item.reason or "dot" in item.reason.lower()
                )
                if (
                    same_text
                    and table_cell
                    and re.search(r"\.{2,}", target.source)
                    and dot_leader_only
                    and mentions_dot_leader
                ):
                    item.reason = "表内のドットリーダーはレイアウト表記であり、原文と訳文で一致しています。"
                    item.verdict = "correct"
                    item.edits = []
                    item.category = None
                    item.severity = None
                    continue
                if same_text and (
                    (
                        f"「{target.source.strip()}」" in item.reason
                        and any(
                            phrase in item.reason
                            for phrase in ("含まれていない", "含まれていません")
                        )
                    )
                    or any(
                        phrase in item.reason
                        for phrase in (
                            "そのまま保持すべき",
                            "そのまま保持することは許容",
                        )
                    )
                ):
                    item.reason = (
                        "原文と訳文は一致しており、指摘理由も変更不要としています。"
                    )
                    item.verdict = "correct"
                    item.edits = []
                    item.category = None
                    item.severity = None
                    continue
                if any(
                    edit.span_id not in selected_spans
                    or (span_owners or {}).get(edit.span_id) not in target.target_ids
                    for edit in item.edits
                ):
                    raise ValueError(
                        "Assessment references an unselected or unowned span"
                    )
                span_positions = {
                    span.id: index for index, span in enumerate(target.spans)
                }
                for edit in item.edits:
                    index = span_positions[edit.span_id]
                    previous = (
                        target.spans[index - 1].text().strip() if index > 0 else ""
                    )
                    following = (
                        target.spans[index + 1].text().strip()
                        if index + 1 < len(target.spans)
                        else ""
                    )
                    if (
                        len(previous) > 1 and edit.text.lstrip().startswith(previous)
                    ) or (
                        len(following) > 1 and edit.text.rstrip().endswith(following)
                    ):
                        raise ValueError(
                            "Assessment edit includes text from an adjacent translation span"
                        )
                if item.edits and all(
                    _without_extraction_spaces(selected_spans[edit.span_id])
                    == _without_extraction_spaces(edit.text)
                    for edit in item.edits
                ):
                    raise ValueError(
                        "The edits only change extraction whitespace or leave the translation unchanged. Use correct."
                    )

        try:
            call_id, response = self.calls.request(
                client,
                operation,
                round_number,
                [f"review:{key}" for key in target_ids],
                {
                    "targets": [
                        {
                            **_target_payload(target),
                            "context": [
                                {
                                    name: value
                                    for name, value in self.contexts["translation"][
                                        key
                                    ].items()
                                    if name != "position"
                                }
                                for key in target.target_ids
                                if key in self.contexts.get("translation", {})
                            ],
                        }
                        for target in targets
                    ],
                    "lineage": lineage,
                },
                "\n".join(target.source for target in targets),
                ReviewResponse,
                "Return assessments, one object for each input targets[].id, in input order. "
                "Each assessment contains target_id (the complete input targets[].id), reason (one brief sentence), "
                "verdict (correct or issue), and edits (span_id and replacement text). "
                "Each edits[].span_id must exactly match an input targets[].translation[].span_id. "
                "Edit text must replace only that span; do not copy text from adjacent spans. "
                "For an issue, also provide category and severity (info, warning or error); for correct use null for both. "
                "Compare the original source with all current translation[].text for that target. "
                "Use correct when the current translation needs no change; then edits must be empty. "
                "Use issue only for a concrete defect, and propose replacements for the affected spans. "
                "A correctly preserved technical identifier is correct, even though it is English. "
                "context describes the translation's structural role, not additional translation text. "
                "Ordinary English prose left untranslated is an issue. Explain the conclusion in Japanese.",
                validate,
            )
        except (
            LLMInputExceededError,
            LLMInvalidResponseError,
            LLMOutputExceededError,
        ):
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
                matching_version=MATCHING_VERSION,
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
        """Agentが選んだ原文と訳文の対応候補を取得する。"""
        return _match_documents(self.calls, units, client, round_number, self.contexts)
