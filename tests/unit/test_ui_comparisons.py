"""Streamlitの対応単位を揃えた比較表示を検証する。"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from translate import ui
from translate.artifact_store import sha256_file, write_model
from translate.models.artifacts import (
    AlignmentResult,
    CheckResult,
    FixResult,
    LLMCallArtifact,
    ReviewResult,
    RevisionOutcome,
)
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.models.review import Finding, ReviewTarget, Revision, TextEdit
from translate.models.upgrade import UpgradePlan, VersionChange
from translate.tasks.translation.translate import TranslationItem, TranslationResponse
from translate.ui import (
    _diff_text,
    _fix_comparison,
    _preview_image_path,
    _review_context,
    _review_rows,
    _translation_comparison,
    _upgrade_context,
)


def test_diff_text_marks_removed_and_added_lines() -> None:
    """差分Collapse用textが変更前後の行を区別する。"""

    value = _diff_text("same\nold", "same\nnew", "before", "after")

    assert "--- before" in value
    assert "+++ after" in value
    assert "-old" in value
    assert "+new" in value


def test_preview_image_path_accepts_only_markdown_local_file(tmp_path: Path) -> None:
    """Preview画像をMarkdown directory内の既存fileへ限定する。"""

    markdown = tmp_path / "publisher/markdown/document.ja.md"
    image = markdown.parent / "assets/figure one.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")

    assert _preview_image_path(markdown, "assets/figure%20one.png") == image.resolve()
    assert _preview_image_path(markdown, "../../outside.png") is None
    assert _preview_image_path(markdown, "https://example.com/image.png") is None


def test_rejected_revisions_are_rendered_in_collapsed_group() -> None:
    """拒否された修正候補を件数付きの閉じたCollapseへまとめる。"""

    with (
        patch.object(ui, "_fix_comparison", return_value=("before", "after")),
        patch.object(ui, "_review_comparison", return_value=None),
        patch.object(ui, "_translation_comparison", return_value=None),
        patch.object(
            ui,
            "_fix_rejections",
            return_value=[
                ("revision-1", "conflicting_edit"),
                ("revision-2", "overlapping_edit"),
            ],
        ),
        patch.object(ui, "_render_text_areas"),
        patch.object(ui, "_render_diff"),
        patch.object(ui.st, "subheader"),
        patch.object(ui.st, "expander") as expander,
        patch.object(ui.st, "markdown") as markdown,
    ):
        ui._render_latest_comparison(Path())  # noqa: SLF001 - UI内部配置の回帰検証。

    expander.assert_called_once_with("拒否された修正候補 (2)", expanded=False)
    assert markdown.call_count == 2
    assert "Revision ID:** `revision-1`" in markdown.call_args_list[0].args[0]
    assert "拒否理由:** `conflicting_edit`" in markdown.call_args_list[0].args[0]
    assert "Revision ID:** `revision-2`" in markdown.call_args_list[1].args[0]


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


def test_review_rows_separate_findings_and_revision_proposals(tmp_path: Path) -> None:
    """Review一覧の行構造を検証する。"""

    write_model(
        tmp_path / "review/align/alignment.json",
        AlignmentResult(
            groups=[],
            targets=[
                ReviewTarget(
                    id="target-1",
                    source="English source",
                    translation="現在の訳",
                    target_ids=["unit-1"],
                )
            ],
        ),
    )
    write_model(
        tmp_path / "review/check/findings.json",
        CheckResult(
            findings=[
                Finding(
                    id="check/target-1/extreme_short",
                    origin="check",
                    category="extreme_short",
                    severity="warning",
                    target_ids=["unit-1"],
                    message="短すぎます。",
                )
            ]
        ),
    )
    write_model(
        tmp_path / "review/review/review.json",
        ReviewResult(
            findings=[],
            revisions=[
                Revision(
                    id="revision-1",
                    target_id="unit-1",
                    edits=[TextEdit(span_id="span-1", text="提案訳")],
                )
            ],
        ),
    )

    findings, revisions = _review_rows(tmp_path)

    assert findings == [
        {
            "種別": "CHECK",
            "重要度": "警告",
            "カテゴリ": "extreme_short",
            "対象": "unit-1",
            "原文": "English source",
            "内容": "短すぎます。",
        }
    ]
    assert revisions == [
        {
            "候補ID": "revision-1",
            "対象": "unit-1",
            "現在の訳": "現在の訳",
            "提案訳": "提案訳",
        }
    ]


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
