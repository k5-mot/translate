"""Streamlitの対応単位を揃えた比較表示を検証する。"""

from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest

from translate import ui
from translate.adapters.artifact_store import load_model, sha256_file, write_model
from translate.models.artifacts import (
    FixResult,
    LLMCallArtifact,
    ReviewResult,
    RevisionOutcome,
)
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.models.review import (
    AlignmentResponse,
    Finding,
    ReviewResponse,
    ReviewTarget,
    Revision,
    TextEdit,
)
from translate.models.upgrade import DiffResponse, UpgradePlan, VersionChange
from translate.ui import (
    _diff_text,
    _fix_comparison,
    _preview_image_path,
    _review_comparison,
    _review_context,
    _review_rows,
    _review_targets,
    _structure_comparison,
    _translation_comparison,
    _upgrade_context,
)
from translate.ui import comparisons as ui_comparisons

StructurePatch = import_module("translate.tasks.13_structure").StructurePatch
StructureResponse = import_module("translate.tasks.13_structure").StructureResponse
TranslationItem = import_module("translate.tasks.30_translate").TranslationItem
TranslationResponse = import_module("translate.tasks.30_translate").TranslationResponse


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
        patch.object(
            ui_comparisons, "_fix_comparison", return_value=("before", "after")
        ),
        patch.object(ui_comparisons, "_review_comparison", return_value=None),
        patch.object(ui_comparisons, "_translation_comparison", return_value=None),
        patch.object(
            ui_comparisons,
            "_fix_rejections",
            return_value=[
                ("revision-1", "conflicting_edit"),
                ("revision-2", "overlapping_edit"),
            ],
        ),
        patch.object(ui_comparisons, "_render_text_areas"),
        patch.object(ui_comparisons, "_render_diff"),
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
        tmp_path / "tasks/41-review/review.json",
        ReviewResult(
            groups=[],
            targets=[
                ReviewTarget(
                    id="review/target-1", source="English", translation="日本語"
                ),
                ReviewTarget(
                    id="review/target-2", source="Second", translation="二番目"
                ),
            ],
        ),
    )

    values = _review_context(tmp_path)

    assert values is not None
    assert "[review/target-1]\nEnglish" in values[0]
    assert "[review/target-1]\n日本語" in values[1]


