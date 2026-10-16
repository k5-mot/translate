"""英文二版と旧訳をAgentで比較し、変更箇所と修正提案を公開する。"""

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
from translate.models.artifacts import LLMCallIndex, TaskName
from translate.models.document import Document
from translate.models.review import AgentAction
from translate.models.upgrade import (
    DiffChange,
    UpgradePlan,
    UpgradeRecord,
    VersionChange,
)
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

DiffTask = import_module("translate.tasks.21_diff").DiffTask


class UpgradeOutcome(BaseModel):
    """UIへ返すUpgrade IDと変更一覧JSON。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)
    upgrade_id: str
    processing_directory: Path
    plan: Path


class UpgradePipeline:
    """Upgradeの設定と実行記録を保持し、入力検証から成果物公開まで進める。"""

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
        source_v1: Path,
        source_v2: Path,
        translation_v1: Path,
        *,
        processing_id: str | None = None,
        resume_id: str | None = None,
    ) -> UpgradeOutcome:
        """三つのPDFを比較し、文書へ適用せず変更と提案の一覧を公開する。

        Args:
            source_v1: 英文旧版PDF。
            source_v2: 英文新版PDF。
            translation_v1: 日本語旧版PDF。
            processing_id: 新規処理ID。
            resume_id: 再開対象ID。

        Returns:
            処理IDと変更・修正提案のJSON。

        Raises:
            InputError: 入力・ID・再開条件が不正な場合。
            Exception: 前処理またはAgent操作の失敗。
        """
        sources = {
            "source_v1": source_v1.resolve(),
            "source_v2": source_v2.resolve(),
            "translation_v1": translation_v1.resolve(),
        }
        inputs = pdf_inputs(sources)
        validate_config(self.config, "upgrade")
        identifier = resolve_processing_id(processing_id, resume_id)
        self.root = (
            (self.outputs or Path.cwd() / "outputs").resolve()
            / source_v2.stem
            / identifier
        )
        self.record_path = self.root / "upgrade.json"
        with ProcessingLock(self.root):
            if self.record_path.is_file():
                self.record = load_model(self.record_path, UpgradeRecord)
                if (
                    not resume_id
                    or self.record.upgrade_id != identifier
                    or any(
                        getattr(self.record, role) != item
                        for role, item in inputs.items()
                    )
                ):
                    raise InputError(
                        "Upgrade ID already exists or resume inputs differ"
                    )
            else:
                if resume_id:
                    raise InputError("Upgrade to resume does not exist")
                now = datetime.now(UTC)
                self.record = UpgradeRecord(
                    upgrade_id=identifier,
                    status="processing",
                    source_v1=inputs["source_v1"],
                    source_v2=inputs["source_v2"],
                    translation_v1=inputs["translation_v1"],
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
                    directory = self.root / "upgrade" / "diff"
                    self.execution.perform_task(
                        TaskName.DIFF,
                        documents,
                        [
                            (
                                directory,
                                UpgradeAgent(documents, directory, self.config).run,
                            )
                        ],
                    )
                    result_path = directory / "plan.json"
                    self.record.status, self.record.error = "succeeded", None
                    self.record.outputs = [describe_artifact(self.root, result_path)]
                    self.record.updated_at = datetime.now(UTC)
                    write_model(self.record_path, self.record)
                except KeyboardInterrupt:
                    ArtifactStore(self.record, self.record_path).cancel_processing()
                    raise
        return UpgradeOutcome(
            upgrade_id=identifier, processing_directory=self.root, plan=result_path
        )


class UpgradeAgent:
    """文書の確認状況を保持し、LLMが選んだ操作と終了条件を管理する。"""

    def __init__(
        self, documents: dict[str, Document], directory: Path, config: Config
    ) -> None:
        """比較対象と処理の依存関係を受け取る。

        Args:
            documents: 役割名で区別した比較対象文書。
            directory: 操作の記録と最終一覧の保存先。
            config: LLMの接続と処理予算。
        """
        self.units = agent_units(documents)
        self.directory = directory
        self.config = config

    def run(self) -> UpgradePlan:
        """Agentが対象と比較・再確認を選択し、英文の全範囲を確認する。

        無効な対象指定は確定済み対応を変えずに理由を返し、既存のstep上限内で選び直す。

        Returns:
            未変更を除く変更一覧と全確認範囲。

        Raises:
            InputError: 復元したCallの対応または終了条件が不正な場合。
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
            self.diff = DiffTask(self.client, self.directory, rules, glossary)
            self.confirmed: list[tuple[str, DiffChange]] = []
            self.call_ids: list[str] = []

            restored = completed_agent_calls(self.directory)
            for call in restored:
                action = AgentAction.model_validate({"operation": call.operation})
                for reference in call.target_ids:
                    role, _, identifier = reference.partition(":")
                    action.references.setdefault(role, []).append(identifier)
                self._execute(action, call.round)
            round_number = max((call.round for call in restored), default=-1) + 1
            idle_steps = 0
            group_steps: dict[str, int] = {}
            one_sided_failures = {"source_v1": 0, "source_v2": 0}
            observation: object = {"restored_operations": len(restored)}
            while True:
                covered = {
                    role: {
                        key
                        for _, item in self.confirmed
                        for key in getattr(item, f"{role}_ids")
                    }
                    for role in ("source_v1", "source_v2")
                }
                pending = {
                    role: [key for key in self.units[role] if key not in ids]
                    for role, ids in covered.items()
                }
                # 片側だけの比較が3回続けて失敗した場合、反対版に残りがない要素を確定する。
                if (
                    one_sided_failures["source_v1"] >= 3
                    and not pending["source_v2"]
                    and pending["source_v1"]
                ):
                    self.confirmed.extend(
                        (
                            f"unmatched-v1-{round_number}-{index}",
                            DiffChange(
                                kind="deleted",
                                source_v1_ids=[identifier],
                                summary="新版に対応する英文はありません。旧訳との対応は未確認です。",
                            ),
                        )
                        for index, identifier in enumerate(pending["source_v1"], 1)
                    )
                    one_sided_failures["source_v1"] = 0
                    continue
                if (
                    one_sided_failures["source_v2"] >= 3
                    and not pending["source_v1"]
                    and pending["source_v2"]
                ):
                    self.confirmed.extend(
                        (
                            f"unmatched-v2-{round_number}-{index}",
                            DiffChange(
                                kind="added",
                                source_v2_ids=[identifier],
                                summary="旧版に対応する英文はありません。旧訳との対応は未確認です。",
                            ),
                        )
                        for index, identifier in enumerate(pending["source_v2"], 1)
                    )
                    one_sided_failures["source_v2"] = 0
                    continue
                assigned_translation = {
                    key for _, item in self.confirmed for key in item.translation_v1_ids
                }
                state: dict[str, object] = {
                    "roles": list(self.units),
                    "pending_counts": {role: len(ids) for role, ids in pending.items()},
                    "pending_ids": {role: ids[:8] for role, ids in pending.items()},
                    "translation_candidates": [
                        key
                        for key in self.units["translation_v1"]
                        if key not in assigned_translation
                    ][:8],
                    "confirmed_count": len(self.confirmed),
                }
                if idle_steps >= 12 or time.monotonic() >= deadline:
                    raise TimeoutError("Upgrade Agent reached its step or time limit")
                try:
                    action = choose_action(
                        self.client,
                        "Compare English source_v1/source_v2 and Japanese translation_v1. List changes and proposed edits.",
                        state,
                        observation,
                        self.units,
                    )
                except LLMInvalidResponseError:
                    observation = {
                        "error": "Invalid action response. No action was executed. Choose a valid operation from the current state."
                    }
                    idle_steps += 1
                    continue
                if action.operation == "finish":
                    if any(pending.values()):
                        raise InputError(
                            "Upgrade cannot finish with unconfirmed English units"
                        )
                    break
                before = sum(map(len, covered.values()))
                # 概要・検索は対象群を固定しないため、連続する無進捗回数で制限する。
                if action.references:
                    group_key = repr(action.references)
                    group_steps[group_key] = group_steps.get(group_key, 0) + 1
                    if group_steps[group_key] > 12:
                        raise TimeoutError(
                            "Upgrade target group exceeded 12 Agent steps"
                        )
                if action.operation in {"overview", "read", "search"}:
                    visible = (
                        {
                            role: {
                                key: unit
                                for key, unit in values.items()
                                if key
                                not in (
                                    assigned_translation
                                    if role == "translation_v1"
                                    else covered[role]
                                )
                            }
                            for role, values in self.units.items()
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
                            "error": "Selected scope exceeds the budget. Select fewer units."
                        }
                    except LLMInvalidResponseError:
                        for role, opposite in (
                            ("source_v1", "source_v2"),
                            ("source_v2", "source_v1"),
                        ):
                            selected = set(action.references.get(role, []))
                            if (
                                selected
                                and selected.issubset(pending[role])
                                and not pending[opposite]
                            ):
                                one_sided_failures[role] += 1
                        observation = {
                            "error": "The comparison returned an invalid response after its validation retry. "
                            "No result was accepted. Inspect context and select a different or smaller group."
                        }
                    except InputError as error:
                        observation = {"error": str(error)}
                    else:
                        one_sided_failures = {"source_v1": 0, "source_v2": 0}
                    round_number += 1
                observation = {"action": action.model_dump(), "result": observation}
                after = sum(
                    len(item.source_v1_ids) + len(item.source_v2_ids)
                    for _, item in self.confirmed
                )
                idle_steps = idle_steps + 1 if after <= before else 0
            result = UpgradePlan(
                changes=[
                    VersionChange(id=key, **item.model_dump())
                    for key, item in self.confirmed
                    if item.kind != "unchanged"
                ],
                reviewed_source_v1_ids=[
                    key
                    for key in self.units["source_v1"]
                    if key in covered["source_v1"]
                ],
                reviewed_source_v2_ids=[
                    key
                    for key in self.units["source_v2"]
                    if key in covered["source_v2"]
                ],
            )
            write_model(
                self.directory / "call-index.json",
                LLMCallIndex(task="DIFF", call_ids=list(dict.fromkeys(self.call_ids))),
            )
            write_model(self.directory / "plan.json", result)
            return result
        finally:
            self.client.client.close()

    def _execute(self, action: AgentAction, round_number: int) -> dict[str, object]:
        """選択範囲を比較し、矛盾する旧結果を残さず結果へ反映する。

        Args:
            action: Agentが選んだ比較または再確認。
            round_number: 保存する操作の連番。

        Returns:
            次の判断へ渡す変更結果の概要。

        Raises:
            InputError: 範囲外IDや既存結果と矛盾する部分対応がある場合。
        """
        if action.operation not in {"match", "evaluate", "recheck"}:
            raise InputError("Unsupported Upgrade Agent operation")
        if set(action.references) - set(self.units):
            raise InputError("Unknown Upgrade role")
        chosen = {role: action.references.get(role, []) for role in self.units}
        if (
            not (chosen["source_v1"] or chosen["source_v2"])
            or sum(map(len, chosen.values())) > 32
        ):
            raise InputError(
                "Upgrade comparison requires English IDs and at most 32 units"
            )
        for role, ids in chosen.items():
            if len(ids) != len(set(ids)) or not set(ids).issubset(self.units[role]):
                raise InputError("Invalid Upgrade reference")
        overlaps = [
            item
            for item in self.confirmed
            if set(item[1].source_v1_ids).intersection(chosen["source_v1"])
            or set(item[1].source_v2_ids).intersection(chosen["source_v2"])
        ]
        if overlaps and action.operation != "recheck":
            raise InputError("Use recheck to revisit confirmed changes")
        for _, previous in overlaps:
            if not set(previous.source_v1_ids).issubset(chosen["source_v1"]) or not set(
                previous.source_v2_ids
            ).issubset(chosen["source_v2"]):
                raise InputError(
                    "Recheck must include the complete existing correspondence"
                )
        retained = [item for item in self.confirmed if item not in overlaps]
        used_translation = {
            key for _, item in retained for key in item.translation_v1_ids
        }
        if used_translation.intersection(chosen["translation_v1"]):
            raise InputError(
                "Recheck must include changes already using the selected translation"
            )
        call_id, response = self.diff.run(
            {
                role: [self.units[role][key] for key in ids]
                for role, ids in chosen.items()
            },
            action.operation,
            round_number,
        )
        self.confirmed[:] = retained + [
            (f"change-{call_id}-{index:04d}", item)
            for index, item in enumerate(response.changes, 1)
        ]
        self.call_ids.append(call_id)
        return {
            "changes": [item.model_dump() for item in response.changes[:5]],
            "total": len(response.changes),
        }
