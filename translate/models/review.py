"""対応付け、検査、レビューおよび修正候補のモデル。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from translate.models.document import Document, TextSpan


class ReviewModel(BaseModel):
    """未知fieldを無視するレビューモデルの共通設定。"""

    model_config = ConfigDict(extra="ignore")


class AlignmentCandidate(ReviewModel):
    """Agentが提案する原文と訳文の対応。"""

    source_ids: list[str]
    translation_ids: list[str]
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

    @classmethod
    def from_document(cls, document: Document) -> list[Self]:
        """Translate後のDocument内IDからREVIEWの対象を作る。

        Args:
            document (Document): 変換または検証対象のDocument。

        Returns:
            list[ReviewTarget]: Translate後のDocument内IDからREVIEWの対象を作る。
        """

        return [
            cls(
                id=f"translate/{unit.id}",
                source=unit.text("source"),
                translation=unit.text("revised"),
                target_ids=[unit.id],
                spans=unit.spans,
            )
            for _, unit in document.text_units()
            if unit.text("source").strip()
        ]


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


class ReviewTextEdit(ReviewModel):
    """LLM応答内のSpan修正。"""

    span_id: str
    text: str


class ReviewAssessment(ReviewModel):
    """一つの比較対象の判定と修正案。正常な対象の分類と重要度は空とする。"""

    target_id: str
    reason: str = Field(min_length=1)
    verdict: Literal["correct", "issue"]
    edits: list[ReviewTextEdit]
    category: str | None
    severity: Literal["info", "warning", "error"] | None


class AlignmentResponse(ReviewModel):
    """対応付け操作から受け取る対応関係だけの応答。"""

    groups: list[AlignmentCandidate] = Field(min_length=1)


class ReviewResponse(ReviewModel):
    """各比較対象を一度ずつ判定した品質評価の応答。"""

    assessments: list[ReviewAssessment]
