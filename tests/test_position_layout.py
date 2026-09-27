"""POSITIONの読み順とfragment結合fixture。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from translate.document import inline_text
from translate.tasks import load, markdown, normalize, position

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
    """header・footer、左右column、座標なしの要素が期待する順序になるか検査する。"""

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

    assert refs == ["#/texts/0", "#/texts/1", "#/texts/2"]
    assert positioned["texts"][0]["text"] == "paragraph one paragraph two"
    assert positioned["texts"][1]["text"] == "code one\ncode two"
    report = json.loads((result.parent / "report.json").read_text(encoding="utf-8"))
    assert [item["output_ref"] for item in report["merged"]] == [
        "#/texts/0",
        "#/texts/1",
    ]


@pytest.mark.parametrize("label", ["text", "paragraph", "code", "program_listing"])
def test_consumed_fragments_do_not_reappear_in_load(tmp_path: Path, label: str) -> None:
    """実前処理を通し、結合元だけを除いて未参照・同文の独立要素を残す。"""

    items = [
        _item("#/texts/0", "A", 0, 0, label),
        _item("#/texts/1", "B", 0, 12, label),
        _item("#/texts/2", "U", 0, 200, label),
        _item("#/texts/3", "B", 0, 300, label),
    ]
    document = {
        "schema_name": "DoclingDocument",
        "pages": {"1": {"page_no": 1}},
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
        "texts": items,
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    before = source.read_bytes()
    result = position.run(source, tmp_path / "position")
    normalized = normalize.run(result, tmp_path / "normalize")
    loaded = load.run(normalized, tmp_path / "load")
    separator = "\n" if label in {"code", "program_listing"} else " "
    assert [inline_text(block.source) for block in loaded.pages[0].blocks] == [
        f"A{separator}B",
        "U",
        "B",
    ]
    assert source.read_bytes() == before
    rendered = [markdown.render_block(block) for block in loaded.pages[0].blocks]
    assert sum(f"A{separator}B" in text for text in rendered) == 1


def test_shared_fragments_are_not_mutated_twice(tmp_path: Path) -> None:
    """二親が同じ本文を共有しても結合せず、一度だけ内容を読込む。"""

    document = {
        "schema_name": "DoclingDocument",
        "pages": {"1": {"page_no": 1}},
        "texts": [_item("#/texts/0", "A", 0, 0), _item("#/texts/1", "B", 0, 12)],
        "groups": [
            {
                "self_ref": f"#/groups/{index}",
                "children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}],
            }
            for index in range(2)
        ],
        "body": {"children": [{"$ref": "#/groups/0"}, {"$ref": "#/groups/1"}]},
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    result = position.run(source, tmp_path / "position")
    positioned = json.loads(result.read_text(encoding="utf-8"))
    assert positioned["texts"] == document["texts"]
    report = json.loads((result.parent / "report.json").read_text(encoding="utf-8"))
    assert report["warnings"]
    assert not report["merged"]
    loaded = load.run(normalize.run(result, tmp_path / "normalize"), tmp_path / "load")
    assert [inline_text(block.source) for block in loaded.pages[0].blocks] == ["A", "B"]


def test_failed_position_publication_keeps_previous_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """report保存失敗でも入力と公開済み文書を変更せず、部分的な結合を公開しない。"""

    document = {
        "texts": [_item("#/texts/0", "A", 0, 0), _item("#/texts/1", "B", 0, 12)],
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    result = position.run(source, tmp_path / "position")
    before = {path.name: path.read_bytes() for path in result.parent.iterdir()}
    write = position.atomic_write_json

    def fail_report(path: Path, value: object) -> None:
        """文書は一時保存させ、続くreport保存だけを合成失敗させる。"""
        if path.name == "report.json":
            message = "synthetic report failure"
            raise OSError(message)
        write(path, value)

    monkeypatch.setattr(position, "atomic_write_json", fail_report)
    with pytest.raises(OSError, match="synthetic report failure"):
        position.run(source, tmp_path / "position")
    assert {path.name: path.read_bytes() for path in result.parent.iterdir()} == before
    assert json.loads(source.read_text(encoding="utf-8")) == document


@pytest.mark.parametrize("shared", [0, 1])
def test_one_shared_fragment_keeps_both_candidates(tmp_path: Path, shared: int) -> None:
    """片側だけの共有でも消費元/結合先の両方を変更しない。"""

    items = [_item("#/texts/0", "A", 0, 0), _item("#/texts/1", "B", 0, 12)]
    document = {
        "texts": items,
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
        "groups": [{"children": [{"$ref": f"#/texts/{shared}"}]}],
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    result = position.run(source, tmp_path / "position")
    assert json.loads(result.read_text(encoding="utf-8"))["texts"] == items
    report = json.loads((result.parent / "report.json").read_text(encoding="utf-8"))
    assert len(report["warnings"]) == 1
    assert not report["merged"]


@pytest.mark.parametrize(
    "field", ["children", "captions", "caption", "title", "formatting", "hyperlink"]
)
def test_ambiguous_text_metadata_is_preserved(tmp_path: Path, field: str) -> None:
    """所有内容と異なる表示属性を結合で捨てず、本文を診断へ転記しない。"""

    marker = "PRIVATE-BODY-CREDENTIAL-123"
    items = [_item("#/texts/0", marker, 0, 0), _item("#/texts/1", "B", 0, 12)]
    items[1][field] = (
        [{"$ref": "#/texts/2"}] if field in {"children", "captions"} else marker
    )
    items.append(_item("#/texts/2", "C", 0, 200))
    document = {
        "texts": items,
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    result = position.run(source, tmp_path / "position")
    assert json.loads(result.read_text(encoding="utf-8"))["texts"] == items
    report_text = (result.parent / "report.json").read_text(encoding="utf-8")
    assert marker not in report_text
    assert json.loads(report_text)["warnings"]


def test_chain_compaction_keeps_later_refs_and_is_idempotent(tmp_path: Path) -> None:
    """連鎖結合・原文層・後続index 10を保ち、再適用しても同じ文書を得る。"""

    items = [
        _item(
            f"#/texts/{index}", str(index), 0, index * 12 if index < 4 else index * 100
        )
        for index in range(11)
    ]
    for item in items:
        item["orig"] = item["text"]
    document = {
        "schema_name": "DoclingDocument",
        "pages": {"1": {"page_no": 1}},
        "texts": items,
        "body": {"children": [{"$ref": item["self_ref"]} for item in items]},
        "pictures": [],
        "metadata": {"target": {"$ref": "#/texts/10"}, "literal": "#/texts/10"},
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    result = position.run(source, tmp_path / "position")
    value = json.loads(result.read_text(encoding="utf-8"))
    assert value["texts"][0]["text"] == value["texts"][0]["orig"] == "0 1 2 3"
    assert len(value["texts"]) == 8
    assert value["metadata"] == {
        "target": {"$ref": "#/texts/7"},
        "literal": "#/texts/10",
    }
    assert [item["self_ref"] for item in value["texts"]] == [
        f"#/texts/{i}" for i in range(8)
    ]
    repeated = position.run(result, tmp_path / "repeated")
    assert json.loads(repeated.read_text(encoding="utf-8")) == value
    report = json.loads((result.parent / "report.json").read_text(encoding="utf-8"))
    assert [item["from"] for item in report["merged"]] == [
        "#/texts/1",
        "#/texts/2",
        "#/texts/3",
    ]
    assert {item["output_ref"] for item in report["merged"]} == {"#/texts/0"}
    loaded = load.run(
        normalize.run(repeated, tmp_path / "normalize"), tmp_path / "load"
    )
    assert [inline_text(block.source) for block in loaded.pages[0].blocks] == [
        "0 1 2 3",
        *map(str, range(4, 11)),
    ]


def test_duplicate_child_reference_does_not_merge_with_itself(tmp_path: Path) -> None:
    """同じ親が同じrefを繰り返しても自己結合や別候補への消費を行わない。"""

    items = [_item("#/texts/0", "A", 0, 0), _item("#/texts/1", "B", 0, 12)]
    document = {
        "texts": items,
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/1"},
            ]
        },
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    result = position.run(source, tmp_path / "position")
    assert json.loads(result.read_text(encoding="utf-8")) == document
    report = json.loads((result.parent / "report.json").read_text(encoding="utf-8"))
    assert report["warnings"]
    assert not report["merged"]
