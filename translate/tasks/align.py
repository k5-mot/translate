"""ALIGN: 独立した英日文書のBlockを対応付ける。"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from translate.adapters.llm import structured
from translate.common.workspace import atomic_directory, atomic_write_json
from translate.document import AlignmentGroup, Document, inline_text
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.settings import Settings

ANCHOR_RE = re.compile(r"https?://\S+|\b\d+(?:\.\d+)*\b")
LOGGER = logging.getLogger(__name__)


class AlignmentResponse(BaseModel):
    """LLM fallbackの多対多対応。"""

    groups: list[AlignmentGroup] = Field(default_factory=list)


def _items(document: Document) -> list[tuple[str, str]]:
    return [
        (block.id, inline_text(block.source))
        for page in document.pages
        for block in page.blocks
        if inline_text(block.source).strip()
    ]


def _valid(
    groups: list[AlignmentGroup], source_ids: set[str], target_ids: set[str]
) -> bool:
    actual_source = [item for group in groups for item in group.source_ids]
    actual_target = [item for group in groups for item in group.target_ids]
    return (
        len(actual_source) == len(set(actual_source))
        and len(actual_target) == len(set(actual_target))
        and set(actual_source) == source_ids
        and set(actual_target) == target_ids
    )


class AlignTask(BaseTask):
    """Execute ALIGN while sharing elapsed-time measurement only."""

    name = "ALIGN"

    def run(
        self,
        source: Document,
        target: Document,
        output_dir: Path,
        settings: Settings | None = None,
    ) -> list[AlignmentGroup]:
        """番号・URLと文書順を使い、全Blockを重複なく対応付ける。"""

        with self.measure():
            source_items = _items(source)
            target_items = _items(target)
            groups: list[AlignmentGroup] = []
            used_targets: set[int] = set()
            cursor = 0
            for source_id, source_text in source_items:
                anchors = set(ANCHOR_RE.findall(source_text))
                candidates = [
                    index
                    for index, (_, text) in enumerate(target_items)
                    if index not in used_targets
                    and anchors
                    and anchors <= set(ANCHOR_RE.findall(text))
                ]
                # Note 1: Explicit numbers and URLs are stronger anchors than cross-language text.
                index = (
                    min(candidates, key=lambda value: abs(value - cursor))
                    if candidates
                    else None
                )
                if index is None:
                    # Note 2: Document order is the deterministic fallback for unanchored prose.
                    index = next(
                        (
                            value
                            for value in range(cursor, len(target_items))
                            if value not in used_targets
                        ),
                        None,
                    )
                if index is None:
                    groups.append(
                        AlignmentGroup(
                            source_ids=[source_id], kind="source_only", confidence=1.0
                        )
                    )
                    continue
                target_id = target_items[index][0]
                groups.append(
                    AlignmentGroup(
                        source_ids=[source_id],
                        target_ids=[target_id],
                        confidence=0.95 if index in candidates else 0.6,
                    )
                )
                used_targets.add(index)
                cursor = index + 1
            groups.extend(
                AlignmentGroup(
                    target_ids=[target_id], kind="target_only", confidence=1.0
                )
                for index, (target_id, _) in enumerate(target_items)
                if index not in used_targets
            )
            # Note 3: Low-confidence order matches are the only records sent to the model.
            if settings is not None and any(group.confidence < 0.8 for group in groups):
                try:
                    response = structured(
                        settings,
                        settings.structure_model or "",
                        AlignmentResponse,
                        (
                            "英語と日本語のblockを1対1、1対多、多対1で対応付ける。"
                            "全IDを重複なく一度だけ出力し、未対応はsource_only/target_onlyにする。"
                        ),
                        json.dumps(
                            {"source": source_items, "target": target_items},
                            ensure_ascii=False,
                        ),
                        reasoning="low",
                    )
                    source_ids = {item[0] for item in source_items}
                    target_ids = {item[0] for item in target_items}
                    if _valid(response.groups, source_ids, target_ids):
                        groups = response.groups
                except Exception:  # noqa: BLE001
                    # Note 4: Deterministic order alignment remains usable if the model fails.
                    LOGGER.warning(
                        "ALIGN model fallback failed; using deterministic order"
                    )
            with atomic_directory(output_dir) as temporary:
                atomic_write_json(
                    temporary / "alignment.json", [item.model_dump() for item in groups]
                )
            return groups


def run(
    source: Document,
    target: Document,
    output_dir: Path,
    settings: Settings | None = None,
) -> list[AlignmentGroup]:
    """Existing function delegates to the typed AlignTask operation."""

    return AlignTask().run(source, target, output_dir, settings)
