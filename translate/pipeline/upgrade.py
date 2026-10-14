"""英文二版と旧訳をAgentで比較し、変更箇所と修正提案を公開する。"""

import time
from datetime import UTC, datetime
from functools import partial
from importlib import import_module
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from translate.adapters.artifact_store import (
    ProcessingLock,
    cancel_processing,
    describe_artifact,
    load_model,
    write_model,
)
from translate.adapters.llm import (
    LLMClient,
    LLMInputExceededError,
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
    agent_units,
    choose_action,
    completed_agent_calls,
    observe_documents,
    pdf_inputs,
    perform_task,
    prepare_documents,
    resolve_processing_id,
)

diff_task = import_module("translate.tasks.21_diff")


class UpgradeOutcome(BaseModel):
    """UIへ返すUpgrade IDと変更一覧JSON。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)
    upgrade_id: str
    processing_directory: Path
    plan: Path


def upgrade_pdfs(
    source_v1: Path,
    source_v2: Path,
    translation_v1: Path,
    config: Config,
    *,
    processing_id: str | None = None,
    resume_id: str | None = None,
    outputs: Path | None = None,
) -> UpgradeOutcome:
    """三つのPDFを比較し、文書へ適用せず変更と提案の一覧を公開する。

    Args:
        source_v1: 英文旧版PDF。
        source_v2: 英文新版PDF。
        translation_v1: 日本語旧版PDF。
        config: 接続とLLM予算の設定。
        processing_id: 新規処理ID。
        resume_id: 再開対象ID。
        outputs: 出力root。省略時は作業directoryのoutputs。

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
    validate_config(config, "upgrade")
    identifier = resolve_processing_id(processing_id, resume_id)
    root = (outputs or Path.cwd() / "outputs").resolve() / source_v2.stem / identifier
    record_path = root / "upgrade.json"
    with ProcessingLock(root):
        if record_path.is_file():
            record = load_model(record_path, UpgradeRecord)
            if (
                not resume_id
                or record.upgrade_id != identifier
                or any(getattr(record, role) != item for role, item in inputs.items())
            ):
                raise InputError("Upgrade ID already exists or resume inputs differ")
        else:
            if resume_id:
                raise InputError("Upgrade to resume does not exist")
            now = datetime.now(UTC)
            record = UpgradeRecord(
                upgrade_id=identifier,
                status="processing",
                source_v1=inputs["source_v1"],
                source_v2=inputs["source_v2"],
                translation_v1=inputs["translation_v1"],
                created_at=now,
                updated_at=now,
            )
            write_model(record_path, record)
        with processing_logging(root, config.log_level):
            try:
                documents, _ = prepare_documents(
                    sources, record, record_path, root, config
                )
                directory = root / "upgrade" / "diff"
                perform_task(
                    record,
                    record_path,
                    root,
                    TaskName.DIFF,
                    documents,
                    [(directory, partial(run_agent, documents, directory, config))],
                )
                result_path = directory / "plan.json"
                record.status, record.error = "succeeded", None
                record.outputs = [describe_artifact(root, result_path)]
                record.updated_at = datetime.now(UTC)
                write_model(record_path, record)
            except KeyboardInterrupt:
                cancel_processing(record, record_path)
                raise
    return UpgradeOutcome(
        upgrade_id=identifier, processing_directory=root, plan=result_path
    )


