"""MERGE: 分割Docling JSONを参照整合性を保って結合する。"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any

from translate.common.workspace import atomic_directory, atomic_write_json

COLLECTIONS = ("texts", "tables", "pictures", "key_value_items", "form_items", "groups")


def _remap(value: Any, offsets: dict[str, int], page_offset: int, part: str) -> Any:
    """Docling参照を再帰的に一文書のnamespaceへ移す。"""

    # Note 1: References can appear at any nesting depth, including table children.
    if isinstance(value, list):
        return [_remap(item, offsets, page_offset, part) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        mapped_item = item
        # Note 2: Collection indexes restart at zero in every split PDF.
        if key in {"self_ref", "$ref"} and isinstance(mapped_item, str):
            pieces = mapped_item.removeprefix("#/").split("/")
            if len(pieces) == 2 and pieces[0] in offsets and pieces[1].isdigit():
                mapped_item = f"#/{pieces[0]}/{int(pieces[1]) + offsets[pieces[0]]}"
        # Note 3: Page numbers also restart in every Docling response.
        elif key == "page_no" and isinstance(mapped_item, int):
            mapped_item += page_offset
        # Note 4: Prefix assets by part so identical filenames cannot overwrite.
        elif (
            key == "uri"
            and isinstance(mapped_item, str)
            and mapped_item.startswith("artifacts/")
        ):
            mapped_item = PurePosixPath(
                "assets", part, mapped_item.removeprefix("artifacts/")
            ).as_posix()
        result[key] = _remap(mapped_item, offsets, page_offset, part)
    return result


def _run_into(documents: list[Path], source: Path, output_dir: Path) -> Path:
    """part JSONとassetを一文書へ結合する。"""

    start = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    merged: dict[str, Any] | None = None
    page_offset = 0
    for number, path in enumerate(documents, 1):
        value = json.loads(path.read_text(encoding="utf-8"))
        offsets = {name: len((merged or {}).get(name, [])) for name in COLLECTIONS}
        part_name = f"part-{number:04d}"
        mapped = _remap(value, offsets, page_offset, part_name)
        pages = mapped.get("pages", {})
        mapped["pages"] = {
            str(int(key) + page_offset): item for key, item in pages.items()
        }
        if merged is None:
            merged = mapped
        else:
            for name in COLLECTIONS:
                merged.setdefault(name, []).extend(mapped.get(name, []))
            merged.setdefault("pages", {}).update(mapped["pages"])
            for tree in ("body", "furniture"):
                merged.setdefault(tree, {}).setdefault("children", []).extend(
                    mapped.get(tree, {}).get("children", [])
                )
        artifacts = path.parent / "artifacts"
        if artifacts.exists():
            shutil.copytree(
                artifacts, output_dir / "assets" / part_name, dirs_exist_ok=True
            )
        page_offset += len(pages)
    if merged is None:
        msg = "Docling produced no documents"
        raise ValueError(msg)
    merged["name"] = source.stem
    merged.setdefault("origin", {}).update(
        {"filename": source.name, "mimetype": "application/pdf"}
    )
    result = output_dir / "document.json"
    atomic_write_json(result, merged)
    end = time.perf_counter()
    print(f"[TIME] MERGE page=- group=-: {end - start:.3f} s")  # noqa: T201
    return result


def run(documents: list[Path], source: Path, output_dir: Path) -> Path:
    """Task directory全体を検証後に公開する。"""

    with atomic_directory(output_dir) as temporary:
        _run_into(documents, source, temporary)
    return output_dir / "document.json"
