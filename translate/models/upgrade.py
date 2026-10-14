"""Upgradeの版間差分、再利用結果および処理記録。"""

from datetime import datetime
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


def _validate_aware(value: datetime) -> datetime:
    """Upgradeの永続化日時をtimezone-aware値に限定する。

    Args:
        value (datetime): Timezone情報を検証する日時。

    Returns:
        datetime: Upgradeの永続化日時をtimezone-aware値に限定する。

    Raises:
        ValueError: `datetime must be timezone-aware`と判定した場合。
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class DiffChange(ArtifactModel):
    """LLMが返す版間対応と変更の説明。未変更も確認範囲として受け取る。"""

    kind: ChangeKind
    source_v1_ids: list[str] = Field(default_factory=list)
    source_v2_ids: list[str] = Field(default_factory=list)
    translation_v1_ids: list[str] = Field(default_factory=list)
    summary: str
    suggested_translation: str | None = None


class VersionChange(DiffChange):
    """利用者へ提示する一つの変更箇所と修正提案。"""

    id: str
    kind: Literal["moved", "modified", "added", "deleted"]


class DiffResponse(ArtifactModel):
    """DIFFの応答。未変更項目を含め、確認した新旧英文IDを返す。"""

    changes: list[DiffChange] = Field(default_factory=list)
    reviewed_source_v1_ids: list[str] = Field(default_factory=list)
    reviewed_source_v2_ids: list[str] = Field(default_factory=list)


class UpgradePlan(ArtifactModel):
    """変更項目と、未変更を含む全確認範囲の記録。"""

    schema_version: Literal[1] = 1
    changes: list[VersionChange] = Field(default_factory=list)
    reviewed_source_v1_ids: list[str] = Field(default_factory=list)
    reviewed_source_v2_ids: list[str] = Field(default_factory=list)


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
    tasks: list[TaskState] = Field(default_factory=list)
    llm_progress: list[LLMProgress] = Field(default_factory=list)
    outputs: list[ArtifactFile] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    error: ProcessingError | None = None

    _created_aware = field_validator("created_at")(_validate_aware)
    _updated_aware = field_validator("updated_at")(_validate_aware)
