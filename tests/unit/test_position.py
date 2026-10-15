"""読み順補正で中央見出しと実際の段組を区別する。"""

from importlib import import_module
from pathlib import Path

import pypdfium2 as pdfium
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


@pytest.mark.parametrize("origin", ["TOPLEFT", "BOTTOMLEFT"])
def test_position_restores_numbered_heading_lines_from_pdf(origin: str) -> None:
    """実PDFの三つの見出しを分離し、階層・座標・所有参照と元の本文を保持する。"""
    pdf = Path(__file__).parents[2] / "inputs/sample.pdf"
    text = "7.1.1.1 Heading 4 7.1.1.1.1 Heading 5 7.1.1.1.1.1 Heading 6"
    top, bottom = 674.0412779453125, 622.957149286749
    if origin == "TOPLEFT":
        with pdfium.PdfDocument(pdf) as document:
            height = document.get_page_size(9)[1]
        top, bottom = height - top, height - bottom
    source = {
        "body": {"self_ref": "#/body", "children": [{"$ref": "#/texts/0"}]},
        "texts": [
            {
                "self_ref": "#/texts/0",
                "parent": {"$ref": "#/body"},
                "label": "section_header",
                "children": [],
                "level": 3,
                "text": text,
                "orig": text,
                "prov": [
                    {
                        "page_no": 10,
                        "charspan": [0, len(text)],
                        "bbox": {
                            "l": 36,
                            "r": 154.48439615626688,
                            "t": top,
                            "b": bottom,
                            "coord_origin": origin,
                        },
                    }
                ],
            }
        ],
    }
    result, report = PositionTask(source, pdf).run()
    assert [item["text"] for item in result["texts"]] == [
        "7.1.1.1 Heading 4",
        "7.1.1.1.1 Heading 5",
        "7.1.1.1.1.1 Heading 6",
    ]
    assert [item["level"] for item in result["texts"]] == [4, 5, 6]
    assert result["body"]["children"] == [{"$ref": f"#/texts/{i}"} for i in range(3)]
    for item in result["texts"]:
        assert item["parent"] == {"$ref": "#/body"}
        assert item["orig"] == item["text"]
        assert item["prov"][0]["charspan"] == [0, len(item["text"])]
        assert item["prov"][0]["bbox"]["coord_origin"] == "BOTTOMLEFT"
    assert len({item["prov"][0]["bbox"]["t"] for item in result["texts"]}) == 3
    assert report["split_headings"] == ["#/texts/0"]
    assert source["texts"][0]["text"] == text
    assert len(source["texts"]) == 1


@pytest.mark.parametrize(
    "case", ["mismatch", "paragraph", "shared", "children", "single"]
)
def test_position_keeps_unproven_heading_boundaries(case: str) -> None:
    """本文不一致・通常段落・曖昧な所有・一つの見出しを分割しない。"""
    text = "7.1.1.1 Heading 4 7.1.1.1.1 Heading 5 7.1.1.1.1.1 Heading 6"
    item = {
        "self_ref": "#/texts/0",
        "parent": {"$ref": "#/body"},
        "label": "paragraph" if case == "paragraph" else "section_header",
        "text": text + " extra" if case == "mismatch" else text,
        "children": [{"$ref": "#/texts/1"}] if case == "children" else [],
        "prov": [
            {
                "page_no": 10,
                "bbox": {
                    "l": 36,
                    "r": 154.48439615626688,
                    "t": 674.0412779453125,
                    "b": 622.957149286749,
                },
            }
        ],
    }
    if case == "single":
        item["text"] = "7.1.1.1 Heading 4"
        item["prov"][0]["bbox"]["b"] = 664.27294921875
    source = {"body": {"children": [{"$ref": "#/texts/0"}]}, "texts": [item]}
    if case == "shared":
        source["extra_reference"] = {"$ref": "#/texts/0"}
    result, report = PositionTask(
        source, Path(__file__).parents[2] / "inputs/sample.pdf"
    ).run()
    assert result["texts"] == [item]
    assert report["split_headings"] == []
