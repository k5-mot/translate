"""POSITIONの分割table再構成fixture。"""

from __future__ import annotations

import copy
import json
import socket
from typing import TYPE_CHECKING, Any

import pytest

from translate_v1.adapters.checkpoint import open_checkpoint
from translate_v1.common.workspace import atomic_write_json, sha256_file
from translate_v1.document import inline_text
from translate_v1.tasks import load, normalize, position
from translate_v1.workflows import translation

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from translate_v1.common.settings import Settings


def _cell_image_document() -> dict[str, Any]:
    """原点混在・画像のみセル・Captionを持つ最小Docling表を作る。"""

    return {
        "schema_name": "DoclingDocument",
        "pages": {"1": {"size": {"width": 100, "height": 100}}},
        "body": {
            "children": [
                {"$ref": "#/tables/0"},
                {"$ref": "#/pictures/0"},
                {"$ref": "#/pictures/0"},
                {"$ref": "#/texts/0"},
            ]
        },
        "texts": [{"self_ref": "#/texts/0", "label": "caption", "text": "Status"}],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 0,
                            "t": 100,
                            "r": 100,
                            "b": 0,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
                "data": {
                    "num_rows": 2,
                    "num_cols": 2,
                    "grid": [
                        [
                            {"text": ""},
                            {
                                "text": "Program",
                                "column_header": True,
                                "bbox": {
                                    "l": 50,
                                    "t": 0,
                                    "r": 90,
                                    "b": 10,
                                    "coord_origin": "TOPLEFT",
                                },
                            },
                        ],
                        [
                            {
                                "text": "Status",
                                "row_header": True,
                                "bbox": {
                                    "l": 0,
                                    "t": 50,
                                    "r": 20,
                                    "b": 80,
                                    "coord_origin": "TOPLEFT",
                                },
                            },
                            {"text": ""},
                        ],
                    ],
                },
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "picture",
                "parent": {"$ref": "#/body"},
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 60,
                            "t": 40,
                            "r": 70,
                            "b": 30,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
                "image": {"uri": "assets/status.png"},
                "captions": [{"$ref": "#/texts/0"}],
            }
        ],
    }


@pytest.mark.parametrize("representation", ["grid", "cells", "both"])
@pytest.mark.parametrize("origin", ["TOPLEFT", "BOTTOMLEFT"])
def test_load_keeps_table_image_in_unique_header_intersection(
    representation: str, origin: str
) -> None:
    """grid/offsetと原点を変えても画像を一意セルへ置き、本文の重複を除く。"""

    document = _cell_image_document()
    data = document["tables"][0]["data"]
    flat = []
    for row_index, row in enumerate(data["grid"]):
        for col_index, cell in enumerate(row):
            cell.update(
                start_row_offset_idx=row_index,
                end_row_offset_idx=row_index + 1,
                start_col_offset_idx=col_index,
                end_col_offset_idx=col_index + 1,
            )
            flat.append(copy.deepcopy(cell))
    if representation != "grid":
        data["table_cells"] = flat
    if representation == "cells":
        del data["grid"]
    if origin == "TOPLEFT":
        box = document["pictures"][0]["prov"][0]["bbox"]
        box.update(t=60, b=70, coord_origin=origin)
    original = copy.deepcopy(document)
    result = load.load_document(document)
    assert document == original
    assert len(result.pages[0].blocks) == 1
    table = result.pages[0].blocks[0]
    cell = next(cell for cell in table.cells if (cell.row, cell.column) == (1, 1))
    assert cell.source == []
    assert len(cell.images) == 1
    image = cell.images[0]
    assert (image.id, image.asset_path, image.width_pt, image.height_pt) == (
        "#/pictures/0",
        "assets/status.png",
        10,
        10,
    )
    assert inline_text(image.caption) == "Status"


@pytest.mark.parametrize("reference", ["parent", "child", "bbox"])
def test_load_uses_cell_reference_or_bbox_without_header_guess(reference: str) -> None:
    """明示所有またはセルbboxで確定し、根拠のない行列推測をしない。"""

    document = _cell_image_document()
    table = document["tables"][0]
    cell = table["data"]["grid"][1][1]
    for row in table["data"]["grid"]:
        for raw in row:
            raw.pop("bbox", None)
    if reference == "parent":
        document["pictures"][0]["parent"] = {"$ref": "#/tables/0/data/grid/1/1"}
        table.pop("prov")
    elif reference == "child":
        cell["children"] = [{"$ref": "#/pictures/0"}]
    else:
        cell["bbox"] = {"l": 50, "t": 50, "r": 90, "b": 90, "coord_origin": "TOPLEFT"}
    result = load.load_document(document)
    assert len(result.pages[0].blocks) == 1
    assert result.pages[0].blocks[0].cells[3].images[0].id == "#/pictures/0"


