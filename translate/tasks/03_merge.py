"""分割Docling JSONをdocling-coreで結合するMERGE Task。"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from docling_core.types.doc import DoclingDocument

from translate.adapters.artifact_store import temporary_task_directory, write_json
from translate.models.artifacts import UnpackManifest


def merge(
    manifest: UnpackManifest,
    source: Path,
    task_directory: Path,
    processing_directory: Path,
) -> Path:
    """part順にcollection、pageおよびassetを一つのDocling文書へ統合する。

    参照とページ番号の振り直しは`DoclingDocument.concatenate`へ委ね、
    assetのpart別名前空間だけをここで与える。

    Args:
        manifest (UnpackManifest): 変換元Taskが生成したManifest。
        source (Path): 変換または検証対象の入力Source。
        task_directory (Path): 対象Taskの成果物Directory。
        processing_directory (Path): 対象処理の成果物Directory。

    Returns:
        Path: 統合したDocling JSONのPath。

    Raises:
        ValueError: 入力がDoclingDocumentとして不正、またはpartがない場合。
    """

    with temporary_task_directory(task_directory) as temporary:
        parts: list[DoclingDocument] = []
        for part in sorted(manifest.parts, key=lambda item: item.number):
            input_path = processing_directory / Path(part.document.relative_path)
            value = json.loads(input_path.read_text(encoding="utf-8"))
            part_name = f"part-{part.number:04d}"
            _namespace_assets(value, part_name)
            parts.append(DoclingDocument.model_validate(value))
            artifacts = input_path.parent / "artifacts"
            if artifacts.exists():
                shutil.copytree(artifacts, temporary / "assets" / part_name)
        if not parts:
            raise ValueError("Docling produced no documents")
        merged = DoclingDocument.concatenate(parts).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        merged["name"] = source.stem
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        # 結合でpart別のoriginが落ちるため、Doclingと同じ形式で原本の値を入れる。
        merged.setdefault("origin", {}).update(
            {
                "filename": source.name,
                "mimetype": "application/pdf",
                "binary_hash": int(digest, 16) % 2**64,
            }
        )
        _normalize_asset_paths(merged)
        write_json(temporary / "document.json", merged, atomic=False)
    return task_directory / "document.json"


def _namespace_assets(document: dict[str, Any], part: str) -> None:
    """picture画像のURIをpart別の公開先へ書き換える。

    Args:
        document: 検証前のDocling JSON。
        part: asset名前空間に使うPart名。
    """

    for picture in document.get("pictures", []):
        image = picture.get("image")
        uri = image.get("uri") if isinstance(image, dict) else None
        if isinstance(uri, str) and uri.startswith("artifacts/"):
            image["uri"] = f"assets/{part}/{uri.removeprefix('artifacts/')}"


def _normalize_asset_paths(document: dict[str, Any]) -> None:
    """Windowsの`Path`直列化で混ざる区切り文字をPOSIX形式へ戻す。

    Args:
        document: 直列化後のDocling JSON。
    """

    for picture in document.get("pictures", []):
        image = picture.get("image")
        if isinstance(image, dict) and isinstance(image.get("uri"), str):
            image["uri"] = image["uri"].replace("\\", "/")
