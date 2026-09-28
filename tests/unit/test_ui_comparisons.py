"""Streamlitの対応単位を揃えた比較表示を検証する。"""

from datetime import UTC, datetime
from pathlib import Path

from translate.artifact_store import sha256_file, write_model
from translate.models.artifacts import (
    AlignmentResult,
    FixResult,
    LLMCallArtifact,
    ReviewResult,
    RevisionOutcome,
)
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.models.review import ReviewTarget, Revision, TextEdit
from translate.models.upgrade import UpgradePlan, VersionChange
from translate.tasks.translation.translate import TranslationItem, TranslationResponse
from translate.ui import (
    _fix_comparison,
    _review_context,
    _translation_comparison,
    _upgrade_context,
)


def _document(values: list[tuple[str, str]]) -> Document:
    """IDとtextから一つのpageを持つDocumentを作る。"""

    return Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id=f"block-{index}",
                        order=index,
                        kind="paragraph",
                        content=TextUnit(
                            id=unit_id,
                            spans=[TextSpan(id=f"span-{unit_id}", source=text)],
                        ),
                    )
                    for index, (unit_id, text) in enumerate(values)
                ],
            )
        ]
    )


def test_review_context_keeps_source_and_translation_on_same_target(
    tmp_path: Path,
) -> None:
    """Review二列は同じReviewTarget IDの原文と訳文を表示する。"""

    write_model(
        tmp_path / "review/align/alignment.json",
        AlignmentResult(
            groups=[],
            targets=[
                ReviewTarget(id="target-1", source="English", translation="日本語"),
                ReviewTarget(id="target-2", source="Second", translation="二番目"),
            ],
        ),
    )

    values = _review_context(tmp_path)

    assert values is not None
    assert "[target-1]\nEnglish" in values[0]
    assert "[target-1]\n日本語" in values[1]


def test_upgrade_context_uses_placeholders_without_guessing(tmp_path: Path) -> None:
    """Upgrade三列はadded、deleted、対応訳なしを規定値で維持する。"""

    write_model(
        tmp_path / "preprocess/source-v1/load/document.json",
        _document([("v1-modified", "old"), ("v1-deleted", "deleted")]),
    )
    write_model(
        tmp_path / "preprocess/source-v2/load/document.json",
        _document([("v2-modified", "new"), ("v2-added", "added")]),
    )
    write_model(
        tmp_path / "preprocess/translation-v1/load/document.json",
        _document([("ja-modified", "旧訳")]),
    )
    write_model(
        tmp_path / "upgrade/diff/plan.json",
        UpgradePlan(
            changes=[
                VersionChange(
                    id="modified",
                    kind="modified",
                    source_v1_ids=["v1-modified"],
                    source_v2_ids=["v2-modified"],
                    translation_v1_ids=["ja-modified"],
                    action="translate",
                    method="ordered_role",
                ),
                VersionChange(
                    id="added",
                    kind="added",
                    source_v2_ids=["v2-added"],
                    action="translate",
                    method="unmatched",
                ),
                VersionChange(
                    id="deleted",
                    kind="deleted",
                    source_v1_ids=["v1-deleted"],
                    action="delete",
                    method="unmatched",
                ),
            ]
        ),
    )

    values = _upgrade_context(tmp_path)

    assert values is not None
    assert "[modified]\nold" in values[0]
    assert "[modified]\n旧訳" in values[1]
    assert "[modified]\nnew" in values[2]
    assert "[added]\n該当なし" in values[0]
    assert "[added]\n該当なし" in values[1]
    assert "[deleted]\n該当なし" in values[2]


def test_translation_comparison_uses_one_verified_call(tmp_path: Path) -> None:
    """TRANSLATE左右は同じ成功Callの対象と検証済み応答を使う。"""

    write_model(
        tmp_path / "preprocess/structure/document.json",
        _document([("unit-1", "English")]),
    )
    call_dir = tmp_path / "translation/translate/calls/call-1"
    write_model(
        call_dir / "response.json",
        TranslationResponse(
            translations=[TranslationItem(span_id="span-unit-1", text="日本語")]
        ),
    )
    now = datetime.now(UTC)
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="TRANSLATE",
            status="succeeded",
            fingerprint="fingerprint",
            target_ids=["span-unit-1"],
            attempts=1,
            response_sha256=sha256_file(call_dir / "response.json"),
            started_at=now,
            updated_at=now,
        ),
    )

    values = _translation_comparison(tmp_path)

    assert values == ("[span-unit-1]\nEnglish", "[span-unit-1]\n日本語")


def test_fix_comparison_shows_only_applied_revision_targets(tmp_path: Path) -> None:
    """FIX左右はapplied outcomeの同じTextUnitだけを表示する。"""

    before = _document([("unit-1", "修正前"), ("unit-2", "対象外")])
    after = _document([("unit-1", "修正後"), ("unit-2", "対象外")])
    write_model(tmp_path / "translation/translate/document.json", before)
    write_model(
        tmp_path / "review/review/review.json",
        ReviewResult(
            findings=[],
            revisions=[
                Revision(
                    id="revision-1",
                    target_id="unit-1",
                    edits=[TextEdit(span_id="span-unit-1", text="修正後")],
                ),
                Revision(
                    id="revision-2",
                    target_id="unit-2",
                    edits=[TextEdit(span_id="span-unit-2", text="拒否")],
                ),
            ],
        ),
    )
    write_model(
        tmp_path / "review/fix/outcomes.json",
        FixResult(
            document=after,
            outcomes=[
                RevisionOutcome(
                    revision_id="revision-1",
                    status="applied",
                    reason_code="applied",
                ),
                RevisionOutcome(
                    revision_id="revision-2",
                    status="rejected",
                    reason_code="conflicting_edit",
                ),
            ],
        ),
    )

    values = _fix_comparison(tmp_path)

    assert values == ("[unit-1]\n修正前", "[unit-1]\n修正後")
