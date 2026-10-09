"""REVIEWの修正候補を決定的に反映するFIX Task。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.models.artifacts import FixResult, ReviewResult, RevisionOutcome
from translate.models.document import Document, TextUnit, text_unit_index

if TYPE_CHECKING:
    from translate.models.review import Revision


def apply_revisions(document: Document, review: ReviewResult) -> FixResult:
    """有効なRevisionだけを順序どおり原子的にDocumentへ反映する。

    Args:
        document (Document): 変換または検証対象のDocument。
        review (ReviewResult): Documentへ適用するReview結果。

    Returns:
        FixResult: 有効なRevisionだけを順序どおり原子的にDocumentへ反映する。
    """

    updated = document.model_copy(deep=True)
    units = text_unit_index(updated)
    changed_spans: set[str] = set()
    outcomes: list[RevisionOutcome] = []
    for revision in review.revisions:
        reason = _rejection_reason(revision, units, changed_spans)
        if reason is not None:
            outcomes.append(
                RevisionOutcome(
                    revision_id=revision.id,
                    status="rejected",
                    reason_code=reason,
                )
            )
            continue
        spans = {span.id: span for span in units[revision.target_id].spans}
        for edit in revision.edits:
            spans[edit.span_id].revised = edit.text
            changed_spans.add(edit.span_id)
        outcomes.append(
            RevisionOutcome(
                revision_id=revision.id,
                status="applied",
                reason_code="applied",
            )
        )
    return FixResult(document=updated, outcomes=outcomes)


def _rejection_reason(  # noqa: PLR0911
    revision: Revision,
    units: dict[str, TextUnit],
    changed_spans: set[str],
) -> str | None:
    """Revision全体を拒否する最初の決定的理由を返す。

    Args:
        revision (Revision): 適用可否と棄却理由を判定する修正候補。
        units (dict[str, TextUnit]): TextUnit IDからTextUnitへの索引。
        changed_spans (set[str]): 変更済みTextSpan ID集合。

    Returns:
        str | None: Revision全体を拒否する最初の決定的理由を返す。
    """

    unit = units.get(revision.target_id)
    if unit is None:
        return "unknown_target"
    valid_span_ids = {span.id for span in unit.spans}
    edit_ids = [edit.span_id for edit in revision.edits]
    if any(span_id not in valid_span_ids for span_id in edit_ids):
        return "unknown_span"
    if len(edit_ids) != len(set(edit_ids)):
        return "duplicate_edit"
    if any(not edit.text.strip() for edit in revision.edits):
        return "empty_text"
    # 長文の既存訳を一部の言い換えだけで全文置換しない。
    for edit in revision.edits:
        current = next(
            span.text("translated").strip()
            for span in unit.spans
            if span.id == edit.span_id
        )
        if len(current) >= 20 and len(edit.text.strip()) * 2 < len(current):
            return "excessive_shortening"
    if any(span_id in changed_spans for span_id in edit_ids):
        return "conflicting_edit"
    return None
