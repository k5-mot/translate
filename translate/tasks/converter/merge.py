"""分割Docling JSONを参照整合性を保って結合するMERGE Task。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from translate.artifact_store import temporary_task_directory, write_json

if TYPE_CHECKING:
    from translate.models.artifacts import UnpackManifest

_COLLECTIONS = (
    "texts",
    "tables",
    "pictures",
    "key_value_items",
    "form_items",
    "groups",
)


def merge(
    manifest: UnpackManifest,
    source: Path,
    task_directory: Path,
    processing_directory: Path,
) -> Path:
    """part順にcollection、pageおよびassetを一つのDocling文書へ統合する。

    Args:
        manifest (UnpackManifest): 変換元Taskが生成したManifest。
        source (Path): 変換または検証対象の入力Source。
        task_directory (Path): 対象Taskの成果物Directory。
        processing_directory (Path): 対象処理の成果物Directory。

    Returns:
        Path: part順にcollection、pageおよびassetを一つのDocling文書へ統合する。

    Raises:
        ValueError: `Docling document must be an object`、`Docling pages must be an
            object`、`Docling produced no documents`、`Docling origin must be an
            object`のいずれかと判定した場合。
    """

    with temporary_task_directory(task_directory) as temporary:
        merged: dict[str, Any] | None = None
        page_offset = 0
        for part in sorted(manifest.parts, key=lambda item: item.number):
            input_path = processing_directory / Path(part.document.relative_path)
            value = json.loads(input_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Docling document must be an object")
            offsets = {name: len((merged or {}).get(name, [])) for name in _COLLECTIONS}
            part_name = f"part-{part.number:04d}"
            mapped = _remap(value, offsets, page_offset, part_name)
            pages = mapped.get("pages", {})
            if not isinstance(pages, dict):
                raise ValueError("Docling pages must be an object")
            mapped["pages"] = _mapped_pages(pages, page_offset)
            if merged is None:
                merged = mapped
            else:
                _append_document(merged, mapped)
            _copy_assets(
                input_path.parent / "artifacts", temporary / "assets" / part_name
            )
            page_offset += len(pages)
        if merged is None:
            raise ValueError("Docling produced no documents")
        merged["name"] = source.stem
        origin = merged.setdefault("origin", {})
        if not isinstance(origin, dict):
            raise ValueError("Docling origin must be an object")
        origin.update({"filename": source.name, "mimetype": "application/pdf"})
        _validate_references(merged)
        write_json(temporary / "document.json", merged)
    return task_directory / "document.json"


def _remap(value: Any, offsets: dict[str, int], page_offset: int, part: str) -> Any:
    """任意深度のDocling参照、page番号およびasset URIを全体namespaceへ移す。

    Args:
        value (Any): 文書全体のNamespaceへ参照を移すDocling要素。
        offsets (dict[str, int]): Part別のPage番号Offset。
        page_offset (int): 文書全体に合わせるPage番号Offset。
        part (str): 参照を書き換えるPart名。

    Returns:
        Any: 任意深度のDocling参照、page番号およびasset URIを全体namespaceへ移す。
    """

    if isinstance(value, list):
        return [_remap(item, offsets, page_offset, part) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        mapped = item
        if key in {"self_ref", "$ref"} and isinstance(mapped, str):
            pieces = mapped.removeprefix("#/").split("/")
            if len(pieces) == 2 and pieces[0] in offsets and pieces[1].isdigit():
                mapped = f"#/{pieces[0]}/{int(pieces[1]) + offsets[pieces[0]]}"
        elif key == "page_no" and isinstance(mapped, int):
            mapped += page_offset
        elif (
            key == "uri" and isinstance(mapped, str) and mapped.startswith("artifacts/")
        ):
            mapped = PurePosixPath(
                "assets",
                part,
                mapped.removeprefix("artifacts/"),
            ).as_posix()
        result[key] = _remap(mapped, offsets, page_offset, part)
    return result


def _mapped_pages(pages: dict[str, Any], page_offset: int) -> dict[str, Any]:
    """Docling pages objectのkeyを文書全体の連番へ変換する。

    Args:
        pages (dict[str, Any]): Page番号または参照別のPage Data。
        page_offset (int): 文書全体に合わせるPage番号Offset。

    Returns:
        dict[str, Any]: Docling pages objectのkeyを文書全体の連番へ変換する。

    Raises:
        ValueError: `f'invalid Docling page key: {key}'`、`f'duplicate mapped page:
            {mapped}'`のいずれかと判定した場合。
    """

    result: dict[str, Any] = {}
    for key, value in pages.items():
        if not str(key).isdigit():
            raise ValueError(f"invalid Docling page key: {key}")
        mapped = str(int(key) + page_offset)
        if mapped in result:
            raise ValueError(f"duplicate mapped page: {mapped}")
        result[mapped] = value
    return result


def _append_document(merged: dict[str, Any], mapped: dict[str, Any]) -> None:
    """collection、pageおよびdocument treeを既存結果へ追加する。

    Args:
        merged (dict[str, Any]): 統合先または統合済みのDocument要素。
        mapped (dict[str, Any]): 参照とPage番号を変換済みの要素。

    Raises:
        ValueError: `f'Docling collection must be a list: {name}'`、`Docling pages must be
            objects`、`mapped page IDs collide`、`f'Docling tree must be an object:
            {tree_name}'`、`f'Docling tree children must be a list:
            {tree_name}'`のいずれかと判定した場合。
    """

    for name in _COLLECTIONS:
        current = merged.setdefault(name, [])
        incoming = mapped.get(name, [])
        if not isinstance(current, list) or not isinstance(incoming, list):
            raise ValueError(f"Docling collection must be a list: {name}")
        current.extend(incoming)
    merged_pages = merged.setdefault("pages", {})
    incoming_pages = mapped.get("pages", {})
    if not isinstance(merged_pages, dict) or not isinstance(incoming_pages, dict):
        raise ValueError("Docling pages must be objects")
    if merged_pages.keys() & incoming_pages.keys():
        raise ValueError("mapped page IDs collide")
    merged_pages.update(incoming_pages)
    for tree_name in ("body", "furniture"):
        merged_tree = merged.setdefault(tree_name, {})
        incoming_tree = mapped.get(tree_name, {})
        if not isinstance(merged_tree, dict) or not isinstance(incoming_tree, dict):
            raise ValueError(f"Docling tree must be an object: {tree_name}")
        children = merged_tree.setdefault("children", [])
        incoming_children = incoming_tree.get("children", [])
        if not isinstance(children, list) or not isinstance(incoming_children, list):
            raise ValueError(f"Docling tree children must be a list: {tree_name}")
        children.extend(incoming_children)


def _copy_assets(source: Path, target: Path) -> None:
    """part専用namespaceへassetを複製し、既存衝突を拒否する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        target (Path): AssetをCopyする統合先Directory。

    Raises:
        ValueError: `f'asset namespace collision: {target.name}'`と判定した場合。
    """

    if not source.exists():
        return
    if target.exists():
        raise ValueError(f"asset namespace collision: {target.name}")
    shutil.copytree(source, target)


def _validate_references(document: dict[str, Any]) -> None:
    """collection参照が統合後の存在範囲内にあることを再帰検査する。

    Args:
        document (dict[str, Any]): 変換または検証対象のDocument。

    Raises:
        ValueError: `f'unresolved Docling reference: {reference}'`と判定した場合。
    """

    limits = {
        name: len(value)
        for name in _COLLECTIONS
        if isinstance((value := document.get(name, [])), list)
    }
    for reference in _iter_references(document):
        pieces = reference.removeprefix("#/").split("/")
        if (
            len(pieces) == 2
            and pieces[0] in limits
            and pieces[1].isdigit()
            and int(pieces[1]) >= limits[pieces[0]]
        ):
            raise ValueError(f"unresolved Docling reference: {reference}")


def _iter_references(value: Any) -> list[str]:
    """Docling JSON内のself_refと$refを再帰的に列挙する。

    Args:
        value (Any): 参照を再帰探索するDocling JSON要素。

    Returns:
        list[str]: Docling JSON内のself_refと$refを再帰的に列挙する。
    """

    if isinstance(value, list):
        return [reference for item in value for reference in _iter_references(item)]
    if not isinstance(value, dict):
        return []
    references = [
        item
        for key, item in value.items()
        if key in {"self_ref", "$ref"} and isinstance(item, str)
    ]
    return references + [
        reference for item in value.values() for reference in _iter_references(item)
    ]
