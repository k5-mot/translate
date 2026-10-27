"""問題指摘と修正候補を生成するREVIEW Task。"""

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
    LLMInvalidResponseError,
    LLMOutputExceededError,
)
from translate.common.config import Config
from translate.models.artifacts import (
    LLMCallArtifact,
    LLMCallIndex,
    LLMTaskDiagnostics,
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
from translate.tasks import SavedLLMCalls
from translate.tasks.review_alignment import match_documents as _match_documents
from translate.tasks.review_chunks import (
    _chunks,
    _retry_groups,
    _target_bytes,
    _target_payload,
    _user_payload,
)


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
            ReviewResult: ReviewTargetをchunk化し、LLMの指摘と修正候補へ決定的なIDを付ける。

        Raises:
            ValueError: `review model is required`と判定した場合。
        """

        if self.config.openai_review_model is None:
            raise ValueError("review model is required")
        self.task_directory.mkdir(parents=True, exist_ok=True)
        diagnostics_path = self.task_directory / "diagnostics.json"
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
            output_tokens = min(self.config.review_output_tokens, 8192)
            input_tokens = (
                self.config.review_input_tokens
                + self.config.review_output_tokens
                - output_tokens
            )
            payload_budget = input_tokens - overhead
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
                "Each edits[].span_id must exactly match an input targets[].spans[].span_id. "
                "For an issue, also provide category and severity (info, warning or error); for correct use null for both. "
                "Compare the original source with all current spans[].text for that target. "
                "Use correct when the current translation needs no change; then edits must be empty. "
                "Use issue only for a concrete defect, and propose replacements for the affected spans. "
                "A correctly preserved technical identifier is correct, even though it is English. "
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
        return _match_documents(self.calls, units, client, round_number)


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
