"""POSITIONの分割table再構成fixture。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from translate.tasks import position

if TYPE_CHECKING:
    from pathlib import Path


def _table(ref: str, top: float, columns: int) -> dict[str, object]:
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
    tmp_path: Path, first: dict[str, object], second: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    document = {
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": first["self_ref"]}, {"$ref": second["self_ref"]}],
        },
        "tables": [first, second],
    }
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
