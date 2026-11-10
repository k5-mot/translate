"""MERGEがpart文書の参照、ページおよびassetを統合することを検証する。"""

import hashlib
import json
from importlib import import_module
from pathlib import Path

from docling_core.types.doc import DoclingDocument

from translate.models.artifacts import ArtifactFile, UnpackedPart, UnpackManifest

merge = import_module("translate.tasks.03_merge").merge


def _part(root: Path, number: int) -> UnpackedPart:
    """1ページの本文と画像を持つpartを保存する。"""
    directory = root / f"part-{number:04d}"
    (directory / "artifacts").mkdir(parents=True)
    (directory / "artifacts" / "image.png").write_bytes(b"png")
    bbox = {"l": 0, "t": 1, "r": 1, "b": 0, "coord_origin": "BOTTOMLEFT"}
    prov = [{"page_no": 1, "bbox": bbox, "charspan": [0, 1]}]
    document = {
        "schema_name": "DoclingDocument",
        "version": "1.7.0",
        "name": "part",
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/texts/0"}, {"$ref": "#/pictures/0"}],
        },
        "texts": [
            {
                "self_ref": "#/texts/0",
                "parent": {"$ref": "#/body"},
                "label": "text",
                "prov": prov,
                "orig": f"Text {number}",
                "text": f"Text {number}",
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "parent": {"$ref": "#/body"},
                "label": "picture",
                "prov": [{"page_no": 1, "bbox": bbox, "charspan": [0, 0]}],
                "image": {
                    "mimetype": "image/png",
                    "dpi": 144,
                    "size": {"width": 1, "height": 1},
                    "uri": "artifacts/image.png",
                },
            }
        ],
        "pages": {"1": {"size": {"width": 10, "height": 10}, "page_no": 1}},
    }
    path = directory / "document.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    artifact = ArtifactFile(
        relative_path=path.relative_to(root).as_posix(), sha256="0" * 64, size_bytes=1
    )
    return UnpackedPart(number=number, document=artifact, assets=[])


def test_merge_renumbers_parts_and_keeps_asset_namespaces(tmp_path: Path) -> None:
    """2partの参照とページを振り直し、同名画像をpart別に保持する。"""
    manifest = UnpackManifest(parts=[_part(tmp_path, 1), _part(tmp_path, 2)])
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-source")
    output = merge(manifest, source, tmp_path / "merged", tmp_path)
    merged = json.loads(output.read_text(encoding="utf-8"))
    # 後段が型として読めるよう、Doclingと同じ原本識別値を持つ。
    DoclingDocument.model_validate(merged)
    digest = hashlib.sha256(b"%PDF-source").hexdigest()
    assert merged["origin"]["binary_hash"] == int(digest, 16) % 2**64
    assert [item["text"] for item in merged["texts"]] == ["Text 1", "Text 2"]
    assert sorted(merged["pages"], key=int) == ["1", "2"]
    assert [item["prov"][0]["page_no"] for item in merged["texts"]] == [1, 2]
    assert {item["$ref"] for item in merged["body"]["children"]} >= {
        "#/texts/0",
        "#/texts/1",
    }
    assert [item["image"]["uri"] for item in merged["pictures"]] == [
        "assets/part-0001/image.png",
        "assets/part-0002/image.png",
    ]
    assert (tmp_path / "merged/assets/part-0002/image.png").read_bytes() == b"png"
    assert merged["origin"]["filename"] == "source.pdf"
