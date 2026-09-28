"""処理状態、ManifestおよびTask成果物の永続化モデル。"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves this runtime type.
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from translate.models.document import Document  # noqa: TC001 - Pydantic runtime type.
from translate.models.review import (  # noqa: TC001 - Pydantic runtime types.
    AlignmentGroup,
    Finding,
    ReviewTarget,
    Revision,
)

ProcessingStatus = Literal["processing", "succeeded", "failed", "cancelled"]
TaskStatus = Literal["processing", "succeeded", "failed", "cancelled", "skipped"]
LLMTaskName = Literal["STRUCTURE", "TRANSLATE", "REVIEW"]
LLMCallStatus = Literal["processing", "succeeded", "partial", "split", "failed"]


class TaskName(StrEnum):
    """Pipelineで永続化するTask名。"""

    SPLIT = "SPLIT"
    DOCLING = "DOCLING"
    UNPACK = "UNPACK"
    MERGE = "MERGE"
    POSITION = "POSITION"
    NORMALIZE = "NORMALIZE"
    LOAD = "LOAD"
    STRUCTURE = "STRUCTURE"
    TRANSLATE = "TRANSLATE"
    TRANSLATE_LITE = "TRANSLATE_LITE"
    ALIGN = "ALIGN"
    DIFF = "DIFF"
    REUSE = "REUSE"
    CHECK = "CHECK"
    REVIEW = "REVIEW"
    FIX = "FIX"
    LINT = "LINT"
    COVER = "COVER"
    MARKDOWN = "MARKDOWN"
    DOCX = "DOCX"
    REPORT = "REPORT"


class ArtifactModel(BaseModel):
    """未知fieldを無視するArtifactモデルの共通設定。"""

    model_config = ConfigDict(extra="ignore")


def _validate_aware(value: datetime) -> datetime:
    """永続化日時がUTCへ変換可能なtimezone-aware値であることを保証する。"""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def _validate_relative_path(value: str) -> str:
    """Artifact pathを安全なPOSIX相対pathに限定する。"""

    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("path must be a safe POSIX relative path")
    return value


class InputFile(ArtifactModel):
    """処理開始時に受理した一つの入力file。"""

    role: str
    logical_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    _safe_path = field_validator("logical_path")(_validate_relative_path)


class ArtifactFile(ArtifactModel):
    """処理ディレクトリを基準とした一つの成果物。"""

    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    _safe_path = field_validator("relative_path")(_validate_relative_path)


class ProcessingError(ArtifactModel):
    """外部本文を含めずに永続化する処理失敗。"""

    code: str
    message: str
    cause_type: str | None = None
    retryable: bool = False


class TaskState(ArtifactModel):
    """開始済みTaskの状態と公開済み成果物。"""

    task: TaskName
    status: TaskStatus
    fingerprint: str
    started_at: datetime
    completed_at: datetime | None = None
    artifacts: list[ArtifactFile] = Field(default_factory=list)
    error: ProcessingError | None = None

    _started_aware = field_validator("started_at")(_validate_aware)
    _completed_aware = field_validator("completed_at")(
        lambda value: _validate_aware(value) if value is not None else value
    )


class LLMProgress(ArtifactModel):
    """一つのLLM Taskの集約進捗。"""

    task: LLMTaskName
    planned_calls: int = Field(ge=0)
    completed_calls: int = Field(ge=0)
    reused_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    updated_at: datetime

    _updated_aware = field_validator("updated_at")(_validate_aware)


class LLMTaskDiagnostics(ArtifactModel):
    """Schema検証後に適用しなかったLLM項目の説明。"""

    schema_version: Literal[1] = 1
    task: LLMTaskName
    diagnostics: list[str] = Field(default_factory=list)
    updated_at: datetime

    _updated_aware = field_validator("updated_at")(_validate_aware)


class LLMCallIndex(ArtifactModel):
    """LLM Taskの最終結果へ実際に採用したCall ID一覧。"""

    schema_version: Literal[1] = 1
    task: LLMTaskName
    call_ids: list[str]

    @field_validator("call_ids")
    @classmethod
    def validate_unique_calls(cls, value: list[str]) -> list[str]:
        """Call IDを出現順を保った重複なしの一覧へ限定する。"""

        if len(value) != len(set(value)):
            raise ValueError("call IDs must be unique")
        return value


class LLMCallArtifact(ArtifactModel):
    """一つの論理的なLLM要求の再開情報。"""

    schema_version: Literal[1] = 1
    response_schema_version: Literal[1] = 1
    call_id: str
    task: LLMTaskName
    status: LLMCallStatus
    fingerprint: str
    target_ids: list[str]
    attempts: int = Field(ge=0)
    child_call_ids: list[str] = Field(default_factory=list)
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    started_at: datetime
    updated_at: datetime
    error: ProcessingError | None = None

    _started_aware = field_validator("started_at")(_validate_aware)
    _updated_aware = field_validator("updated_at")(_validate_aware)


class TranslationRecord(ArtifactModel):
    """Translate処理全体の正本となる最上位記録。"""

    schema_version: Literal[1] = 1
    translation_id: str
    status: ProcessingStatus
    source: InputFile
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


class ReviewRecord(ArtifactModel):
    """比較Review処理全体の正本となる最上位記録。"""

    schema_version: Literal[1] = 1
    review_id: str
    status: ProcessingStatus
    source: InputFile
    translation: InputFile
    tasks: list[TaskState] = Field(default_factory=list)
    llm_progress: list[LLMProgress] = Field(default_factory=list)
    outputs: list[ArtifactFile] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    error: ProcessingError | None = None

    _created_aware = field_validator("created_at")(_validate_aware)
    _updated_aware = field_validator("updated_at")(_validate_aware)


class RegistrationSourceResult(ArtifactModel):
    """一つの参照資料をQdrantへ登録した結果。"""

    logical_path: str
    sha256: str
    revision: str
    point_count: int = Field(ge=0)
    status: Literal["registered", "unchanged"]


class RegistrationResult(ArtifactModel):
    """Register処理のQdrant登録結果。"""

    collection: str
    embedding_model: str
    sources: list[RegistrationSourceResult] = Field(default_factory=list)
    total_points: int = Field(ge=0)


class RegistrationRecord(ArtifactModel):
    """Register処理全体の正本となる最上位記録。"""

    schema_version: Literal[1] = 1
    registration_id: str
    status: ProcessingStatus
    source_id: str | None = None
    inputs: list[InputFile]
    fingerprint: str
    collection: str
    embedding_model: str
    result: RegistrationResult | None = None
    created_at: datetime
    updated_at: datetime
    error: ProcessingError | None = None

    _created_aware = field_validator("created_at")(_validate_aware)
    _updated_aware = field_validator("updated_at")(_validate_aware)


class SplitPart(ArtifactModel):
    """分割PDFと元文書上のpage範囲。"""

    number: int = Field(ge=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    file: ArtifactFile


class SplitManifest(ArtifactModel):
    """SPLITが公開する分割PDF一覧。"""

    schema_version: Literal[1] = 1
    source_sha256: str
    total_pages: int = Field(ge=1)
    parts: list[SplitPart]


class DoclingPart(ArtifactModel):
    """一つの分割fileに対応するDocling成果。"""

    number: int = Field(ge=1)
    job_id: str
    archive: ArtifactFile
    poll_attempts: int = Field(ge=1)


class DoclingManifest(ArtifactModel):
    """DOCLINGが公開するarchive一覧。"""

    schema_version: Literal[1] = 1
    parts: list[DoclingPart]


class UnpackedPart(ArtifactModel):
    """安全に展開されたDocling JSONとasset。"""

    number: int = Field(ge=1)
    document: ArtifactFile
    assets: list[ArtifactFile] = Field(default_factory=list)


class UnpackManifest(ArtifactModel):
    """UNPACKが公開する展開済み成果一覧。"""

    schema_version: Literal[1] = 1
    parts: list[UnpackedPart]


class TransformReport(ArtifactModel):
    """決定的なJSON変換の入出力hashと診断。"""

    schema_version: Literal[1] = 1
    task: TaskName
    input_sha256: str
    output_sha256: str
    diagnostics: list[str] = Field(default_factory=list)


class AlignmentResult(ArtifactModel):
    """ALIGNの対応群とレビュー対象。"""

    schema_version: Literal[1] = 1
    groups: list[AlignmentGroup]
    targets: list[ReviewTarget]


class CheckResult(ArtifactModel):
    """CHECKが決定的に検出した指摘。"""

    schema_version: Literal[1] = 1
    findings: list[Finding]


class ReviewResult(ArtifactModel):
    """REVIEWが生成した指摘と修正候補。"""

    schema_version: Literal[1] = 1
    findings: list[Finding]
    revisions: list[Revision]


class RevisionOutcome(ArtifactModel):
    """FIXが一つのRevisionを受理または拒否した結果。"""

    revision_id: str
    status: Literal["applied", "rejected"]
    reason_code: str


class FixResult(ArtifactModel):
    """FIX後のDocumentと各候補の適用結果。"""

    schema_version: Literal[1] = 1
    document: Document
    outcomes: list[RevisionOutcome]


class LintDiagnostic(ArtifactModel):
    """公開前検査で見つかった一つの問題。"""

    code: str
    path: str
    message: str


class LintResult(ArtifactModel):
    """最終Documentとassetの公開可否。"""

    schema_version: Literal[1] = 1
    valid: bool
    document_sha256: str
    diagnostics: list[LintDiagnostic]


class CoverResult(ArtifactModel):
    """COVERが生成した表紙画像と除外page。"""

    schema_version: Literal[1] = 1
    image: ArtifactFile
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    excluded_page_numbers: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pages(self) -> Self:
        """除外pageを正の昇順かつ重複なしに限定する。"""

        if self.excluded_page_numbers != sorted(set(self.excluded_page_numbers)):
            raise ValueError("excluded pages must be unique and sorted")
        if any(number < 1 for number in self.excluded_page_numbers):
            raise ValueError("excluded pages must be positive")
        return self
