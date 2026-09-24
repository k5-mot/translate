"""POSITIONの読み順とfragment結合fixture。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from translate.tasks import position

if TYPE_CHECKING:
    from pathlib import Path


def _item(
    ref: str, text: str, left: float, top: float, label: str = "text"
) -> dict[str, object]:
    """左上原点の固定寸法bboxを持つ要素を作り、段組・領域・断片間隔の条件を制御する。"""

    return {
        "self_ref": ref,
        "label": label,
        "text": text,
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": left,
                    "r": left + 100,
                    "t": top,
                    "b": top + 10,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
    }


def test_multi_column_marginalia_overlap_and_missing_coordinates_are_stable(
    tmp_path: Path,
) -> None:
    """欄外、左右column、重なり、座標なしを決定的に並べる。"""

    items = [
        _item("#/texts/0", "right-bottom", 300, 100),
        _item("#/texts/1", "left-bottom", 0, 100),
        _item("#/texts/2", "footer", 0, 500, "page_footer"),
        _item("#/texts/3", "right-top", 300, 10),
        _item("#/texts/4", "left-top", 0, 10),
        _item("#/texts/5", "header", 0, 0, "page_header"),
        {"self_ref": "#/texts/6", "label": "text", "text": "no-box-a"},
        {"self_ref": "#/texts/7", "label": "text", "text": "no-box-b"},
    ]
    document = {
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": item["self_ref"]} for item in items],
        },
        "texts": items,
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")

    result = position.run(source, tmp_path / "position")
    positioned = json.loads(result.read_text(encoding="utf-8"))
    refs = [item["$ref"] for item in positioned["body"]["children"]]
    report = json.loads((result.parent / "report.json").read_text(encoding="utf-8"))

    assert refs == [
        "#/texts/5",
        "#/texts/4",
        "#/texts/1",
        "#/texts/3",
        "#/texts/0",
        "#/texts/2",
        "#/texts/6",
        "#/texts/7",
    ]
    assert report["reordered"][0]["before"] != report["reordered"][0]["after"]


def test_paragraph_and_code_fragments_merge_only_when_continuous(
    tmp_path: Path,
) -> None:
    """幾何的に連続する同label fragmentだけを結合する。"""

    items = [
        _item("#/texts/0", "paragraph one", 0, 0),
        _item("#/texts/1", "paragraph two", 0, 12),
        _item("#/texts/2", "code one", 0, 40, "code"),
        _item("#/texts/3", "code two", 0, 52, "code"),
        _item("#/texts/4", "far paragraph", 0, 200),
    ]
    document = {
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": item["self_ref"]} for item in items],
        },
        "texts": items,
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")

    result = position.run(source, tmp_path / "position")
    positioned = json.loads(result.read_text(encoding="utf-8"))
    refs = [item["$ref"] for item in positioned["body"]["children"]]

    assert refs == ["#/texts/0", "#/texts/2", "#/texts/4"]
    assert positioned["texts"][0]["text"] == "paragraph one paragraph two"
    assert positioned["texts"][2]["text"] == "code one\ncode two"
