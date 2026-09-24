"""NORMALIZE: 不要要素除外と決定的text cleanupを行う。"""

from __future__ import annotations

import copy
import json
import re
from typing import TYPE_CHECKING, Any

from translate.common.workspace import atomic_directory, atomic_write_json
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

SKIPPED = {"page_header", "page_footer", "document_index"}
INDEX_RE = re.compile(
    r"^(?:table of contents|contents|list of figures|list of tables|目次|図目次|表目次)$",
    re.IGNORECASE,
)
CODE = {"code", "program_listing"}


def _clean(value: str) -> str:
    # Note 1: Cleanup is deterministic; semantic corrections belong to STRUCTURE.
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    value = re.sub(r"\.{3,}", "...", value)
    value = re.sub(r"・{3,}", "・・・", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _refs(value: Any) -> set[str]:
    """任意のDocling subtreeに含まれる参照を再帰的に集める。"""

    if isinstance(value, list):
        return set().union(*(_refs(item) for item in value), set())
    if not isinstance(value, dict):
        return set()
    result = {value["$ref"]} if isinstance(value.get("$ref"), str) else set()
    return result | set().union(*(_refs(item) for item in value.values()), set())


def _page(item: dict[str, Any]) -> int | None:
    provenance = item.get("prov")
    if isinstance(provenance, list) and provenance and isinstance(provenance[0], dict):
        value = provenance[0].get("page_no")
        return value if isinstance(value, int) else None
    return None


def _filter_tree(document: dict[str, Any], node: Any, removed: set[str]) -> None:
    if not isinstance(node, dict):
        return
    children = node.get("children")
    if not isinstance(children, list):
        return
    kept: list[Any] = []
    for child in children:
        ref = child.get("$ref") if isinstance(child, dict) else None
        if isinstance(ref, str) and ref in removed:
            continue
        kept.append(child)
    node["children"] = kept
    for child in kept:
        ref = child.get("$ref") if isinstance(child, dict) else None
        if not isinstance(ref, str):
            continue
        value: Any = document
        try:
            for part in ref.removeprefix("#/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        _filter_tree(document, value, removed)


class NormalizeTask(BaseTask):
    """Execute NORMALIZE while sharing elapsed-time measurement only."""

    name = "NORMALIZE"

    def run(self, source: Path, output_dir: Path) -> Path:
        """不要要素を参照treeから除き、非code本文をcleanする。"""

        with self.measure():
            document = copy.deepcopy(json.loads(source.read_text(encoding="utf-8")))
            removed_reasons: dict[str, str] = {}
            changed: list[str] = []
            # Note 3: Picture child text is metadata/caption content, not duplicate body prose.
            picture_owned = set().union(
                *(
                    _refs(item.get("children", []))
                    for item in document.get("pictures", [])
                ),
                set(),
            )
            index_pages = {
                page
                for item in document.get("texts", [])
                if isinstance(item, dict)
                and (
                    item.get("label") == "document_index"
                    or INDEX_RE.fullmatch(str(item.get("text", "")).strip())
                )
                if (page := _page(item)) is not None
            }
            for collection in ("texts", "tables", "pictures"):
                for index, item in enumerate(document.get(collection, [])):
                    if not isinstance(item, dict):
                        continue
                    ref = str(item.get("self_ref", f"#/{collection}/{index}"))
                    text = str(item.get("text", ""))
                    reason = None
                    if item.get("label") in SKIPPED:
                        reason = str(item.get("label"))
                    elif _page(item) in index_pages:
                        reason = "document_index_page"
                    elif ref in picture_owned:
                        reason = "picture_owned_text"
                    elif collection == "texts" and not text.strip():
                        reason = "empty_text"
                    if reason is not None:
                        removed_reasons[ref] = reason
                        continue
                    # Note 2: Never normalize literal code where punctuation is meaningful.
                    if item.get("label") not in CODE and isinstance(
                        item.get("text"), str
                    ):
                        cleaned = _clean(item["text"])
                        if cleaned != item["text"]:
                            item["text"] = cleaned
                            changed.append(ref)
            _filter_tree(document, document.get("body", {}), set(removed_reasons))
            with atomic_directory(output_dir) as temporary:
                atomic_write_json(temporary / "document.json", document)
                atomic_write_json(
                    temporary / "report.json",
                    {
                        "removed": [
                            {"id": ref, "reason": reason}
                            for ref, reason in sorted(removed_reasons.items())
                        ],
                        "cleaned": changed,
                    },
                )
            return output_dir / "document.json"


def run(source: Path, output_dir: Path) -> Path:
    """Existing function delegates to the typed NormalizeTask operation."""

    return NormalizeTask().run(source, output_dir)
