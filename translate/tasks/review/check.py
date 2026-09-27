"""空訳と極端な長さ差だけを検出するCHECK Task。"""

from __future__ import annotations

import re

from translate.models.artifacts import CheckResult
from translate.models.document import Document, iter_text_units
from translate.models.review import Finding, ReviewTarget


def check(targets: list[ReviewTarget]) -> CheckResult:
    """正規化した原文と訳文へ固定閾値の検査を適用する。"""

    findings: list[Finding] = []
    for target in targets:
        source = _normalize(target.source)
        translation = _normalize(target.translation)
        category: str | None = None
        severity = "warning"
        message = ""
        if source and not translation:
            category = "empty_translation"
            severity = "error"
            message = "原文に対応する訳文が空です。"
        elif source and len(source) >= 80 and len(translation) < len(source) * 0.15:
            category = "extreme_short"
            message = "訳文が原文に比べて極端に短い可能性があります。"
        elif source and len(translation) >= 100 and len(translation) > len(source) * 5:
            category = "extreme_long"
            message = "訳文が原文に比べて極端に長い可能性があります。"
        if category is not None:
            findings.append(
                Finding(
                    id=f"check/{target.id}/{category}",
                    origin="check",
                    category=category,
                    severity=severity,
                    target_ids=target.target_ids,
                    message=message,
                )
            )
    return CheckResult(findings=findings)


def targets_from_document(document: Document) -> list[ReviewTarget]:
    """Translate後のDocument内IDからCHECKとREVIEWの対象を作る。"""

    return [
        ReviewTarget(
            id=f"translate/{unit.id}",
            source=unit.text("source"),
            translation=unit.text("revised"),
            target_ids=[unit.id],
            spans=unit.spans,
        )
        for _, unit in iter_text_units(document)
        if unit.text("source").strip()
    ]


def _normalize(value: str) -> str:
    """前後空白を除去し、連続空白を一つのspaceへ縮約する。"""

    return re.sub(r"\s+", " ", value.strip())
