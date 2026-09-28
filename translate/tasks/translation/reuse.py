"""Upgradeで互換な日本語v1 Spanだけを英文v2へ移植する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.artifact_store import write_model
from translate.models.document import Document, TextSpan, text_unit_index
from translate.models.upgrade import ReuseReport, UpgradePlan

if TYPE_CHECKING:
    from pathlib import Path


def reuse(
    source_v2: Document,
    translation_v1: Document,
    plan: UpgradePlan,
    task_directory: Path,
) -> tuple[Document, ReuseReport]:
    """Planでreuseと確定した日本語Spanをv2 Documentへ設定する。"""

    updated = source_v2.model_copy(deep=True)
    target_units = text_unit_index(updated)
    translated_units = text_unit_index(translation_v1)
    reused_ids: list[str] = []
    translation_ids: list[str] = []
    for change in plan.changes:
        if change.action == "translate":
            translation_ids.extend(change.source_v2_ids)
            continue
        if change.action != "reuse":
            continue
        if len(change.source_v2_ids) != 1 or len(change.translation_v1_ids) != 1:
            raise ValueError(f"invalid reuse mapping: {change.id}")
        target = target_units[change.source_v2_ids[0]]
        translated = translated_units[change.translation_v1_ids[0]]
        target_spans = _translatable_spans(target.spans)
        translated_spans = _translatable_spans(translated.spans)
        if len(target_spans) != len(translated_spans):
            raise ValueError(f"incompatible reuse mapping: {change.id}")
        for target_span, translated_span in zip(
            target_spans, translated_spans, strict=True
        ):
            target_span.translated = translated_span.source
        reused_ids.append(target.id)
    report = ReuseReport(
        reused_unit_ids=reused_ids,
        translation_target_ids=translation_ids,
    )
    write_model(task_directory / "document.json", updated)
    write_model(task_directory / "report.json", report)
    return updated, report


def previous_context(
    plan: UpgradePlan,
    source_v1: Document,
    source_v2: Document,
    translation_v1: Document,
) -> dict[str, tuple[str, str]]:
    """modified対象Spanへ対応する旧英日TextUnitを関連付ける。"""

    old_units = text_unit_index(source_v1)
    new_units = text_unit_index(source_v2)
    translated_units = text_unit_index(translation_v1)
    result: dict[str, tuple[str, str]] = {}
    for change in plan.changes:
        if (
            change.kind != "modified"
            or len(change.source_v1_ids) != 1
            or len(change.source_v2_ids) != 1
            or len(change.translation_v1_ids) != 1
        ):
            continue
        old = old_units[change.source_v1_ids[0]].text("source")
        translated = translated_units[change.translation_v1_ids[0]].text("source")
        for span in _translatable_spans(new_units[change.source_v2_ids[0]].spans):
            result[span.id] = (old, translated)
    return result


def _translatable_spans(spans: list[TextSpan]) -> list[TextSpan]:
    """codeと改行以外の翻訳対象Spanを返す。"""

    return [span for span in spans if span.kind not in {"code", "line_break"}]
