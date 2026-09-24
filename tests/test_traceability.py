"""OpenSpec Requirement/ScenarioとTest IDの対応表を検証する。"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHANGE_ROOT = PROJECT_ROOT / "openspec" / "changes"
ARCHIVE_ROOT = CHANGE_ROOT / "archive"


def test_all_capability_scenarios_have_existing_test_ids() -> None:
    """初期archiveの要求・Scenario数と対応表の連番、参照するTest名の存在を検査する。"""

    specification_paths = sorted(
        ARCHIVE_ROOT.glob("*-establish-translate-ja-contracts/specs/*/spec.md")
    )
    assert len(specification_paths) == 5
    specifications = "\n".join(
        path.read_text(encoding="utf-8") for path in specification_paths
    )
    verification_paths = sorted(
        ARCHIVE_ROOT.glob(
            "*-resolve-translate-contract-verification-gaps/verification.md"
        )
    )
    assert len(verification_paths) == 1
    verification = verification_paths[0].read_text(encoding="utf-8")

    assert specifications.count("### Requirement:") == 30
    assert specifications.count("#### Scenario:") == 48
    rows = re.findall(r"^\| (\d+) \|.*$", verification, flags=re.MULTILINE)
    assert [int(value) for value in rows] == list(range(1, 49))
    assert "未対応0、未実行0" in verification

    test_ids = re.findall(r"`(tests/[^`]+)`", verification)
    assert test_ids
    for test_id in test_ids:
        path_text, separator, name = test_id.partition("::")
        path = PROJECT_ROOT / path_text
        assert path.is_file(), test_id
        if separator and path.suffix == ".py":
            function = name.partition("[")[0]
            source = path.read_text(encoding="utf-8")
            pattern = rf"^def {re.escape(function)}\("
            assert re.search(pattern, source, re.MULTILINE), test_id
