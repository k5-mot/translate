"""Findingの単一schema契約を検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from translate.document import AlignmentGroup, Finding
from translate.tasks import check, report, review

if TYPE_CHECKING:
    from pathlib import Path


def test_legacy_finding_is_rejected() -> None:
    """旧category/source形式を誤って再利用できない。"""

    with pytest.raises(ValidationError):
        Finding.model_validate(
            {
                "category": "glossary",
                "severity": "critical",
                "message": "旧形式",
                "source": "term",
            }
        )


def test_finding_round_trip_across_check_review_and_report(tmp_path: Path) -> None:
    """CHECK/REVIEW/REPORTが同じFinding JSONを共有する。"""

    finding = check.deterministic_findings("Keep 10 MB.", "保持します。", [])[0]
    payload = finding.model_dump_json()
    reviewed = review.ReviewResponse.model_validate_json(
        json.dumps({"findings": [json.loads(payload)]})
    ).findings[0]
    output = tmp_path / "review.md"

    report.run(
        [AlignmentGroup(source_ids=["source/1"], target_ids=["target/1"])],
        [finding],
        [reviewed],
        output,
        tmp_path / ".workspace",
    )

    stored = json.loads(
        (tmp_path / ".workspace" / "review.json").read_text(encoding="utf-8")
    )
    assert Finding.model_validate(stored["findings"][0]) == finding
    assert stored["counts"] == {"error/number-unit": 2}
    assert "error / number-unit" in output.read_text(encoding="utf-8")
