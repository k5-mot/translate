"""対応付け、検査、レビューおよび修正候補のモデル。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from translate.models.document import TextSpan  # noqa: TC001 - Pydantic runtime type.


class ReviewModel(BaseModel):
    """未知fieldを無視するレビューモデルの共通設定。"""

    model_config = ConfigDict(extra="ignore")


class AlignmentGroup(ReviewModel):
    """独立した原文と訳文の決定的な対応関係。"""

    id: str
    source_ids: list[str] = Field(default_factory=list)
    translation_ids: list[str] = Field(default_factory=list)
    kind: Literal["matched", "source_only", "translation_only"]
    method: Literal["unique_anchor", "ordered_role", "unmatched"]


class ReviewTarget(ReviewModel):
    """CHECKとREVIEWへ渡す共通の比較単位。"""

    id: str
    source: str
    translation: str
    target_ids: list[str] = Field(default_factory=list)
    spans: list[TextSpan] = Field(default_factory=list)


class Finding(ReviewModel):
    """決定的検査またはLLMレビューが指摘した一つの問題。"""

    id: str
    origin: Literal["check", "review"]
    category: str
    severity: Literal["info", "warning", "error"]
    target_ids: list[str] = Field(default_factory=list)
    message: str


class TextEdit(ReviewModel):
    """一つのSpanへ適用する修正文字列。"""

    span_id: str
    text: str


class Revision(ReviewModel):
    """一つのTextUnitへ原子的に適用する修正候補。"""

    id: str
    target_id: str
    edits: list[TextEdit] = Field(default_factory=list)


class ReviewFinding(ReviewModel):
    """IDをapplicationが補う前のLLM指摘。"""

    category: str
    severity: Literal["info", "warning", "error"]
    target_ids: list[str] = Field(default_factory=list)
    message: str


class ReviewTextEdit(ReviewModel):
    """LLM応答内のSpan修正。"""

    span_id: str
    text: str


class ReviewRevision(ReviewModel):
    """LLM応答内のTextUnit修正候補。"""

    target_id: str
    edits: list[ReviewTextEdit] = Field(default_factory=list)


class ReviewResponse(ReviewModel):
    """REVIEWのLLMから受け取る浅いstructured output。"""

    findings: list[ReviewFinding] = Field(default_factory=list)
    revisions: list[ReviewRevision] = Field(default_factory=list)
