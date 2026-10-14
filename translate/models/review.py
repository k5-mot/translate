"""対応付け、検査、レビューおよび修正候補のモデル。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from translate.models.document import Document, TextSpan, iter_text_units


class ReviewModel(BaseModel):
    """未知fieldを無視するレビューモデルの共通設定。"""

    model_config = ConfigDict(extra="ignore")


class AlignmentCandidate(ReviewModel):
    """Agentが提案する原文と訳文の対応。"""

    source_ids: list[str] = Field(default_factory=list)
    translation_ids: list[str] = Field(default_factory=list)
    kind: Literal["matched", "source_only", "translation_only"]
    reason: str | None = None


class AlignmentGroup(AlignmentCandidate):
    """参照検証後にapplicationがIDを付与した対応関係。"""

    id: str


class AgentAction(ReviewModel):
    """Agentが次に行う許可済み操作と、文書内の対象指定。"""

    operation: Literal[
        "overview", "read", "search", "match", "evaluate", "recheck", "finish"
    ]
    references: dict[str, list[str]] = Field(default_factory=dict)
    target_ids: list[str] = Field(default_factory=list)
    role: str = ""
    query: str = ""
    offset: int = Field(default=0, ge=0)


class ReviewTarget(ReviewModel):
    """REVIEWへ渡す原文・訳文と修正可能なSpan。"""

    id: str
    source: str
    translation: str
    target_ids: list[str] = Field(default_factory=list)
    spans: list[TextSpan] = Field(default_factory=list)


class Finding(ReviewModel):
    """LLMレビューが根拠とともに指摘した一つの問題。"""

    id: str
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

    groups: list[AlignmentCandidate] = Field(default_factory=list)
    reviewed_target_ids: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    revisions: list[ReviewRevision] = Field(default_factory=list)


def targets_from_document(document: Document) -> list[ReviewTarget]:
    """Translate後のDocument内IDからREVIEWの対象を作る。

    Args:
        document (Document): 変換または検証対象のDocument。

    Returns:
        list[ReviewTarget]: Translate後のDocument内IDからREVIEWの対象を作る。
    """

    return [
        ReviewTarget(
            id=f"translate/{unit.id}",
            source=unit.text("source"),
            translation=unit.text("revised"),
            target_ids=[unit.id],
            spans=unit.spans,
        )
        for _, unit in iter_text_units(document)
        if unit.text("source").strip()
    ]