def run_agent(
    documents: dict[str, Document], directory: Path, config: Config
) -> UpgradePlan:
    """Agentが対象と比較・再確認を選択し、英文の全範囲を確認する。

    Args:
        documents: 英文二版と旧訳のDocument。
        directory: DIFF成果物directory。
        config: 接続と判断の上限設定。

    Returns:
        未変更を除く変更一覧と全確認範囲。

    Raises:
        InputError: 参照・対応・終了条件が不正な場合。
        TimeoutError: 判断回数またはTask期限を超えた場合。
        LLMError: 外部要求が失敗した場合。
    """
    units = agent_units(documents)
    client = LLMClient(config)
    deadline = time.monotonic() + config.llm_task_deadline_seconds
    client.deadline = deadline
    try:
        templates = Path(__file__).parents[1] / "templates"
        rules = (templates / "review-rules.md").read_text(encoding="utf-8")
        glossary = (templates / "glossary.csv").read_text(encoding="utf-8")
        confirmed: list[tuple[str, DiffChange]] = []
        call_ids: list[str] = []

        def execute(action: AgentAction, round_number: int) -> dict[str, object]:
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
            if set(action.references) - set(units):
                raise InputError("Unknown Upgrade role")
            chosen = {role: action.references.get(role, []) for role in units}
            if (
                not (chosen["source_v1"] or chosen["source_v2"])
                or sum(map(len, chosen.values())) > 32
            ):
                raise InputError(
                    "Upgrade comparison requires English IDs and at most 32 units"
                )
            for role, ids in chosen.items():
                if len(ids) != len(set(ids)) or not set(ids).issubset(units[role]):
                    raise InputError("Invalid Upgrade reference")
            overlaps = [
                item
                for item in confirmed
                if set(item[1].source_v1_ids).intersection(chosen["source_v1"])
                or set(item[1].source_v2_ids).intersection(chosen["source_v2"])
            ]
            if overlaps and action.operation != "recheck":
                raise InputError("Use recheck to revisit confirmed changes")
            for _, previous in overlaps:
                if not set(previous.source_v1_ids).issubset(
                    chosen["source_v1"]
                ) or not set(previous.source_v2_ids).issubset(chosen["source_v2"]):
                    raise InputError(
                        "Recheck must include the complete existing correspondence"
                    )
            retained = [item for item in confirmed if item not in overlaps]
            used_translation = {
                key for _, item in retained for key in item.translation_v1_ids
            }
            if used_translation.intersection(chosen["translation_v1"]):
                raise InputError(
                    "Recheck must include changes already using the selected translation"
                )
            call_id, response = diff_task.diff(
                {
                    role: [units[role][key] for key in ids]
                    for role, ids in chosen.items()
                },
                directory,
                client,
                rules,
                glossary,
                action.operation,
                round_number,
            )
            confirmed[:] = retained + [
                (f"change-{call_id}-{index:04d}", item)
                for index, item in enumerate(response.changes, 1)
            ]
            call_ids.append(call_id)
            return {
                "changes": [item.model_dump() for item in response.changes[:5]],
                "total": len(response.changes),
            }

        restored = completed_agent_calls(directory)
        for call in restored:
            action = AgentAction.model_validate({"operation": call.operation})
            for reference in call.target_ids:
                role, _, identifier = reference.partition(":")
                action.references.setdefault(role, []).append(identifier)
            execute(action, call.round)
        round_number = max((call.round for call in restored), default=-1) + 1
        idle_steps = 0
        group_steps: dict[str, int] = {}
        observation: object = {"restored_operations": len(restored)}
        while True:
            covered = {
                role: {
                    key for _, item in confirmed for key in getattr(item, f"{role}_ids")
                }
                for role in ("source_v1", "source_v2")
            }
            pending = {
                role: [key for key in units[role] if key not in ids]
                for role, ids in covered.items()
            }
            state: dict[str, object] = {
                "roles": list(units),
                "pending_counts": {role: len(ids) for role, ids in pending.items()},
                "pending_ids": {role: ids[:8] for role, ids in pending.items()},
                "translation_candidates": list(units["translation_v1"])[:8],
                "confirmed_count": len(confirmed),
            }
            if idle_steps >= 12 or time.monotonic() >= deadline:
                raise TimeoutError("Upgrade Agent reached its step or time limit")
            action = choose_action(
                client,
                "Compare English source_v1/source_v2 and Japanese translation_v1. List changes and proposed edits.",
                state,
                observation,
                units,
            )
            if action.operation == "finish":
                if any(pending.values()):
                    raise InputError(
                        "Upgrade cannot finish with unconfirmed English units"
                    )
                break
            before = sum(map(len, covered.values()))
            group_key = repr(
                (action.references, action.role, action.query, action.offset)
            )
            group_steps[group_key] = group_steps.get(group_key, 0) + 1
            if group_steps[group_key] > 12:
                raise TimeoutError("Upgrade target group exceeded 12 Agent steps")
            if action.operation in {"overview", "read", "search"}:
                visible = (
                    {
                        role: {key: values[key] for key in pending.get(role, values)}
                        for role, values in units.items()
                    }
                    if action.operation == "overview"
                    else units
                )
                observation = observe_documents(
                    action, visible, max(512, config.review_input_tokens // 3)
                )
            else:
                try:
                    observation = execute(action, round_number)
                except (LLMInputExceededError, LLMOutputExceededError):
                    observation = {
                        "error": "Selected scope exceeds the budget. Select fewer units."
                    }
                round_number += 1
            observation = {"action": action.model_dump(), "result": observation}
            after = sum(
                len(item.source_v1_ids) + len(item.source_v2_ids)
                for _, item in confirmed
            )
            idle_steps = idle_steps + 1 if after <= before else 0
        result = UpgradePlan(
            changes=[
                VersionChange(id=key, **item.model_dump())
                for key, item in confirmed
                if item.kind != "unchanged"
            ],
            reviewed_source_v1_ids=[
                key for key in units["source_v1"] if key in covered["source_v1"]
            ],
            reviewed_source_v2_ids=[
                key for key in units["source_v2"] if key in covered["source_v2"]
            ],
        )
        write_model(
            directory / "call-index.json",
            LLMCallIndex(task="DIFF", call_ids=list(dict.fromkeys(call_ids))),
        )
        write_model(directory / "plan.json", result)
        return result
    finally:
        client.client.close()
