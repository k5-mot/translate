"""原文と訳文をAgentで対応付け、指摘と修正提案を一覧化する。"""

import logging
import time
from datetime import UTC, datetime
from difflib import SequenceMatcher
from importlib import import_module
from pathlib import Path
from typing import cast

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
    LLMCallArtifact,
    LLMCallIndex,
    ReviewRecord,
    ReviewResult,
    TaskName,
)
from translate.models.document import Document
from translate.models.review import AgentAction, AlignmentGroup, Finding, ReviewTarget
from translate.pipeline import (
    ACTION_FAILURE_LIMIT,
    InputError,
    PipelineRun,
    agent_units,
    choose_action,
    completed_agent_calls,
    observe_documents,
    pdf_inputs,
    resolve_processing_id,
)
from translate.pipeline.matching import MatchingCandidates
from translate.tasks import MATCHING_VERSION

ReviewTask = import_module("translate.tasks.41_review").ReviewTask
logger = logging.getLogger(__name__)
_MATCH_NO_PROGRESS_LIMIT = 3
_DUPLICATE_FRONT_PAGE_MIN_CHARS = 100
_DUPLICATE_FRONT_PAGE_MIN_SIMILARITY = 0.85


def _copied_translation_front_page_ids(
    source: Document, translation: Document
) -> set[str]:
    """訳文の先頭に複製された英語原文ページがあれば、そのTextUnit IDを返す。

    Args:
        source: 英語原文。
        translation: Review対象の訳文。

    Returns:
        set[str]: OCR差の比較基準に原文LOAD本文を使う訳文unitのID。
    """
    if not source.pages or not translation.pages:
        return set()
    source_units = [
        unit
        for block in source.pages[0].blocks
        for unit in ([block.content] if block.content else [])
        + [cell.content for cell in block.cells]
    ]
    translation_units = [
        unit
        for block in translation.pages[0].blocks
        for unit in ([block.content] if block.content else [])
        + [cell.content for cell in block.cells]
    ]
    source_text = " ".join(unit.text("source") for unit in source_units)
    translation_text = " ".join(unit.text("source") for unit in translation_units)
    normalized_source = " ".join(source_text.casefold().split())
    normalized_translation = " ".join(translation_text.casefold().split())
    if min(len(normalized_source), len(normalized_translation)) < (
        _DUPLICATE_FRONT_PAGE_MIN_CHARS
    ):
        return set()
    japanese = sum(
        "\u3040" <= character <= "\u30ff" or "\u4e00" <= character <= "\u9fff"
        for character in normalized_translation
    )
    if japanese / len(normalized_translation) > 0.01:
        return set()
    # shortcut: checks only page 1; extend to later page pairs if copied originals can appear elsewhere.
    if (
        SequenceMatcher(None, normalized_source, normalized_translation).ratio()
        < _DUPLICATE_FRONT_PAGE_MIN_SIMILARITY
    ):
        return set()
    return {unit.id for unit in translation_units}


