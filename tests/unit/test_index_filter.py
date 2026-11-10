"""Doclingの目次ラベルが本文を巻き込んでも内容を失わないことを検証する。"""

import json
from importlib import import_module
from pathlib import Path

import pytest
from docling_core.types.doc import DocItemLabel, DoclingDocument, TableCell, TableData

from tests import docling_document, docling_prov

normalize = import_module("translate.tasks.11_normalize").normalize
DocumentLoader = import_module("translate.tasks.12_load").DocumentLoader


def _add_index_table(document: DoclingDocument, rows: list[list[str]]) -> None:
    """目次と誤判定された注記を、Doclingの表として追加する。"""
    document.add_table(
        label=DocItemLabel.DOCUMENT_INDEX,
        data=TableData(
            num_rows=len(rows),
            num_cols=len(rows[0]),
            table_cells=[
                TableCell(
                    text=text,
                    start_row_offset_idx=row,
                    end_row_offset_idx=row + 1,
                    start_col_offset_idx=column,
                    end_col_offset_idx=column + 1,
                )
                for row, values in enumerate(rows)
                for column, text in enumerate(values)
            ],
        ),
        prov=docling_prov(),
    )


@pytest.mark.parametrize("title", ["目次", ""])
def test_index_label_does_not_remove_note_table(tmp_path: Path, title: str) -> None:
    """目次・続きページの項目を除外し、同じページの誤分類された注記を保持する。"""
    notes = [
        f"{kind}: Provides useful information."
        for kind in ("NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION")
    ]
    document = docling_document()
    if title:
        document.add_text(
            label=DocItemLabel.SECTION_HEADER, text=title, prov=docling_prov()
        )
    _add_index_table(document, [["Chapter", "2"]] if title else [["Chapter .... 2"]])
    _add_index_table(document, [[text] for text in notes])
    value = document.export_to_dict()
    source = tmp_path / "source.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    normalized = json.loads(
        normalize(source, tmp_path / "normalized").read_text(encoding="utf-8")
    )
    for data in (value, normalized):
        loaded = DocumentLoader(data).load()
        assert len(loaded.pages[0].blocks) == 1
        block = loaded.pages[0].blocks[0]
        assert block.kind == "table"
        assert [cell.content.text("source") for cell in block.cells] == notes
