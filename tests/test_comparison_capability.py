"""比較Review Capabilityの独立入力、Finding集計および0件Reportを検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from translate.common.workspace import sha256_file
from translate.document import Block, Document, Finding, Inline, Page
from translate.tasks import align, check, report, review
from translate.workflows.comparison_review import _comparison_document

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def _document(block_id: str, text: str) -> Document:
    """指定した原文を一つのBlockに持つ文書を作り、独立英日入力の比較条件を固定する。"""

    return Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id=block_id,
                        order=0,
                        kind="paragraph",
                        source=[Inline(id=f"{block_id}/text", text=text)],
                    )
                ],
            )
        ]
    )


@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["clean", "findings"])
def test_comparison_capability_reports_findings_or_explicit_zero_without_mutation(
    scenario: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """合成した英日Documentから指摘あり/なしのReportを作る。PDF解析は行わない。"""

    source_pdf = tmp_path / "independent-en.pdf"
    target_pdf = tmp_path / "independent-ja.pdf"
    source_pdf.write_bytes(b"independent source PDF fixture")
    target_pdf.write_bytes(b"independent target PDF fixture")
    before = (sha256_file(source_pdf), sha256_file(target_pdf))
    has_findings = scenario == "findings"
    source = _document("source/1", "Version 2 supports 10 MB.")
    target_number = "5" if has_findings else "10"
    target = _document("target/1", f"バージョン2は{target_number} MBを扱います。")
    settings = settings_factory(review_model="review")

    groups = align.run(source, target, tmp_path / "align")
    comparison = _comparison_document(source, target, groups)
    checks = check.run(comparison, None, tmp_path / "check")
    review_finding = Finding(
        kind="fluency",
        severity="warning",
        target_ids=["alignment/0"],
        message="日本語表現を確認してください",
        evidence="fixture evidence",
        suggestion="修正方針",
    )
    monkeypatch.setattr(
        review,
        "structured",
        lambda *_args, **_kwargs: review.ReviewResponse(
            findings=[review_finding] if has_findings else []
        ),
    )
    reviews = review.run(
        comparison,
        checks,
        "review rules",
        [],
        settings,
        tmp_path / "review",
    )
    output = tmp_path / "comparison.md"
    report.run(
        groups,
        [item for values in checks.values() for item in values],
        [item for values in reviews.values() for item in values],
        output,
        tmp_path / "report",
    )

    rendered = output.read_text(encoding="utf-8")
    stored = json.loads(
        (tmp_path / "report" / "review.json").read_text(encoding="utf-8")
    )
    if has_findings:
        assert stored["counts"] == {"error/number-unit": 1, "warning/fluency": 1}
        assert "error / number-unit" in rendered
        assert "warning / fluency" in rendered
    else:
        assert stored["counts"] == {}
        assert rendered.count("指摘なし") == 2
    assert (sha256_file(source_pdf), sha256_file(target_pdf)) == before