@pytest.mark.parametrize(
    "failure",
    [
        "missing-image-box",
        "missing-table-box",
        "missing-height",
        "unknown-origin",
        "nan",
        "zero-size",
        "partial-overlap",
        "multiple-tables",
        "multiple-cells",
        "multiple-owners",
        "invalid-parent",
        "wrong-cell",
        "wrong-page",
        "no-cell-evidence",
        "header-boundary",
        "span-disagreement",
        "shape-disagreement",
        "missing-child",
        "invalid-parent-shape",
        "cell-other-page",
        "contradictory-cell-box",
        "header-role-disagreement",
    ],
)
def test_load_rejects_uncertain_table_image_ownership(failure: str) -> None:  # noqa: C901, PLR0912, PLR0915
    """不正・競合根拠を独立図出力や最近傍fallbackで隠さず停止する。"""

    document = _cell_image_document()
    table, picture = document["tables"][0], document["pictures"][0]
    box = picture["prov"][0]["bbox"]
    grid = table["data"]["grid"]
    if failure == "missing-image-box":
        picture.pop("prov")
    elif failure == "missing-table-box":
        table.pop("prov")
    elif failure == "missing-height":
        document["pages"]["1"]["size"].pop("height")
    elif failure == "unknown-origin":
        box["coord_origin"] = "UNKNOWN"
    elif failure == "nan":
        box["l"] = float("nan")
    elif failure == "zero-size":
        box["r"] = box["l"]
    elif failure == "partial-overlap":
        box.update(l=95, r=105)
    elif failure == "multiple-tables":
        duplicate = copy.deepcopy(table)
        duplicate["self_ref"] = "#/tables/1"
        document["tables"].append(duplicate)
    elif failure == "multiple-cells":
        for cell in grid[1]:
            cell["bbox"] = {
                "l": 50,
                "t": 50,
                "r": 90,
                "b": 90,
                "coord_origin": "TOPLEFT",
            }
    elif failure == "multiple-owners":
        for cell in grid[1]:
            cell["children"] = [{"$ref": "#/pictures/0"}]
    elif failure == "invalid-parent":
        picture["parent"] = {"$ref": "#/tables/0/data/grid/5/5"}
    elif failure == "wrong-cell":
        picture["parent"] = {"$ref": "#/tables/0/data/grid/0/0"}
    elif failure == "wrong-page":
        document["pages"]["2"] = document["pages"]["1"]
        picture["prov"][0]["page_no"] = 2
        picture["parent"] = {"$ref": "#/tables/0/data/grid/1/1"}
    elif failure == "no-cell-evidence":
        grid[0][1].pop("bbox")
    elif failure == "header-boundary":
        box.update(l=45, r=55)
    elif failure == "span-disagreement":
        grid[1][1].update(row_span=2, end_row_offset_idx=2)
    elif failure == "shape-disagreement":
        table["data"]["table_cells"] = [{"text": "contradiction"}]
    elif failure == "invalid-parent-shape":
        picture["parent"] = {"$ref": None}
    elif failure == "cell-other-page":
        grid[1][1]["page_no"] = 2
    elif failure == "contradictory-cell-box":
        picture["parent"] = {"$ref": "#/tables/0/data/grid/1/1"}
        grid[1][1]["bbox"] = {
            "l": 0,
            "t": 0,
            "r": 10,
            "b": 10,
            "coord_origin": "TOPLEFT",
        }
    elif failure == "header-role-disagreement":
        raw = copy.deepcopy(grid[0][1])
        raw.update(
            start_row_offset_idx=0,
            end_row_offset_idx=1,
            start_col_offset_idx=1,
            end_col_offset_idx=2,
            row_header=True,
            column_header=False,
        )
        table["data"]["table_cells"] = [raw]
    else:
        grid[1][1]["children"] = [{"$ref": "#/pictures/55"}]
    with pytest.raises(
        ValueError, match=r"table|image|cell|geometry|height|coordinate"
    ):
        load.load_document(document)


def test_load_keeps_multiple_images_and_unrelated_collection_figure() -> None:
    """同セル画像は本文出現順で保持し、正当なcollection補完の独立図を残す。"""

    document = _cell_image_document()
    second = copy.deepcopy(document["pictures"][0])
    second.update(self_ref="#/pictures/1", captions=[])
    outside = copy.deepcopy(second)
    outside["self_ref"] = "#/pictures/2"
    outside["prov"][0]["bbox"].update(l=110, r=120)
    document["pages"]["1"]["size"]["width"] = 200
    document["pictures"].extend([second, outside])
    document["body"]["children"].insert(0, {"$ref": "#/pictures/1"})
    result = load.load_document(document)
    assert [block.id for block in result.pages[0].blocks] == [
        "#/tables/0",
        "#/pictures/2",
    ]
    images = result.pages[0].blocks[0].cells[3].images
    assert [image.id for image in images] == ["#/pictures/1", "#/pictures/0"]
    assert [block.order for block in result.pages[0].blocks] == [0, 1]


