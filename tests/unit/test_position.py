"""読み順補正で中央見出しと実際の段組を区別する。"""

from importlib import import_module

import pytest

PositionTask = import_module("translate.tasks.10_position").PositionTask


@pytest.mark.parametrize("origin", ["TOPLEFT", "BOTTOMLEFT"])
@pytest.mark.parametrize(
    ("right_column", "expected"),
    [
        ([], ["header", "title", "left-1", "left-2", "footer"]),
        (
            [("right-1", 350, 105), ("right-2", 350, 160)],
            ["header", "title", "left-1", "left-2", "right-1", "right-2", "footer"],
        ),
    ],
)
def test_position_keeps_centered_title_above_body_columns(
    origin: str, right_column: list[tuple[str, int, int]], expected: list[str]
) -> None:
    """左右位置が異なる上部タイトルを、単段・二段本文の後ろへ送らない。"""
    rows = [
        ("left-1", 36, 110),
        ("left-2", 36, 165),
        *right_column,
        ("title", 248, 60),
        ("footer", 295, 800),
        ("header", 295, 20),
    ]
    texts = []
    for index, (name, left, top) in enumerate(rows):
        upper, lower = (
            (top, top + 15) if origin == "TOPLEFT" else (842 - top, 827 - top)
        )
        texts.append(
            {
                "self_ref": f"#/texts/{index}",
                "label": f"page_{name}"
                if name in {"header", "footer"}
                else "section_header",
                "text": name,
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": left,
                            "r": left + 100,
                            "t": upper,
                            "b": lower,
                            "coord_origin": origin,
                        },
                    }
                ],
            }
        )
    source = {
        "body": {"children": [{"$ref": text["self_ref"]} for text in texts]},
        "texts": texts,
    }
    result, _ = PositionTask(source).run()
    actual = [
        result["texts"][int(ref["$ref"].rsplit("/", 1)[1])]["text"]
        for ref in result["body"]["children"]
    ]
    assert actual == expected
    assert source["body"]["children"] == [{"$ref": text["self_ref"]} for text in texts]
