"""REPORT: 比較Reviewの結果をMarkdownとJSONへ直列化する。"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from translate.common.workspace import atomic_write_json, atomic_write_text
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

    from translate.document import AlignmentGroup, Finding


def _literal(value: str | None) -> str:
    """自由文をMarkdown構文にせず表示し、未記載と空文字を区別する。"""

    if value is None:
        return "未記載\n"
    if value == "":
        return "空文字\n"
    # 本文がfenceを閉じないよう、既存code描画と同じ長さ選択を使う。
    longest = max((len(item) for item in re.findall(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{value}\n{fence}\n"


def _finding_lines(finding: Finding, group_ids: set[str]) -> list[str]:
    """Finding全項目を保持し、未指定/未知の対象に対応関係を捏造しない。"""

    lines = [
        "重大度 / 種別",
        "",
        _literal(f"{finding.severity} / {finding.kind}"),
        "メッセージ",
        "",
        _literal(finding.message),
    ]
    if not finding.target_ids:
        lines.extend(["対象ID", "", "対象未指定", ""])
    for target_id in finding.target_ids:
        label = "対象ID" if target_id in group_ids else "対象ID (対応情報なし)"
        lines.extend([label, "", _literal(target_id)])
    lines.extend(
        [
            "根拠",
            "",
            _literal(finding.evidence),
            "修正方針",
            "",
            _literal(finding.suggestion),
        ]
    )
    return lines


class ReportTask(BaseTask):
    """Execute REPORT while sharing elapsed-time measurement only."""

    name = "REPORT"

    def run(
        self,
        groups: list[AlignmentGroup],
        checks: list[Finding],
        reviews: list[Finding],
        output: Path,
        work_dir: Path,
    ) -> Path:
        """対応、欠落候補、Finding集計を公開reportへ保存する。"""

        with self.measure():
            # REVIEW forwards advisory references; count the original CHECK warning once.
            findings = [
                *checks,
                *(
                    item
                    for item in reviews
                    if item.kind != "literal-reference" or item not in checks
                ),
            ]
            counts = Counter(f"{item.severity}/{item.kind}" for item in findings)
            lines = ["# 翻訳レビュー", "", "## 集計", ""]
            lines.extend(
                _literal(f"{key}: {value}") for key, value in sorted(counts.items())
            )
            if not counts:
                lines.append("- 指摘なし")
            lines.extend(["", "## 対応", ""])
            # 比較Documentが既に使用するIDを列挙するだけで、別のID台帳は保存しない。
            group_ids = {f"alignment/{index}" for index in range(len(groups))}
            for index, group in enumerate(groups):
                lines.extend(
                    [
                        f"### alignment/{index}",
                        "",
                        f"種別: {group.kind} / confidence={group.confidence:.2f}",
                        "",
                        "原文ID",
                        "",
                        *(_literal(value) for value in group.source_ids),
                        *([] if group.source_ids else ["対応なし", ""]),
                        "訳文ID",
                        "",
                        *(_literal(value) for value in group.target_ids),
                        *([] if group.target_ids else ["対応なし", ""]),
                    ]
                )
            lines.extend(["", "## 指摘", ""])
            for index, finding in enumerate(findings, start=1):
                lines.extend(
                    [f"### 指摘 {index}", "", *_finding_lines(finding, group_ids)]
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
            return output


def run(
    groups: list[AlignmentGroup],
    checks: list[Finding],
    reviews: list[Finding],
    output: Path,
    work_dir: Path,
) -> Path:
    """Existing function delegates to the typed ReportTask operation."""

    return ReportTask().run(groups, checks, reviews, output, work_dir)
