"""Findingの単一schema契約を検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from translate_v1.document import AlignmentGroup, Finding
from translate_v1.tasks import check, report, review

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


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("U.S.", "米国"),
        ("U.K.", "英国"),
        ("U.S.A.", "アメリカ合衆国"),
        ("Microsoft", "マイクロソフト"),
        ("camelCase", "キャメルケース"),
        ("some_identifier", "識別子"),
    ],
)
def test_natural_names_and_abbreviations_are_not_literal_findings(
    source: str, target: str
) -> None:
    """名前や識別子の形だけを根拠に自然な訳を誤指摘しない。"""

    assert check.literal_references(source) == []
    assert check.deterministic_findings(source, target, []) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("See manual.pdf.", ["manual.pdf"]),
        ("Open MANUAL.DOCX, please.", ["MANUAL.DOCX"]),
        ("(https://example.com/manual.pdf).", ["https://example.com/manual.pdf"]),
        ("www.example.com;", ["www.example.com"]),
        ("See manual.unknown and U.S.A.", []),
    ],
)
def test_explicit_references_only_produce_advisory_findings(
    source: str, expected: list[str]
) -> None:
    """既知拡張子と明示URLだけを対象とし、句読点を根拠へ混ぜない。"""

    assert check.literal_references(source) == expected
    findings = check.deterministic_findings(source, "参照してください。", [])
    assert [item.evidence for item in findings] == expected
    assert all(item.severity == "warning" for item in findings)
    assert all(item.kind == "literal-reference" for item in findings)


def test_existing_semantic_checks_keep_their_severity() -> None:
    """数値・単位・否定・条件・比較・用語集の検査を弱めない。"""

    findings = check.deterministic_findings(
        "If value is not higher than 10 MB, use cache.",
        "値を使います。",
        [check.GlossaryEntry(source="cache", target="キャッシュ")],
    )
    assert {item.kind for item in findings} >= {
        "number-unit",
        "negation",
        "condition",
        "comparison",
        "glossary",
    }
    assert all(item.severity == "error" for item in findings)


@pytest.mark.parametrize("target", ["訳文", "指定訳を使用する"])
@pytest.mark.parametrize(
    ("source", "term", "applicable"),
    [
        ("Capital", "API", False),
        ("APIs", "API", False),
        ("API_key", "API", False),
        ("myAPI", "API", False),
        ("API", "API", True),
        ("api", "API", True),
        ("(API)", "API", True),
        ("Use API, please.", "API", True),
        ("Asset Management", "asset management", True),
        ("Asset  Management", "asset management", True),
        ("Asset\nManagement", "asset management", True),
        ("Asset Managements", "asset management", False),
        ("Use C++.", "C++", True),
        ("Use Cxx.", "C++", False),
        ("(A.B)", "A.B", True),
        ("AxB", "A.B", False),
    ],
)
def test_glossary_findings_share_source_selection_boundaries(
    source: str, term: str, target: str, *, applicable: bool
) -> None:
    """選択とCHECKが語境界・空白・句読点で一致し、真の指定訳欠落だけを返す。"""

    entry = check.GlossaryEntry(source=term, target="指定訳")
    assert check.matching_glossary(source, [entry]) == ([entry] if applicable else [])
    findings = [
        item
        for item in check.deterministic_findings(source, target, [entry])
        if item.kind == "glossary"
    ]
    expected = (
        [
            Finding(
                kind="glossary",
                severity="error",
                message=f"指定訳が使われていない: {term} → 指定訳",
                evidence=term,
                suggestion="指定訳",
            ),
        ]
        if applicable and "指定訳" not in target
        else []
    )
    assert findings == expected


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
