"""比較Review結果を利用者向けMarkdownへ変換するREPORT Task。"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from translate.artifact_store import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from translate.models.artifacts import AlignmentResult, CheckResult, ReviewResult


def create_report(
    alignment: AlignmentResult,
    checked: CheckResult,
    reviewed: ReviewResult,
    output: Path,
) -> Path:
    """件数、対応、指摘、修正候補の順にReview Reportを保存する。"""

    findings = [*checked.findings, *reviewed.findings]
    counts = Counter((finding.severity, finding.category) for finding in findings)
    lines = ["# 翻訳レビュー", "", "## 件数", ""]
    lines.extend(
        [
            *(
                f"- {severity} / {category}: {count}"
                for (severity, category), count in sorted(counts.items())
            ),
        ]
        or ["なし"]
    )
    lines.extend(["", "## Alignment", ""])
    lines.extend(
        f"- {group.id}: {group.kind} ({group.method}) source={', '.join(group.source_ids) or '-'} translation={', '.join(group.translation_ids) or '-'}"
        for group in alignment.groups
    )
    if not alignment.groups:
        lines.append("なし")
    lines.extend(["", "## Finding", ""])
    lines.extend(
        f"- [{finding.severity}] {finding.id} ({finding.category}): {finding.message}"
        for finding in findings
    )
    if not findings:
        lines.append("なし")
    lines.extend(["", "## 修正候補", ""])
    target_map = {target.id: target for target in alignment.targets}
    for revision in reviewed.revisions:
        target = next(
            (
                target
                for target in target_map.values()
                if revision.target_id in target.target_ids
            ),
            None,
        )
        current = target.translation if target is not None else "不明"
        proposal = " / ".join(edit.text for edit in revision.edits)
        lines.append(
            f"- {revision.id}: 対象={revision.target_id}; 現在訳={current}; 提案訳={proposal}"
        )
    if not reviewed.revisions:
        lines.append("なし")
    atomic_write_text(output, "\n".join(lines).rstrip() + "\n")
    return output
