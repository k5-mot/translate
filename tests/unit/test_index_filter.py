"""Doclingの目次ラベルが本文を巻き込んでも内容を失わないことを検証する。"""

import json
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

normalize = import_module("translate.tasks.11_normalize").normalize
DocumentLoader = import_module("translate.tasks.12_load").DocumentLoader


def _table(index: int, rows: list[list[str]], representation: str) -> dict[str, Any]:
    """目次と誤判定された注記を、同じDocling表形式で作る。"""
    grid = [
        [
            {
                "text": text,
                "start_row_offset_idx": row,
                "end_row_offset_idx": row + 1,
                "start_col_offset_idx": column,
                "end_col_offset_idx": column + 1,
            }
            for column, text in enumerate(values)
        ]
        for row, values in enumerate(rows)
    ]
    return {
        "self_ref": f"#/tables/{index}",
        "label": "document_index",
        "prov": [{"page_no": 1}],
        "data": {
            "num_rows": len(rows),
            "num_cols": len(rows[0]),
            representation: grid
            if representation == "grid"
            else [cell for row in grid for cell in row],
        },
    }


@pytest.mark.parametrize("representation", ["table_cells", "grid"])
@pytest.mark.parametrize("title", ["目次", ""])
def test_index_label_does_not_remove_note_table(
    tmp_path: Path, representation: str, title: str
) -> None:
    """目次・続きページの項目を除外し、同じページの誤分類された注記を保持する。"""
    notes = [
        f"{kind}: Provides useful information."
        for kind in ("NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION")
    ]
    texts = (
        [
            {
                "self_ref": "#/texts/0",
                "label": "section_header",
                "text": title,
                "prov": [{"page_no": 1}],
            }
        ]
        if title
        else []
    )
    value = {
        "schema_name": "DoclingDocument",
        "pages": {"1": {"size": {"width": 100, "height": 200}}},
        "texts": texts,
        "tables": [
            _table(
                0, [["Chapter", "2"]] if title else [["Chapter .... 2"]], representation
            ),
            _table(1, [[text] for text in notes], representation),
        ],
        "body": {
            "children": [{"$ref": item["self_ref"]} for item in texts]
            + [{"$ref": "#/tables/0"}, {"$ref": "#/tables/1"}]
        },
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    normalized = json.loads(
        normalize(source, tmp_path / "normalized").read_text(encoding="utf-8")
    )
    for data in (value, normalized):
        document = DocumentLoader(data).load()
        assert len(document.pages[0].blocks) == 1
        block = document.pages[0].blocks[0]
        assert block.kind == "table"
        assert [cell.content.text("source") for cell in block.cells] == notes