def _fallback_action(state: dict[str, object]) -> AgentAction:
    """未解決の対象から、LLMの判断なしで次に行うReview操作を決める。

    Args:
        state: Agentへ渡す確認状況。

    Returns:
        AgentAction: 競合の再確認、未評価の評価、未対応の照合、終了の優先順の操作。
    """
    conflicts = cast("list[str]", state["conflicts"])
    if conflicts:
        return AgentAction(operation="recheck", target_ids=conflicts[:8])
    unchecked = cast("list[str]", state["unchecked_targets"])
    if unchecked:
        return AgentAction(operation="evaluate", target_ids=unchecked[:8])
    pending = cast("dict[str, list[str]]", state["pending_ids"])
    limit = max(1, cast("int", state["max_reference_ids"]) // 2)
    references = {role: ids[:limit] for role, ids in pending.items() if ids}
    if references:
        return AgentAction(operation="match", references=references)
    unmatched = cast("dict[str, list[str]]", state["unmatched_ids"])
    if unmatched["source"] and unmatched["translation"]:
        return AgentAction(
            operation="match",
            references={role: ids[:limit] for role, ids in unmatched.items() if ids},
        )
    return AgentAction(operation="finish")


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
        self.record_path = self.root / "state-review.json"
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
            with processing_logging(self.root, self.config.log_level, "review.log"):
                try:
                    self.execution = PipelineRun(
                        ArtifactStore(self.record, self.record_path), self.config
                    )
                    documents, _ = self.execution.prepare_documents(sources)
                    directory = self.root / "tasks" / "41-review"
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
        self.documents = documents
        self.copied_front_page_ids = _copied_translation_front_page_ids(
            documents["source"], documents["translation"]
        )
        self.contexts = {
            role: document.unit_contexts() for role, document in documents.items()
        }
        self.candidates = MatchingCandidates(
            self.units, self.contexts, directory, config
        )
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
            # 対応群ごとに品質確認し、別の対象の不備を混入させない。
            self.review = ReviewTask(
                self.config.model_copy(update={"review_max_targets": 1}),
                self.directory,
                rules,
                glossary,
                contexts=self.contexts,
            )
            self.result = ReviewResult()
            self.conflicts: set[str] = set()
            self.call_ids: list[str] = []
            self.match_scopes: set[tuple[tuple[str, ...], ...]] = set()
            self.match_failures: dict[tuple[str, str], int] = {}
            self.exhausted_match_ids: set[tuple[str, str]] = set()
            # 未対応群を置換しても、評価が参照するgroup IDを再利用しない。
            self.group_number = 0

            restored = completed_agent_calls(
                self.directory, matching_version=MATCHING_VERSION
            )
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
                try:
                    result = self._execute(action, call.round, replay=True)
                except InputError as error:
                    logger.warning(
                        "Skipping stale Review operation round=%s operation=%s: %s",
                        call.round,
                        call.operation,
                        error,
                    )
                    continue
                if call.operation == "match":
                    self._record_match_failures(action, result)
            self._restore_failed_match_attempts()

            round_number = max((call.round for call in restored), default=-1) + 1
            idle_steps = 0
            observation: object = {"restored_operations": len(replayed)}
            group_steps: dict[str, int] = {}
            max_reference_ids = 32
            action_failures = 0
            deterministic = False
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
                        if (role, key) not in self.exhausted_match_ids
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
                    "max_reference_ids": max_reference_ids,
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
                if idle_steps >= 12 and not (
                    any(pending.values()) or unchecked or self.conflicts
                ):
                    if unmatched["source"] and unmatched["translation"]:
                        action_failures = ACTION_FAILURE_LIMIT
                        idle_steps = 0
                        observation = {
                            "error": "Unmatched units remain on both sides. Retry correspondence before finishing."
                        }
                        continue
                    break
                if (idle_steps >= 12 and deterministic) or time.monotonic() >= deadline:
                    raise TimeoutError("Review Agent reached its step or time limit")
                if idle_steps >= 12:
                    # LLMの選択が進まなくても、状態から決まる残作業を最後まで実行する。
                    logger.warning("Using deterministic Agent actions after idle steps")
                    deterministic = True
                    idle_steps = 0
                try:
                    action = (
                        _fallback_action(state)
                        if deterministic or action_failures >= ACTION_FAILURE_LIMIT
                        else choose_action(
                            self.client,
                            "Review English source against Japanese translation and propose edits.",
                            state,
                            observation,
                            self.units,
                        )
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
                    action_failures += 1
                    if action_failures >= ACTION_FAILURE_LIMIT:
                        # 判断を繰り返し得られない間も、状態から決まる次の作業は止めない。
                        logger.warning("Using deterministic Agent action")
                        idle_steps = 0
                    continue
                if action.operation == "finish":
                    if any(pending.values()) or unchecked or self.conflicts:
                        raise InputError(
                            "Review cannot finish with unconfirmed or conflicting targets"
                        )
                    if unmatched["source"] and unmatched["translation"]:
                        action_failures = ACTION_FAILURE_LIMIT
                        idle_steps = 0
                        observation = {
                            "error": "Unmatched units remain on both sides. Retry correspondence before finishing."
                        }
                        continue
                    break
                if action.operation == "match":
                    exhausted = {
                        (role, identifier)
                        for role, identifiers in action.references.items()
                        for identifier in identifiers
                        if (role, identifier) in self.exhausted_match_ids
                    }
                    if exhausted:
                        action.references = {
                            role: [
                                identifier
                                for identifier in identifiers
                                if (role, identifier) not in exhausted
                            ]
                            for role, identifiers in action.references.items()
                        }
                        action.references = {
                            role: identifiers
                            for role, identifiers in action.references.items()
                            if identifiers
                        }
                        observation = {
                            "error": "These units already had three unsuccessful correspondence attempts. Choose other unmatched units."
                        }
                        action_failures += 1
                        if action_failures >= ACTION_FAILURE_LIMIT:
                            logger.warning("Using deterministic Agent action")
                        continue
                progress_before = (
                    sum(map(len, assigned.values()))
                    + len(self.result.targets)
                    + len(self.result.reviewed_target_ids)
                )
                # 同じ照合・評価範囲が3回進まなければ、未確認として結果へ残す。
                stalled_action = False
                action_group_key = None
                if action.operation in {"match", "evaluate", "recheck"}:
                    action_group_key = repr(
                        (action.operation, action.references, action.target_ids)
                    )
                    previous_no_progress = group_steps.get(action_group_key, 0)
                    stalled_action = previous_no_progress >= 3
                    if previous_no_progress >= 1 and action.operation == "match":
                        selected_count = sum(map(len, action.references.values()))
                        if selected_count > 2:
                            max_reference_ids = max(
                                2,
                                min(max_reference_ids - 1, selected_count // 2),
                            )
                if stalled_action:
                    if action.operation == "match":
                        selected_ids = {
                            role: set(action.references.get(role, []))
                            for role in self.units
                        }
                        assigned_ids = {
                            role: {
                                identifier
                                for group in self.result.groups
                                for identifier in getattr(group, f"{role}_ids")
                            }
                            for role in self.units
                        }
                        for role, identifiers in selected_ids.items():
                            for identifier in sorted(identifiers - assigned_ids[role]):
                                self._add_unverified(
                                    role,
                                    identifier,
                                    "同じ範囲の照合が進まなかったため、対応関係は未確認です。",
                                )
                        if not any(
                            identifiers - assigned_ids[role]
                            for role, identifiers in selected_ids.items()
                        ):
                            for role, identifiers in pending.items():
                                for identifier in identifiers:
                                    self._add_unverified(
                                        role,
                                        identifier,
                                        "Agentが同じ照合を繰り返したため、対応関係は未確認です。",
                                    )
                        target_ids = [
                            target.id
                            for group in self.result.groups
                            if group.kind == "matched"
                            and (
                                selected_ids["source"].intersection(group.source_ids)
                                or selected_ids["translation"].intersection(
                                    group.translation_ids
                                )
                            )
                            for target in self.result.targets
                            if target.id == f"review/{group.id}"
                        ]
                    else:
                        target_ids = list(action.target_ids)
                    targets_by_id = {
                        target.id: target for target in self.result.targets
                    }
                    target_ids = [
                        target_id
                        for target_id in target_ids
                        if target_id in targets_by_id
                    ] or list(unchecked)
                    unresolved_targets = [
                        target_id
                        for target_id in target_ids
                        if target_id not in self.result.reviewed_target_ids
                    ]
                    for target_id in unresolved_targets:
                        target = targets_by_id[target_id]
                        self.result.findings.append(
                            Finding(
                                id=f"review/unverified/{target_id}",
                                category="未確認",
                                severity="warning",
                                target_ids=target.target_ids,
                                message="同じ対象の再試行で進捗がなかったため、内容を確認できませんでした。",
                            )
                        )
                    self.result.reviewed_target_ids = list(
                        dict.fromkeys(
                            [*self.result.reviewed_target_ids, *unresolved_targets]
                        )
                    )
                    observation = {
                        "error": "Repeated action made no progress. Affected targets were recorded as unverified; continue with remaining work."
                    }
                elif action.operation in {"overview", "read", "search"}:
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
                        action,
                        visible,
                        max(
                            512,
                            self.config.input_bytes(self.config.review_input_tokens)
                            // 3,
                        ),
                        contexts=self.contexts,
                    )
                else:
                    try:
                        if action.operation == "match":
                            available = {
                                role: set(values)
                                - {
                                    key
                                    for group in self.result.groups
                                    if group.kind == "matched"
                                    for key in getattr(group, f"{role}_ids")
                                }
                                - {
                                    identifier
                                    for unit_role, identifier in self.exhausted_match_ids
                                    if unit_role == role
                                }
                                for role, values in self.units.items()
                            }
                            action.references = self.candidates.expand(
                                action.references, available, max_reference_ids
                            )
                        observation = self._execute(action, round_number)
                        if action.operation == "match":
                            self._record_match_failures(action, observation)
                    except (LLMInputExceededError, LLMOutputExceededError):
                        if action.operation == "match":
                            selected = sum(map(len, action.references.values()))
                            scope = tuple(
                                tuple(sorted(action.references.get(role, [])))
                                for role in self.units
                            )
                            if selected > 2:
                                max_reference_ids = max(
                                    2, min(max_reference_ids - 1, selected // 2)
                                )
                                message = (
                                    "Match scope exceeded the budget. Select at most "
                                    f"{max_reference_ids} document IDs."
                                )
                            else:
                                self.match_scopes.add(scope)
                                for role, ids in action.references.items():
                                    for identifier in ids:
                                        self._add_unverified(
                                            role,
                                            identifier,
                                            "入力上限により照合できず、対応関係は未確認です。",
                                        )
                                message = (
                                    "Minimum match scope exceeded the budget. "
                                    "Selected units were recorded as unverified; continue with other units."
                                )
                            observation = {"error": message}
                        else:
                            observation = {
                                "error": "Selected scope exceeds the budget. Select fewer units or targets."
                            }
                    except InputError as error:
                        observation = {
                            "error": f"{error}. No action was executed; choose valid references from the current state."
                        }
                    except LLMInvalidResponseError:
                        if action.operation == "match":
                            self._record_failed_match_attempt(action)
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
                if progress_after > progress_before:
                    action_failures = 0
                if action_group_key is not None:
                    if progress_after <= progress_before:
                        group_steps[action_group_key] = (
                            group_steps.get(action_group_key, 0) + 1
                        )
                    else:
                        group_steps.pop(action_group_key, None)
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

    def _add_unverified(self, role: str, identifier: str, reason: str) -> None:
        """照合できなかった要素を片側だけの未確認対応として結果へ加える。

        Args:
            role: `source`または`translation`。
            identifier: 対象のTextUnit ID。
            reason: 未確認となった理由。
        """
        self.group_number += 1
        is_source = role == "source"
        self.result.groups.append(
            AlignmentGroup(
                id=f"alignment-{self.group_number:06d}",
                kind="source_only" if is_source else "translation_only",
                source_ids=[identifier] if is_source else [],
                translation_ids=[] if is_source else [identifier],
                reason=reason,
            )
        )

    def _record_match_failures(
        self, action: AgentAction, observation: dict[str, object]
    ) -> None:
        """未対応のまま三回照合したTextUnitを、再試行対象から外す。

        Args:
            action: 候補追加後に実行した照合。
            observation: 対応付けで返された新しいgroup。
        """
        groups = cast("list[dict[str, object]]", observation["groups"])
        matched = {
            (role, identifier)
            for group in groups
            if group["kind"] == "matched"
            for role in self.units
            for identifier in cast("list[str]", group[f"{role}_ids"])
        }
        for role, identifiers in action.references.items():
            for identifier in identifiers:
                key = (role, identifier)
                if key in matched:
                    self.match_failures.pop(key, None)
                    self.exhausted_match_ids.discard(key)
                    continue
                self._increment_match_failure(role, identifier)

    def _record_failed_match_attempt(self, action: AgentAction) -> None:
        """Record a rejected match request and leave exhausted IDs unverified."""
        matched = {
            (role, identifier)
            for group in self.result.groups
            if group.kind == "matched"
            for role in self.units
            for identifier in getattr(group, f"{role}_ids")
        }
        assigned = {
            (role, identifier)
            for group in self.result.groups
            for role in self.units
            for identifier in getattr(group, f"{role}_ids")
        }
        for role, identifiers in action.references.items():
            for identifier in identifiers:
                if (role, identifier) in matched:
                    continue
                self._increment_match_failure(role, identifier)
                if (role, identifier) in self.exhausted_match_ids and (
                    role,
                    identifier,
                ) not in assigned:
                    self._add_unverified(
                        role,
                        identifier,
                        "同じunitの照合が3回失敗したため、対応関係は未確認です。",
                    )

    def _increment_match_failure(self, role: str, identifier: str) -> None:
        """同じunitの照合失敗数を加算し、上限到達時に再試行対象から外す。"""
        key = (role, identifier)
        failures = self.match_failures.get(key, 0) + 1
        self.match_failures[key] = failures
        if failures >= _MATCH_NO_PROGRESS_LIMIT:
            self.exhausted_match_ids.add(key)

    def _restore_failed_match_attempts(self) -> None:
        """Restore failed match attempts that completed calls do not replay."""
        failures: dict[int, dict[str, set[str]]] = {}
        for path in (self.directory / "calls").glob("*/call.json"):
            try:
                call = load_model(path, LLMCallArtifact)
            except (OSError, ValueError):
                continue
            if (
                call.task != "REVIEW"
                or call.operation != "match"
                or call.matching_version != MATCHING_VERSION
            ):
                continue
            if call.status != "failed":
                continue
            by_role = failures.setdefault(call.round, {})
            for reference in call.target_ids:
                role, _, identifier = reference.partition(":")
                if role in self.units:
                    by_role.setdefault(role, set()).add(identifier)
        for round_failures in failures.values():
            self._record_failed_match_attempt(
                AgentAction(
                    operation="match",
                    references={
                        role: sorted(identifiers)
                        for role, identifiers in round_failures.items()
                    },
                )
            )

    def _execute(
        self, action: AgentAction, round_number: int, *, replay: bool = False
    ) -> dict[str, object]:
        """一つの許可済み操作を実行し、検証した結果だけを集約する。

        Args:
            action: Agentが選択した対応付け・評価・再確認。
            round_number: 保存Callの連番。
            replay: 保存済みの操作を復元する場合。過去の同一範囲の再照合を許容する。

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
            scope = tuple(tuple(sorted(chosen[role])) for role in self.units)
            if scope in self.match_scopes and not replay:
                unmatched = {
                    (role, identifier)
                    for group in self.result.groups
                    if group.kind != "matched"
                    for role in self.units
                    for identifier in getattr(group, f"{role}_ids")
                }
                if not all(
                    (role, identifier) in unmatched
                    for role, identifiers in chosen.items()
                    for identifier in identifiers
                ):
                    raise InputError("Review match scope was already checked")
            call_id, response = self.review.match_documents(
                {
                    role: [self.units[role][key] for key in ids]
                    for role, ids in chosen.items()
                },
                self.client,
                round_number,
            )
            self.match_scopes.add(scope)
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
                    copied_page = set(group.translation_ids).issubset(
                        self.copied_front_page_ids
                    )
                    translated = [
                        self.units["translation"][key] for key in group.translation_ids
                    ]
                    source_text = "\n".join(
                        self.units["source"][key].text("source")
                        for key in group.source_ids
                    )
                    # A copied source page is already represented by the source PDF;
                    # use it as the text baseline to avoid findings from OCR drift.
                    self.result.targets.append(
                        ReviewTarget(
                            id=f"review/{group.id}",
                            source=source_text,
                            translation=source_text
                            if copied_page
                            else "\n".join(unit.text("source") for unit in translated),
                            target_ids=group.translation_ids,
                            spans=[]
                            if copied_page
                            else [span for unit in translated for span in unit.spans],
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
            dict.fromkeys(
                [*self.result.reviewed_target_ids, *(target.id for target in selected)]
            )
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
            for call in completed_agent_calls(
                self.directory, matching_version=MATCHING_VERSION
            )
            if call.round == round_number and call.operation == action.operation
        )
        return {
            "findings": [item.model_dump() for item in evaluated.findings[:5]],
            "revisions": [item.model_dump() for item in evaluated.revisions[:5]],
            "total_findings": len(evaluated.findings),
            "total_revisions": len(evaluated.revisions),
            "conflicts": sorted(self.conflicts),
        }
