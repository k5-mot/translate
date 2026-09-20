"""REPORT: 比較Reviewの結果をMarkdownとJSONへ直列化する。"""

from __future__ import annotations

import time
from collections import Counter
from typing import TYPE_CHECKING

from translate.common.workspace import atomic_write_json, atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from translate.document import AlignmentGroup, Finding


def run(
    groups: list[AlignmentGroup],
    checks: list[Finding],
    reviews: list[Finding],
    output: Path,
    work_dir: Path,
) -> Path:
    """対応、欠落候補、Finding集計を公開reportへ保存する。"""

    start = time.perf_counter()
    findings = [*checks, *reviews]
    counts = Counter(f"{item.severity}/{item.kind}" for item in findings)
    lines = ["# 翻訳レビュー", "", "## 集計", ""]
    lines.extend(f"- {key}: {value}" for key, value in sorted(counts.items()))
    if not counts:
        lines.append("- 指摘なし")
    lines.extend(["", "## 対応", ""])
    lines.extend(
        (
            f"- `{group.kind}` source={', '.join(group.source_ids) or '-'} "
            f"target={', '.join(group.target_ids) or '-'} "
            f"confidence={group.confidence:.2f}"
        )
        for group in groups
    )
    lines.extend(["", "## 指摘", ""])
    lines.extend(
        (f"- **{finding.severity} / {finding.kind}**: {finding.message}")
        for finding in findings
    )
    if not findings:
        lines.append("- 指摘なし")
    atomic_write_text(output, "\n".join(lines) + "\n")
    atomic_write_json(
        work_dir / "review.json",
        {
            "counts": dict(counts),
            "alignment": [item.model_dump() for item in groups],
            "findings": [item.model_dump() for item in findings],
        },
    )
    end = time.perf_counter()
    print(f"[TIME] REPORT page=- group=-: {end - start:.3f} s")  # noqa: T201
    return output