def test_load_normalizes_repeated_grid_span_to_one_image_owner() -> None:
    """見出しの複数交点が同じ結合セルなら、span起点へ一度だけ画像を所有させる。"""

    document = _cell_image_document()
    data = document["tables"][0]["data"]
    header = data["grid"][0][1]
    header.update(start_col_offset_idx=1, end_col_offset_idx=3, col_span=2)
    data["grid"][0].append(copy.deepcopy(header))
    cell = data["grid"][1][1]
    cell.update(
        start_row_offset_idx=1,
        end_row_offset_idx=2,
        start_col_offset_idx=1,
        end_col_offset_idx=3,
        col_span=2,
    )
    data["grid"][1].append(copy.deepcopy(cell))
    data["num_cols"] = 3
    result = load.load_document(document)
    cells = result.pages[0].blocks[0].cells
    assert len(cells) == 4
    assert cells[3].colspan == 2
    assert len(cells[3].images) == 1


@pytest.mark.parametrize("failure", ["ownership", "save"])
def test_load_image_failure_preserves_artifact_and_resumes_from_checkpoint(  # noqa: PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    failure: str,
) -> None:
    """実GraphのLOAD停止と別SQLite接続からの再開を、所属不明/保存障害で検査する。"""

    def deny_network(*_args: object, **_kwargs: object) -> None:
        """LOAD境界の検査から外部サービスを呼び出さない。"""

        pytest.fail("network forbidden in LOAD test")

    def fail_save(*_args: object, **_kwargs: object) -> None:
        """成果物保存中に秘密marker付き障害を発生させる。"""

        message = "LOAD-PRIVATE-SAVE-MARKER"
        raise OSError(message)

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    settings = settings_factory(reasoning_mode="off")
    work = tmp_path / "work"
    source = tmp_path / "input.pdf"
    source.write_bytes(b"original input")
    source_hash = sha256_file(source)
    normalized = work / "normalize/document.json"
    document = _cell_image_document()
    document["texts"][0]["text"] = "LOAD-PRIVATE-SOURCE-MARKER"
    if failure == "ownership":
        document["tables"][0]["data"]["grid"][0][1].pop("bbox")
    atomic_write_json(normalized, document)
    previous = work / "load/document.json"
    atomic_write_json(previous, {"previous": True})
    before = previous.read_bytes()
    output = tmp_path / "output.docx"
    output.write_bytes(b"previous output")
    output_hash = sha256_file(output)
    config: RunnableConfig = {
        "configurable": {"thread_id": "cell-images"},
        "max_concurrency": 1,
    }
    database = work / "checkpoints.sqlite"
    save = load.atomic_write_text
    if failure == "save":
        monkeypatch.setattr(load, "atomic_write_text", fail_save)
    with open_checkpoint(database) as saver:
        graph = translation.build_graph(settings).compile(
            checkpointer=saver, interrupt_after=["load"]
        )
        graph.update_state(
            config,
            {
                "source": str(source),
                "workspace_dir": str(work),
                "normalized": str(normalized),
                "output_dir": str(tmp_path),
                "backend": "llm",
            },
            as_node="normalize",
        )
        assert graph.get_state(config).next == ("load",)
        with pytest.raises(OSError if failure == "save" else ValueError):
            graph.invoke(None, config)
        snapshot = graph.get_state(config)
        assert snapshot.next == ("load",)
        assert snapshot.tasks[0].error == "TaskError"
        evidence = repr((snapshot, saver.get_tuple(config))).encode()
    assert previous.read_bytes() == before
    assert sha256_file(output) == output_hash
    assert sha256_file(source) == source_hash
    assert not (work / "structure").exists()
    assert not list(work.glob(".load.*"))
    evidence += b"".join(path.read_bytes() for path in work.glob("checkpoints.sqlite*"))
    assert b"LOAD-PRIVATE-SOURCE-MARKER" not in evidence
    assert b"LOAD-PRIVATE-SAVE-MARKER" not in evidence

    # 合成入力だけを修復し、製品のskip台帳等を作らず同じGraph threadを再開する。
    atomic_write_json(normalized, _cell_image_document())
    monkeypatch.setattr(load, "atomic_write_text", save)
    with open_checkpoint(database) as saver:
        graph = translation.build_graph(settings).compile(
            checkpointer=saver, interrupt_after=["load"]
        )
        graph.invoke(None, config)
        assert graph.get_state(config).next == ("structure",)
    stored = json.loads(previous.read_text(encoding="utf-8"))
    assert (
        stored["pages"][0]["blocks"][0]["cells"][3]["images"][0]["id"] == "#/pictures/0"
    )
    assert sha256_file(output) == output_hash
    assert sha256_file(source) == source_hash


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
def test_uncertain_table_representation_is_not_mutated(  # noqa: C901, PLR0912
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
    if mode in {"overlap", "invalid_span"}:
        # POSITIONは原形を保つが、LOADは矛盾したshapeを丸めて成功させない。
        with pytest.raises(
            load.TableImageOwnershipError, match="table image ownership"
        ):
            load.load_document(document)
        return
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
