"""原文と訳文をAgentで対応付け、指摘と修正提案を一覧化する。"""

import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from translate.adapters.artifact_store import (
    ArtifactStore,
    ProcessingLock,
    describe_artifact,
    load_model,
    write_model,
)
from translate.adapters.llm import (
    LLMClient,
    LLMInputExceededError,
    LLMInvalidResponseError,
    LLMOutputExceededError,
)
from translate.common.config import Config, validate_config
from translate.common.logger import processing_logging
from translate.models.artifacts import (
    LLMCallIndex,
    ReviewRecord,
    ReviewResult,
    TaskName,
)
from translate.models.document import Document
from translate.models.review import AgentAction, AlignmentGroup, ReviewTarget
from translate.pipeline import (
    InputError,
    PipelineRun,
    agent_units,
    choose_action,
    completed_agent_calls,
    observe_documents,
    pdf_inputs,
    resolve_processing_id,
)

ReviewTask = import_module("translate.tasks.41_review").ReviewTask


class ReviewOutcome(BaseModel):
    """UIへ返すReview IDと結果JSON。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)
    review_id: str
    processing_directory: Path
    result: Path


class ReviewPipeline:
    """Reviewの設定と実行記録を保持し、入力検証から成果物公開まで進める。"""

    def __init__(self, config: Config, outputs: Path | None = None) -> None:
        """外部接続の設定と成果物の基準ディレクトリを受け取る。

        Args:
            config: 操作で使用する接続と処理上限。
            outputs: 出力先。省略時は実行時の作業ディレクトリ内のoutputs。
        """
        self.config = config
        self.outputs = outputs

    def run(
        self,
        source: Path,
        translation: Path,
        *,
        processing_id: str | None = None,
        resume_id: str | None = None,
    ) -> ReviewOutcome:
        """二つのPDFを解析し、Agentが確定した一覧だけを公開する。

        Args:
            source: 英語原文PDF。
            translation: 日本語訳文PDF。
            processing_id: UIが発行した新規ID。
            resume_id: 再開するID。

        Returns:
            処理IDと指摘・修正提案のJSON。

        Raises:
            InputError: 入力・IDまたは再開条件が不正な場合。
            Exception: 前処理またはAgent操作が失敗した場合。
        """
        sources = {"source": source.resolve(), "translation": translation.resolve()}
        inputs = pdf_inputs(sources)
        validate_config(self.config, "review")
        identifier = resolve_processing_id(processing_id, resume_id)
        self.root = (
            (self.outputs or Path.cwd() / "outputs").resolve()
            / translation.stem
            / identifier
        )
        self.record_path = self.root / "review.json"
        with ProcessingLock(self.root):
            if self.record_path.is_file():
                self.record = load_model(self.record_path, ReviewRecord)
                if (
                    not resume_id
                    or self.record.review_id != identifier
                    or self.record.source != inputs["source"]
                    or self.record.translation != inputs["translation"]
                ):
                    raise InputError("Review ID already exists or resume inputs differ")
            else:
                if resume_id:
                    raise InputError("Review to resume does not exist")
                now = datetime.now(UTC)
                self.record = ReviewRecord(
                    review_id=identifier,
                    status="processing",
                    source=inputs["source"],
                    translation=inputs["translation"],
                    created_at=now,
                    updated_at=now,
                )
                write_model(self.record_path, self.record)
            with processing_logging(self.root, self.config.log_level):
                try:
                    self.execution = PipelineRun(
                        ArtifactStore(self.record, self.record_path), self.config
                    )
                    documents, _ = self.execution.prepare_documents(sources)
                    directory = self.root / "review" / "review"
                    self.execution.perform_task(
                        TaskName.REVIEW,
                        documents,
                        [
                            (
                                directory,
                                ReviewAgent(
                                    documents, directory, self.root, self.config
                                ).run,
                            )
                        ],
                    )
                    self.record.status, self.record.error = "succeeded", None
                    result_path = directory / "review.json"
                    self.record.outputs = [describe_artifact(self.root, result_path)]
                    self.record.updated_at = datetime.now(UTC)
                    write_model(self.record_path, self.record)
                except KeyboardInterrupt:
                    ArtifactStore(self.record, self.record_path).cancel_processing()
                    raise
        return ReviewOutcome(
            review_id=identifier, processing_directory=self.root, result=result_path
        )


class ReviewAgent:
    """文書の確認状況を保持し、LLMが選んだ操作と終了条件を管理する。"""

    def __init__(
        self,
        documents: dict[str, Document],
        directory: Path,
        root: Path,
        config: Config,
    ) -> None:
        """比較対象と処理の依存関係を受け取る。

        Args:
            documents: 役割名で区別した比較対象文書。
            directory: 操作の記録と最終一覧の保存先。
            root: 処理IDの保存先。
            config: LLMの接続と処理予算。
        """
        self.units = agent_units(documents)
        self.directory = directory
        self.config = config
        self.root = root

    def run(self) -> ReviewResult:
        """文脈取得・対応付け・評価・再確認を選択し、全対象の確認後に一覧を保存する。

        Returns:
            対応関係、全指摘、修正提案および確認範囲。

        Raises:
            InputError: Agentの参照、操作、終了要求が不正な場合。
            TimeoutError: 判断回数またはTask期限を超えた場合。
            LLMError: 外部要求が失敗した場合。
        """
        self.client = LLMClient(self.config)
        deadline = time.monotonic() + self.config.llm_task_deadline_seconds
        self.client.deadline = deadline
        try:
            templates = Path(__file__).parents[1] / "templates"
            rules = (templates / "review-rules.md").read_text(encoding="utf-8")
            glossary = (templates / "glossary.csv").read_text(encoding="utf-8")
            self.review = ReviewTask(self.config, self.directory, rules, glossary)
            self.result = ReviewResult()
            self.conflicts: set[str] = set()
            self.call_ids: list[str] = []
            # 未対応群を置換しても、評価が参照するgroup IDを再利用しない。
            self.group_number = 0

            restored = completed_agent_calls(self.directory)
            replayed: set[tuple[int, str]] = set()
            for call in restored:
                key = (call.round, call.operation)
                if key in replayed:
                    continue
                replayed.add(key)
                action = AgentAction.model_validate({"operation": call.operation})
                for current in restored:
                    if (current.round, current.operation) != key:
                        continue
                    for reference in current.target_ids:
                        role, _, identifier = reference.partition(":")
                        if call.operation == "match":
                            action.references.setdefault(role, []).append(identifier)
                        else:
                            action.target_ids.append(identifier.split("/part-", 1)[0])
                action.target_ids = list(dict.fromkeys(action.target_ids))
                self._execute(action, call.round)

            round_number = max((call.round for call in restored), default=-1) + 1
            idle_steps = 0
            observation: object = {"restored_operations": len(replayed)}
            group_steps: dict[str, int] = {}
            while True:
                assigned = {
                    role: {
                        key
                        for group in self.result.groups
                        for key in getattr(group, f"{role}_ids")
                    }
                    for role in self.units
                }
                pending = {
                    role: [key for key in values if key not in assigned[role]]
                    for role, values in self.units.items()
                }
                unmatched = {
                    role: [
                        key
                        for group in self.result.groups
                        if group.kind != "matched"
                        for key in getattr(group, f"{role}_ids")
                    ]
                    for role in self.units
                }
                unchecked = [
                    target.id
                    for target in self.result.targets
                    if target.id not in self.result.reviewed_target_ids
                ]
                state: dict[str, object] = {
                    "roles": list(self.units),
                    "pending_counts": {role: len(ids) for role, ids in pending.items()},
                    "pending_ids": {role: ids[:8] for role, ids in pending.items()},
                    "unmatched_counts": {
                        role: len(ids) for role, ids in unmatched.items()
                    },
                    "unmatched_ids": {role: ids[:8] for role, ids in unmatched.items()},
                    "unchecked_count": len(unchecked),
                    "unchecked_targets": unchecked[:32],
                    "reviewed_targets": self.result.reviewed_target_ids[-8:],
                    "conflicts": sorted(self.conflicts),
                }
                if idle_steps >= 12 or time.monotonic() >= deadline:
                    raise TimeoutError("Review Agent reached its step or time limit")
                try:
                    action = choose_action(
                        self.client,
                        "Review English source against Japanese translation and propose edits.",
                        state,
                        observation,
                        self.units,
                    )
                except LLMInputExceededError:
                    observation = {
                        "error": "Previous result exceeded the action input budget. No action was executed; choose from the current state."
                    }
                    idle_steps += 1
                    continue
                except LLMInvalidResponseError:
                    observation = {
                        "error": "Invalid action response. No action was executed. Choose a valid operation from the current state."
                    }
                    idle_steps += 1
                    continue
                if action.operation == "finish":
                    if any(pending.values()) or unchecked or self.conflicts:
                        raise InputError(
                            "Review cannot finish with unconfirmed or conflicting targets"
                        )
                    break
                progress_before = (
                    sum(map(len, assigned.values()))
                    + len(self.result.targets)
                    + len(self.result.reviewed_target_ids)
                )
                # 概要・検索は対象群を固定しないため、連続する無進捗回数で制限する。
                if action.references or action.target_ids:
                    group_key = repr((action.references, action.target_ids))
                    group_steps[group_key] = group_steps.get(group_key, 0) + 1
                    if group_steps[group_key] > 12:
                        raise TimeoutError(
                            "Review target group exceeded 12 Agent steps"
                        )
                if action.operation in {"overview", "read", "search"}:
                    visible = (
                        {
                            role: {
                                key: self.units[role][key]
                                for key in ids + unmatched[role]
                            }
                            for role, ids in pending.items()
                        }
                        if action.operation == "overview"
                        else self.units
                    )
                    observation = observe_documents(
                        action, visible, max(512, self.config.review_input_tokens // 3)
                    )
                else:
                    try:
                        observation = self._execute(action, round_number)
                    except (LLMInputExceededError, LLMOutputExceededError):
                        observation = {
                            "error": "Selected scope exceeds the budget. Select fewer units or targets."
                        }
                    except LLMInvalidResponseError:
                        observation = {
                            "error": "The operation returned an invalid response after its validation retry. "
                            "No result was accepted. Inspect context and select a smaller or different group."
                        }
                    round_number += 1
                observation = {"action": action.model_dump(), "result": observation}
                progress_after = (
                    sum(
                        len(group.source_ids) + len(group.translation_ids)
                        for group in self.result.groups
                    )
                    + len(self.result.targets)
                    + len(self.result.reviewed_target_ids)
                )
                idle_steps = idle_steps + 1 if progress_after <= progress_before else 0
            write_model(
                self.directory / "call-index.json",
                LLMCallIndex(
                    task="REVIEW", call_ids=list(dict.fromkeys(self.call_ids))
                ),
            )
            write_model(self.directory / "review.json", self.result)
            return self.result
        finally:
            self.client.client.close()

    def _execute(self, action: AgentAction, round_number: int) -> dict[str, object]:
        """一つの許可済み操作を実行し、検証した結果だけを集約する。

        Args:
            action: Agentが選択した対応付け・評価・再確認。
            round_number: 保存Callの連番。

        Returns:
            次の判断へ渡す操作結果の概要。

        Raises:
            InputError: 対象や結果の参照が不正な場合。
        """
        if action.operation == "match":
            if set(action.references) - set(self.units):
                raise InputError("Unknown Review role")
            chosen = {role: action.references.get(role, []) for role in self.units}
            if not any(chosen.values()) or sum(map(len, chosen.values())) > 32:
                raise InputError("Review match requires 1 to 32 selected units")
            for role, ids in chosen.items():
                if len(ids) != len(set(ids)) or not set(ids).issubset(self.units[role]):
                    raise InputError("Invalid Review correspondence reference")
            for role, ids in chosen.items():
                assigned = {
                    key
                    for group in self.result.groups
                    if group.kind == "matched"
                    for key in getattr(group, f"{role}_ids")
                }
                if assigned.intersection(ids):
                    raise InputError(
                        "Match requires units without a confirmed correspondence"
                    )
            call_id, response = self.review.match_documents(
                {
                    role: [self.units[role][key] for key in ids]
                    for role, ids in chosen.items()
                },
                self.client,
                round_number,
            )
            # 新しい結果の検証成功後に、再探索したIDだけを以前の未対応群から除く。
            for group in self.result.groups:
                if group.kind != "matched":
                    group.source_ids = [
                        key for key in group.source_ids if key not in chosen["source"]
                    ]
                    group.translation_ids = [
                        key
                        for key in group.translation_ids
                        if key not in chosen["translation"]
                    ]
            self.result.groups = [
                group
                for group in self.result.groups
                if group.source_ids or group.translation_ids
            ]
            first_new_group = len(self.result.groups)
            for candidate in response.groups:
                self.group_number += 1
                group = AlignmentGroup(
                    id=f"alignment-{self.group_number:06d}",
                    **candidate.model_dump(),
                )
                self.result.groups.append(group)
                if group.kind == "matched":
                    translated = [
                        self.units["translation"][key] for key in group.translation_ids
                    ]
                    self.result.targets.append(
                        ReviewTarget(
                            id=f"review/{group.id}",
                            source="\n".join(
                                self.units["source"][key].text("source")
                                for key in group.source_ids
                            ),
                            translation="\n".join(
                                unit.text("source") for unit in translated
                            ),
                            target_ids=group.translation_ids,
                            spans=[span for unit in translated for span in unit.spans],
                        )
                    )
            self.call_ids.append(call_id)
            return {
                "groups": [
                    group.model_dump() for group in self.result.groups[first_new_group:]
                ]
            }
        if action.operation not in {"evaluate", "recheck"}:
            raise InputError("Unsupported Review Agent operation")
        selected = [
            target for target in self.result.targets if target.id in action.target_ids
        ]
        if (
            not selected
            or len(action.target_ids) > 32
            or len(selected) != len(action.target_ids)
        ):
            raise InputError("Invalid Review evaluation target")
        if action.operation == "evaluate" and set(action.target_ids).intersection(
            self.result.reviewed_target_ids
        ):
            raise InputError("Use recheck to revisit a completed target")
        evaluated = self.review.run(
            selected,
            self.root,
            operation=action.operation,
            round_number=round_number,
            publish=False,
            client=self.client,
            span_owners={
                span.id: key
                for target in selected
                for key in target.target_ids
                for span in self.units["translation"][key].spans
            },
        )
        target_units = {key for target in selected for key in target.target_ids}
        self.result.findings = [
            finding
            for finding in self.result.findings
            if not target_units.intersection(finding.target_ids)
        ] + evaluated.findings
        self.result.revisions = [
            revision
            for revision in self.result.revisions
            if revision.target_id not in target_units
        ] + evaluated.revisions
        self.result.reviewed_target_ids = list(
            dict.fromkeys([*self.result.reviewed_target_ids, *action.target_ids])
        )
        self.conflicts.difference_update(action.target_ids)
        edits: dict[str, set[str]] = {}
        for revision in evaluated.revisions:
            for edit in revision.edits:
                edits.setdefault(edit.span_id, set()).add(edit.text)
        if any(len(texts) > 1 for texts in edits.values()):
            self.conflicts.update(action.target_ids)
        self.call_ids.extend(
            call.call_id
            for call in completed_agent_calls(self.directory)
            if call.round == round_number and call.operation == action.operation
        )
        return {
            "findings": [item.model_dump() for item in evaluated.findings[:5]],
            "revisions": [item.model_dump() for item in evaluated.revisions[:5]],
            "total_findings": len(evaluated.findings),
            "total_revisions": len(evaluated.revisions),
            "conflicts": sorted(self.conflicts),
        }