def test_review_rows_separate_findings_and_revision_proposals(tmp_path: Path) -> None:
    """Review一覧の行構造を検証する。"""

    write_model(
        tmp_path / "tasks/41-review/review.json",
        ReviewResult(
            groups=[],
            targets=[
                ReviewTarget(
                    id="review/target-1",
                    source="English source",
                    translation="現在の訳",
                    target_ids=["unit-1"],
                )
            ],
        ),
    )
    value = load_model(tmp_path / "tasks/41-review/review.json", ReviewResult)
    value.findings = [
        Finding(
            id="finding-1",
            category="accuracy",
            severity="warning",
            target_ids=["unit-1"],
            message="数値が原文と異なります。",
        )
    ]
    value.revisions = [
        Revision(
            id="revision-1",
            target_id="unit-1",
            edits=[TextEdit(span_id="span-1", text="提案訳")],
        )
    ]
    write_model(tmp_path / "tasks/41-review/review.json", value)

    findings, revisions = _review_rows(tmp_path)

    assert findings == [
        {
            "重要度": "警告",
            "カテゴリ": "accuracy",
            "対象": "unit-1",
            "原文": "English source",
            "現在の訳": "現在の訳",
            "内容": "数値が原文と異なります。",
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
        tmp_path / "tasks/12-load/source-v1/document.json",
        _document([("v1-modified", "old"), ("v1-deleted", "deleted")]),
    )
    write_model(
        tmp_path / "tasks/12-load/source-v2/document.json",
        _document([("v2-modified", "new"), ("v2-added", "added")]),
    )
    write_model(
        tmp_path / "tasks/12-load/translation-v1/document.json",
        _document([("ja-modified", "旧訳")]),
    )
    write_model(
        tmp_path / "tasks/21-diff/plan.json",
        UpgradePlan(
            changes=[
                VersionChange(
                    id="modified",
                    kind="modified",
                    source_v1_ids=["v1-modified"],
                    source_v2_ids=["v2-modified"],
                    translation_v1_ids=["ja-modified"],
                    summary="変更",
                ),
                VersionChange(
                    id="added",
                    kind="added",
                    source_v2_ids=["v2-added"],
                    summary="追加",
                ),
                VersionChange(
                    id="deleted",
                    kind="deleted",
                    source_v1_ids=["v1-deleted"],
                    summary="削除",
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
        tmp_path / "tasks/13-structure/document.json",
        _document([("unit-1", "English")]),
    )
    call_dir = tmp_path / "tasks/30-translate/calls/call-1"
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


@pytest.mark.parametrize(
    "document_path",
    ["tasks/12-load/document.json", "tasks/12-load/source-v2/document.json"],
)
def test_structure_comparison_shows_active_block_text(
    tmp_path: Path, document_path: str
) -> None:
    """STRUCTUREの処理中Callに含まれるBlockと未確定状態を表示する。"""

    write_model(
        tmp_path / document_path,
        _document([("unit-1", "Processing text"), ("unit-2", "Other text")]),
    )
    now = datetime.now(UTC)
    write_model(
        tmp_path / "tasks/13-structure/calls/call-1/call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="STRUCTURE",
            status="processing",
            fingerprint="structure",
            target_ids=["block-0"],
            attempts=1,
            started_at=now,
            updated_at=now,
        ),
    )

    assert _structure_comparison(tmp_path) == (
        (
            "[block-0]\n種別: paragraph\n見出しレベル: -\n注意種別: -"
            "\nキャプション元: -\n本文: Processing text"
        ),
        "処理中 (確定結果なし)",
    )


def test_structure_comparison_shows_verified_patch_diff(tmp_path: Path) -> None:
    """検証済みSTRUCTURE応答の構造変更を同じBlockの前後に表示する。"""

    write_model(
        tmp_path / "tasks/12-load/document.json", _document([("unit-1", "Title")])
    )
    call_dir = tmp_path / "tasks/13-structure/calls/call-1"
    write_model(
        call_dir / "response.json",
        StructureResponse(
            patches=[StructurePatch(block_id="block-0", kind="heading", level=2)]
        ),
    )
    now = datetime.now(UTC)
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="STRUCTURE",
            status="succeeded",
            fingerprint="structure",
            target_ids=["block-0"],
            attempts=1,
            response_sha256=sha256_file(call_dir / "response.json"),
            started_at=now,
            updated_at=now,
        ),
    )

    before, after = _structure_comparison(tmp_path) or ("", "")

    assert "種別: paragraph" in before
    assert "種別: heading" in after
    assert "見出しレベル: 2" in after
    assert "-種別: paragraph" in _diff_text(before, after, "前", "後")
    assert "+種別: heading" in _diff_text(before, after, "前", "後")


def test_fix_comparison_shows_only_applied_revision_targets(tmp_path: Path) -> None:
    """FIX左右はapplied outcomeの同じTextUnitだけを表示する。"""

    before = _document([("unit-1", "修正前"), ("unit-2", "対象外")])
    after = _document([("unit-1", "修正後"), ("unit-2", "対象外")])
    write_model(tmp_path / "tasks/30-translate/document.json", before)
    write_model(
        tmp_path / "tasks/41-review/review.json",
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
        tmp_path / "tasks/42-fix/outcomes.json",
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


def test_upgrade_displays_verified_call_before_final_plan(tmp_path: Path) -> None:
    """DIFF途中の成功応答を三列へ表示し、改ざんされた応答は表示しない。"""
    for role, key, text in (
        ("source-v1", "old", "Old text"),
        ("source-v2", "new", "New text"),
        ("translation-v1", "ja", "旧訳"),
    ):
        write_model(
            tmp_path / f"tasks/12-load/{role}/document.json", _document([(key, text)])
        )
    call_dir = tmp_path / "tasks/21-diff/calls/call-1"
    write_model(
        call_dir / "response.json",
        DiffResponse.model_validate(
            {
                "changes": [
                    {
                        "kind": "modified",
                        "source_v1_ids": ["old"],
                        "source_v2_ids": ["new"],
                        "translation_v1_ids": ["ja"],
                        "summary": "Changed",
                    }
                ],
                "reviewed_source_v1_ids": ["old"],
                "reviewed_source_v2_ids": ["new"],
            }
        ),
    )
    now = datetime.now(UTC)
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="DIFF",
            operation="evaluate",
            status="succeeded",
            fingerprint="input",
            target_ids=["source_v2:new"],
            attempts=1,
            response_sha256=sha256_file(call_dir / "response.json"),
            started_at=now,
            updated_at=now,
        ),
    )
    assert _upgrade_context(tmp_path) == (
        "[call-1/0]\nOld text",
        "[call-1/0]\n旧訳",
        "[call-1/0]\nNew text",
    )
    (call_dir / "response.json").write_text("{}", encoding="utf-8")
    assert _upgrade_context(tmp_path) is None


