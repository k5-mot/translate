"""Tests for the checked-in OpenCode permission policy."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_opencode_policy_allows_inspection_and_denies_destructive_git() -> None:
    """Allow inspection while denying destructive Git commands."""
    policy = json.loads((ROOT / "opencode.jsonc").read_text(encoding="utf-8"))
    rules = {
        (item["action"], item["resource"]): item["effect"]
        for item in policy["permissions"]
    }

    assert rules[("shell", "git status *")] == "allow"
    assert rules[("shell", "git clean *")] == "deny"
    assert rules[("shell", "git reset --hard *")] == "deny"
