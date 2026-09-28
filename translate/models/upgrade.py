"""Upgradeの版間差分、再利用結果および処理記録。"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves this runtime type.
from typing import Literal

from pydantic import Field, field_validator

from translate.models.artifacts import (
    ArtifactFile,
    ArtifactModel,
    InputFile,
    LLMProgress,
    ProcessingError,
    ProcessingStatus,
    TaskState,
)

ChangeKind = Literal["unchanged", "moved", "modified", "added", "deleted"]
ChangeAction = Literal["reuse", "translate", "delete"]
ChangeMethod = Literal["unique_text", "unique_anchor", "ordered_role", "unmatched"]


def _validate_aware(value: datetime) -> datetime:
    """Upgradeの永続化日時をtimezone-aware値に限定する。"""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class VersionChange(ArtifactModel):
    """英文の版間対応と日本語v1の採用方針。"""

    id: str
    kind: ChangeKind
    source_v1_ids: list[str] = Field(default_factory=list)
    source_v2_ids: list[str] = Field(default_factory=list)
    translation_v1_ids: list[str] = Field(default_factory=list)
    action: ChangeAction
    method: ChangeMethod


class UpgradePlan(ArtifactModel):
    """DIFFが確定した順序付き変更一覧。"""

    schema_version: Literal[1] = 1
    changes: list[VersionChange] = Field(default_factory=list)


class ReuseReport(ArtifactModel):
    """REUSEが移植したTextUnitと翻訳対象。"""

    schema_version: Literal[1] = 1
    reused_unit_ids: list[str] = Field(default_factory=list)
    translation_target_ids: list[str] = Field(default_factory=list)


class UpgradeRecord(ArtifactModel):
    """Upgrade処理全体の正本となる最上位記録。"""

    schema_version: Literal[1] = 1
    upgrade_id: str
    status: ProcessingStatus
    source_v1: InputFile
    source_v2: InputFile
    translation_v1: InputFile
    source_language: Literal["en"] = "en"
    target_language: Literal["ja"] = "ja"
    backend: Literal["llm", "libretranslate"] = "llm"
    tasks: list[TaskState] = Field(default_factory=list)
    llm_progress: list[LLMProgress] = Field(default_factory=list)
    outputs: list[ArtifactFile] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    error: ProcessingError | None = None

    _created_aware = field_validator("created_at")(_validate_aware)
    _updated_aware = field_validator("updated_at")(_validate_aware)