def test_review_comparison_resolves_agent_ids_and_revision_units(
    tmp_path: Path,
) -> None:
    """Agentのrole付き対象IDとTextUnitを参照する提案を同じCallから表示する。"""
    write_model(
        tmp_path / "tasks/41-review/review.json",
        ReviewResult(
            targets=[
                ReviewTarget(
                    id="review/alignment-000001",
                    source="English",
                    translation="現在訳",
                    target_ids=["unit"],
                ),
            ]
        ),
    )
    call_dir = tmp_path / "tasks/41-review/calls/call-1"
    write_model(
        call_dir / "response.json",
        ReviewResponse.model_validate(
            {
                "assessments": [
                    {
                        "target_id": "review/alignment-000001",
                        "reason": "訳文を修正する",
                        "verdict": "issue",
                        "category": "accuracy",
                        "severity": "warning",
                        "edits": [{"span_id": "span-unit", "text": "修正案"}],
                    }
                ],
            }
        ),
    )
    now = datetime.now(UTC)
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="REVIEW",
            operation="evaluate",
            status="succeeded",
            fingerprint="input",
            target_ids=["review:review/alignment-000001"],
            attempts=1,
            response_sha256=sha256_file(call_dir / "response.json"),
            started_at=now,
            updated_at=now,
        ),
    )
    assert _review_comparison(tmp_path) == (
        "[review/alignment-000001]\n現在訳",
        "[review/alignment-000001]\n修正案",
    )


def test_review_preview_reads_alignment_response(tmp_path: Path) -> None:
    """対応付け専用の成功応答から、評価前にも同じ英日単位を比較表示する。"""
    for role, identifier, text in [
        ("source", "en", "English"),
        ("translation", "ja", "訳文"),
    ]:
        write_model(
            tmp_path / "tasks" / "12-load" / role / "document.json",
            _document([(identifier, text)]),
        )
    directory = tmp_path / "tasks/41-review/calls/match-call"
    write_model(
        directory / "response.json",
        AlignmentResponse.model_validate(
            {
                "groups": [
                    {
                        "source_ids": ["en"],
                        "translation_ids": ["ja"],
                        "kind": "matched",
                    },
                ]
            }
        ),
    )
    now = datetime.now(UTC)
    write_model(
        directory / "call.json",
        LLMCallArtifact(
            call_id="match-call",
            task="REVIEW",
            operation="match",
            status="succeeded",
            fingerprint="inputs",
            target_ids=["source:en", "translation:ja"],
            attempts=1,
            response_sha256=sha256_file(directory / "response.json"),
            started_at=now,
            updated_at=now,
        ),
    )
    assert _review_targets(tmp_path) == {
        "review/alignment-000001": ("English", "訳文"),
        "ja": ("English", "訳文"),
    }
