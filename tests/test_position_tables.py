"""POSITIONの分割table再構成fixture。"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING

import pytest

from translate.document import inline_text
from translate.tasks import load, normalize, position

if TYPE_CHECKING:
    from pathlib import Path


def _table(ref: str, top: float, columns: int) -> dict[str, object]:
    """
    指定列数の一行表とセル参照を作り、位置・列互換性・結合後offsetを検査可能にする。
    """

    return {
        "self_ref": ref,
        "label": "table",
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": 0,
                    "r": 200,
                    "t": top,
                    "b": top + 50,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
        "data": {
            "num_rows": 1,
            "num_cols": columns,
            "table_cells": [
                {
                    "self_ref": f"{ref}/cell/{column}",
                    "parent": {"$ref": ref},
                    "start_row_offset_idx": 0,
                    "end_row_offset_idx": 1,
                    "start_col_offset_idx": column,
                    "end_col_offset_idx": column + 1,
                    "text": f"cell-{column}",
                }
                for column in range(columns)
            ],
        },
    }


def _run(
    tmp_path: Path,
    first: dict[str, object],
    second: dict[str, object],
    extra: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """二つの表断片をPOSITIONへ渡し、補正文書と結合・警告reportを読んで返す。"""

    document = {
        "schema_name": "DoclingDocument",
        "pages": {"1": {"page_no": 1}},
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": first["self_ref"]}, {"$ref": second["self_ref"]}],
        },
        "tables": [first, second],
    }
    document.update(extra or {})
    source = tmp_path / "source.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    result = position.run(source, tmp_path / "position")
    return (
        json.loads(result.read_text(encoding="utf-8")),
        json.loads((result.parent / "report.json").read_text(encoding="utf-8")),
    )


def test_compatible_table_fragments_reconstruct_rows_spans_and_references(
    tmp_path: Path,
) -> None:
    """同じ列構造の連続tableをrow offset付きで結合する。"""

    document, report = _run(
        tmp_path,
        _table("#/tables/0", 0, 2),
        _table("#/tables/1", 52, 2),
    )
    cells = document["tables"][0]["data"]["table_cells"]

    assert len(document["body"]["children"]) == 1
    assert document["tables"][0]["data"]["num_rows"] == 2
    assert [cell["start_row_offset_idx"] for cell in cells] == [0, 0, 1, 1]
    assert all(cell["parent"]["$ref"] == "#/tables/0" for cell in cells)
    assert report["merged"][0]["reason"] == "table rows and spans reconstructed"


def test_ambiguous_table_fragments_remain_separate_with_warning(tmp_path: Path) -> None:
    """列数が異なるtableを誤結合せず警告する。"""

    document, report = _run(
        tmp_path,
        _table("#/tables/0", 0, 2),
        _table("#/tables/1", 52, 3),
    )

    assert len(document["body"]["children"]) == 2
    assert report["warnings"] == [
        {
            "first": "#/tables/0",
            "second": "#/tables/1",
            "reason": "ambiguous table fragments kept separate",
        }
    ]


def test_merged_table_is_loaded_once_without_rewriting_cell_text(
    tmp_path: Path,
) -> None:
    """表結合後の全セルと参照風本文を実LOADまで保持し、元表を再追加しない。"""

    first, second = _table("#/tables/0", 0, 2), _table("#/tables/1", 52, 2)
    literal = "literal #/tables/10 then #/tables/1"
    second["data"]["table_cells"][0]["text"] = literal
    document, _ = _run(tmp_path, first, second)
    assert document["tables"][0]["data"]["table_cells"][2]["text"] == literal
    assert len(document["tables"]) == 1
    loaded = load.run(
        normalize.run(tmp_path / "position/document.json", tmp_path / "normalize"),
        tmp_path / "load",
    )
    assert len(loaded.pages[0].blocks) == 1
    cells = loaded.pages[0].blocks[0].cells
    assert [inline_text(cell.source) for cell in cells] == [
        "cell-0",
        "cell-1",
        literal,
        "cell-1",
    ]
    assert [cell.row for cell in cells] == [0, 0, 1, 1]


@pytest.mark.parametrize("representation", ["table_cells", "cells"])
def test_table_spans_cell_ids_and_literal_fields_survive(
    tmp_path: Path,
    representation: str,
) -> None:
    """複数行・結合セル・同名セルID・参照風文字列を結合後と再適用後に保持する。"""

    first, second = _table("#/tables/0", 0, 2), _table("#/tables/1", 52, 2)
    for table in (first, second):
        cells = table["data"].pop("table_cells")
        cells[0]["end_row_offset_idx"] = 2
        cells[1]["end_row_offset_idx"] = 2
        table["data"].update({"num_rows": 2, representation: cells})
    literal = "https://example.invalid/#/tables/10?q=#/tables/1"
    for key in ("text", "text_content", "url"):
        second["data"][representation][0][key] = literal
    document, _ = _run(tmp_path, first, second)
    cells = document["tables"][0]["data"][representation]
    assert [cell["self_ref"] for cell in cells] == [
        f"#/tables/0/cell/{i}" for i in range(4)
    ]
    assert all(cell["parent"] == {"$ref": "#/tables/0"} for cell in cells)
    assert [cell["start_row_offset_idx"] for cell in cells] == [0, 0, 2, 2]
    assert [cell["end_row_offset_idx"] for cell in cells] == [2, 2, 4, 4]
    assert all(cells[2][key] == literal for key in ("text", "text_content", "url"))
    repeated = position.run(tmp_path / "position/document.json", tmp_path / "repeat")
    assert json.loads(repeated.read_text(encoding="utf-8")) == document
    loaded = load.run(
        normalize.run(repeated, tmp_path / "normalize"), tmp_path / "load"
    )
    assert len(loaded.pages[0].blocks) == 1
    assert [cell.rowspan for cell in loaded.pages[0].blocks[0].cells] == [2] * 4


@pytest.mark.parametrize(
    "mode",
    [
        "grid",
        "both",
        "empty_grid",
        "both_cells",
        "external_cell",
        "unknown_id",
        "overlap",
        "invalid_span",
    ],
)
def test_uncertain_table_representation_is_not_mutated(
    tmp_path: Path, mode: str
) -> None:
    """表現やセル参照を確定できない候補を原形のまま保ち、警告する。"""

    first, second = _table("#/tables/0", 0, 2), _table("#/tables/1", 52, 2)
    extra = {}
    if mode in {"grid", "both", "empty_grid"}:
        for table in (first, second):
            table["data"]["grid"] = (
                []
                if mode == "empty_grid"
                else [copy.deepcopy(table["data"]["table_cells"])]
            )
            if mode == "grid":
                del table["data"]["table_cells"]
    elif mode == "both_cells":
        second["data"]["cells"] = copy.deepcopy(second["data"]["table_cells"])
    elif mode == "external_cell":
        extra = {"metadata": {"cell": {"$ref": "#/tables/1/cell/0"}}}
    elif mode == "unknown_id":
        second["data"]["table_cells"][0]["self_ref"] = "#/tables/1/unknown/0"
    elif mode == "overlap":
        second["data"]["table_cells"][1]["start_col_offset_idx"] = 0
    else:
        second["data"]["table_cells"][0]["end_row_offset_idx"] = 0
    before = copy.deepcopy([first, second])
    document, report = _run(tmp_path, first, second, extra)
    assert document["tables"] == before
    assert report["warnings"]
    assert not report["merged"]
    expected = load.load_document(
        json.loads((tmp_path / "source.json").read_text(encoding="utf-8"))
    )
    loaded = load.run(
        normalize.run(tmp_path / "position/document.json", tmp_path / "normalize"),
        tmp_path / "load",
    )
    assert loaded == expected


@pytest.mark.parametrize("shared", [False, True])
def test_table_caption_ownership_survives_rejected_merge(
    tmp_path: Path, *, shared: bool
) -> None:
    """固有/共有Captionを持つ表を残し、実LOADでCaptionが消失しないことを確認する。"""

    first, second = _table("#/tables/0", 0, 2), _table("#/tables/1", 52, 2)
    first["captions"] = [{"$ref": "#/texts/0"}]
    second["captions"] = [{"$ref": f"#/texts/{0 if shared else 1}"}]
    texts = [
        {
            "self_ref": f"#/texts/{i}",
            "label": "caption",
            "text": f"Caption {i}",
            "prov": [{"page_no": 1}],
        }
        for i in range(1 if shared else 2)
    ]
    document, report = _run(tmp_path, first, second, {"texts": texts})
    assert document["tables"] == [first, second]
    assert report["warnings"]
    assert not report["merged"]
    loaded = load.run(
        normalize.run(tmp_path / "position/document.json", tmp_path / "normalize"),
        tmp_path / "load",
    )
    assert len(loaded.pages[0].blocks) == 2
    assert [inline_text(block.caption) for block in loaded.pages[0].blocks] == [
        "Caption 0",
        f"Caption {0 if shared else 1}",
    ]


def test_three_tables_keep_colspans_and_unique_cell_ids(tmp_path: Path) -> None:
    """三表の連鎖結合で列結合幅と後半セルIDを保持する。"""

    tables = [_table(f"#/tables/{index}", index * 52, 2) for index in range(3)]
    for table in tables:
        cell = table["data"]["table_cells"][0]
        cell["end_col_offset_idx"] = 2
        cell["col_span"] = 2
        table["data"]["table_cells"] = [cell]
    document, report = _run(
        tmp_path,
        *tables[:2],
        {
            "tables": tables,
            "body": {"children": [{"$ref": table["self_ref"]} for table in tables]},
        },
    )
    assert len(document["tables"]) == 1
    assert len(report["merged"]) == 2
    assert [
        cell["self_ref"] for cell in document["tables"][0]["data"]["table_cells"]
    ] == [f"#/tables/0/cell/{index}" for index in range(3)]
    loaded = load.run(
        normalize.run(tmp_path / "position/document.json", tmp_path / "normalize"),
        tmp_path / "load",
    )
    assert [(cell.row, cell.colspan) for cell in loaded.pages[0].blocks[0].cells] == [
        (0, 2),
        (1, 2),
        (2, 2),
    ]


def test_table_children_keep_their_parent_and_content(tmp_path: Path) -> None:
    """表配下の子要素を結合で孤立させず、親参照と本文を読込みまで保持する。"""

    first, second = _table("#/tables/0", 0, 2), _table("#/tables/1", 52, 2)
    second["children"] = [{"$ref": "#/texts/0"}]
    child = {
        "self_ref": "#/texts/0",
        "parent": {"$ref": "#/tables/1"},
        "label": "text",
        "text": "table child",
        "prov": [{"page_no": 1}],
    }
    document, report = _run(tmp_path, first, second, {"texts": [child]})
    assert document["tables"] == [first, second]
    assert document["texts"] == [child]
    assert report["warnings"]
    assert not report["merged"]
    loaded = load.run(
        normalize.run(tmp_path / "position/document.json", tmp_path / "normalize"),
        tmp_path / "load",
    )
    assert len(loaded.pages[0].blocks) == 3
    assert inline_text(loaded.pages[0].blocks[-1].source) == "table child"


def test_tail_page_match_does_not_move_table_to_another_page(tmp_path: Path) -> None:
    """表の末尾出典が後続表と同じページでも代表ページが異なれば結合しない。"""

    first, second = _table("#/tables/0", 0, 2), _table("#/tables/1", 52, 2)
    first["prov"].append(copy.deepcopy(first["prov"][0]))
    first["prov"][-1]["page_no"] = 2
    second["prov"][0]["page_no"] = 2
    document, report = _run(
        tmp_path, first, second, {"pages": {"1": {"page_no": 1}, "2": {"page_no": 2}}}
    )
    assert document["tables"] == [first, second]
    assert report["warnings"]
    assert not report["merged"]
    loaded = load.run(
        normalize.run(tmp_path / "position/document.json", tmp_path / "normalize"),
        tmp_path / "load",
    )
    assert [len(page.blocks) for page in loaded.pages] == [1, 1]
