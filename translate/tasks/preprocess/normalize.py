"""NORMALIZE: 不要要素除外と決定的text cleanupを行う。"""

from __future__ import annotations

import copy
import json
import re
from typing import TYPE_CHECKING, Any

from translate.artifact_store import temporary_task_directory, write_json

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
    """非code本文の制御文字・連続記号・空白を整えるための決定的なtext補正を行う。

    Args:
        value (str): 決定的な補正を適用する本文Text。

    Returns:
        str: 非code本文の制御文字・連続記号・空白を整えるための決定的なtext補正を行う。
    """

    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    value = re.sub(r"\.{3,}", "...", value)
    value = re.sub(r"・{3,}", "・・・", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _refs(value: Any) -> set[str]:
    """任意のDocling subtreeに含まれる参照を再帰的に集める。

    Args:
        value (Any): 参照を再帰探索するDocling Subtree。

    Returns:
        set[str]: 任意のDocling subtreeに含まれる参照を再帰的に集める。
    """

    if isinstance(value, list):
        return set().union(*(_refs(item) for item in value), set())
    if not isinstance(value, dict):
        return set()
    result = {value["$ref"]} if isinstance(value.get("$ref"), str) else set()
    return result | set().union(*(_refs(item) for item in value.values()), set())


def _page(item: dict[str, Any]) -> int | None:
    """先頭の出典情報に整数のページ番号がある場合だけ返し、目次ページの識別に使う。

    Args:
        item (dict[str, Any]): 変換または位置計算対象の要素Data。

    Returns:
        int | None: 先頭の出典情報に整数のページ番号がある場合だけ返し、目次ページの識別に使う。
    """

    provenance = item.get("prov")
    if isinstance(provenance, list) and provenance and isinstance(provenance[0], dict):
        value = provenance[0].get("page_no")
        return value if isinstance(value, int) else None
    return None


def index_only_pages(document: dict[str, Any]) -> set[int]:
    """目次見出しがあり、長い本文段落を含まないページだけを返す。"""

    markers = {
        page
        for item in document.get("texts", [])
        if isinstance(item, dict)
        and (
            item.get("label") == "document_index"
            or (
                item.get("label") in {"title", "section_header", "heading", "header"}
                and INDEX_RE.fullmatch(str(item.get("text", "")).strip())
            )
        )
        if (page := _page(item)) is not None
    }
    # ponytail: 120字未満の本文が目次見出しと同居すると除外され得る。必要なら配置情報で判別する。
    prose = {
        page
        for item in document.get("texts", [])
        if isinstance(item, dict)
        and item.get("label") == "text"
        and len(str(item.get("text", "")).strip()) >= 120
        if (page := _page(item)) is not None
    }
    return markers - prose


def _filter_tree(document: dict[str, Any], node: Any, removed: set[str]) -> None:
    """除外対象への子参照を文書treeから取り除き、解決できる残りの参照先にも再帰適用する。

    Args:
        document (dict[str, Any]): 変換または検証対象のDocument。
        node (Any): 再帰的に走査または並べ替えるNode。
        removed (set[str]): 除外したNode参照を収集する集合。
    """

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


def normalize(source: Path, output_dir: Path) -> Path:
    """不要要素を参照treeから除き、非code本文をcleanする。

    Args:
        source (Path): 変換または検証対象の入力Source。
        output_dir (Path): Task成果物の出力Directory。

    Returns:
        Path: 不要要素を参照treeから除き、非code本文をcleanする。
    """

    document = copy.deepcopy(json.loads(source.read_text(encoding="utf-8")))
    removed_reasons: dict[str, str] = {}
    changed: list[str] = []
    picture_owned = set().union(
        *(_refs(item.get("children", [])) for item in document.get("pictures", [])),
        set(),
    )
    index_pages = index_only_pages(document)
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
            elif (
                collection == "texts"
                and item.get("label")
                in {"title", "section_header", "heading", "header"}
                and INDEX_RE.fullmatch(text.strip())
            ):
                reason = "document_index_title"
            elif ref in picture_owned:
                reason = "picture_owned_text"
            elif collection == "texts" and not text.strip():
                reason = "empty_text"
            if reason is not None:
                removed_reasons[ref] = reason
                continue
            if item.get("label") not in CODE and isinstance(item.get("text"), str):
                cleaned = _clean(item["text"])
                if cleaned != item["text"]:
                    item["text"] = cleaned
                    changed.append(ref)
    _filter_tree(document, document.get("body", {}), set(removed_reasons))
    with temporary_task_directory(output_dir) as temporary:
        write_json(temporary / "document.json", document)
        write_json(
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
