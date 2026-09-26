"""Markdown/DOCXの構造保持とatomic公開を検証する。"""

# ruff: noqa: E501

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from translate.adapters import pandoc
from translate.document import Block, Document, Inline, Page, TableCell
from translate.tasks.markdown import render_block, render_document

if TYPE_CHECKING:
    from collections.abc import Callable


def test_markdown_preserves_heading_code_table_and_figure_structure() -> None:
    """主要なInternal Document構造をPandoc Markdownへ保持する。"""

    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="heading",
                        order=0,
                        kind="heading",
                        level=2,
                        translated=[Inline(id="h", text="見出し")],
                    ),
                    Block(
                        id="code",
                        order=1,
                        kind="code",
                        language="python",
                        translated=[Inline(id="c", text="print(1)")],
                    ),
                    Block(
                        id="table",
                        order=2,
                        kind="table",
                        cells=[
                            TableCell(
                                row=0,
                                column=0,
                                header=True,
                                translated=[Inline(id="th", text="列")],
                            ),
                            TableCell(
                                row=1,
                                column=0,
                                translated=[Inline(id="td", text="値")],
                            ),
                        ],
                    ),
                    Block(
                        id="figure",
                        order=3,
                        kind="figure",
                        asset_path="assets/figure.png",
                        alt_text="図",
                    ),
                ],
            )
        ]
    )

    rendered = render_document(document)

    assert "## 見出し" in rendered
    assert "```python" in rendered
    assert "print(1)" in rendered
    assert "列" in rendered
    assert "値" in rendered
    assert "<table>" not in rendered
    assert "+=" in rendered
    assert "assets/figure\\.png" in rendered
    assert 'fig-alt="図"' in rendered


def _fake_pandoc_run(*, valid: bool) -> Callable[..., subprocess.CompletedProcess[str]]:
    """公開前のDOCX検証を試すため、Pandocの成功/不正出力を模擬する。"""

    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        """指定された出力先へ検証用の最小containerを書き込む。"""

        output = Path(args[args.index("--output") + 1])
        if valid:
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
        else:
            output.write_bytes(b"invalid-docx")
        return subprocess.CompletedProcess(args, 0, "", "")

    return run


def _write_minimal_docx(path: Path) -> None:
    """containerの存在検証に必要な部品だけを持つDOCXを作る。"""

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")


@pytest.mark.parametrize("failure", ["missing", "invalid"])
def test_docx_failure_preserves_existing_complete_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Pandoc欠落・不正DOCXで既存完全版を上書きしない。"""

    markdown = tmp_path / "source.md"
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    markdown.write_text("# title", encoding="utf-8")
    _write_minimal_docx(template)
    output.write_bytes(b"old-complete")
    if failure == "missing":
        monkeypatch.setattr(pandoc.shutil, "which", lambda _name: None)
    else:
        monkeypatch.setattr(pandoc, "check_pandoc", lambda: None)
        monkeypatch.setattr(pandoc.shutil, "which", lambda _name: "pandoc")
        monkeypatch.setattr(pandoc.subprocess, "run", _fake_pandoc_run(valid=False))

    with pytest.raises(RuntimeError):
        pandoc.create_docx(markdown, output, template)

    assert output.read_bytes() == b"old-complete"


def test_valid_docx_is_structurally_verified_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """代替Pandocが作る最小containerを公開し、必須OOXML部品が残るか確認する。"""

    markdown = tmp_path / "source.md"
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    markdown.write_text("# title", encoding="utf-8")
    _write_minimal_docx(template)
    monkeypatch.setattr(pandoc, "check_pandoc", lambda: None)
    monkeypatch.setattr(pandoc.shutil, "which", lambda _name: "pandoc")
    monkeypatch.setattr(pandoc.subprocess, "run", _fake_pandoc_run(valid=True))

    pandoc.create_docx(markdown, output, template)

    with zipfile.ZipFile(output) as archive:
        assert {"[Content_Types].xml", "word/document.xml"} <= set(archive.namelist())


def _write_front_matter_docx(path: Path, *, external_file: bool = False) -> None:
    """Create a minimal OOXML package that exercises DOCX normalization."""

    document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
<w:body>
<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>
<w:sdtContent><w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r></w:p></w:sdtContent></w:sdt>
<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="List of Figures"/></w:docPartObj></w:sdtPr>
<w:sdtContent><w:p/></w:sdtContent></w:sdt>
<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="List of Tables"/></w:docPartObj></w:sdtPr>
<w:sdtContent><w:p/></w:sdtContent></w:sdt>
<w:p><w:r><w:drawing><wp:docPr descr="表紙"/></w:drawing></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="ImageCaption"/></w:pPr><w:r><w:t>表紙</w:t></w:r></w:p>
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>本文</w:t></w:r></w:p>
<w:sectPr/>
</w:body></w:document>"""
    if external_file:
        rels = (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="x" '
            'Target="file:///outside.docx" TargetMode="External"/>'
            "</Relationships>"
        )
    else:
        rels = (
            "<Relationships "
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", rels)


def test_docx_normalization_puts_cover_before_lists_and_removes_prompt_flags(
    tmp_path: Path,
) -> None:
    """表紙・一覧順序、表紙Captionおよびdirty fieldを正規化する。"""

    path = tmp_path / "layout.docx"
    _write_front_matter_docx(path)

    pandoc._normalize_docx(path)  # noqa: SLF001

    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))  # noqa: S314
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    body = root.find("w:body", ns)
    assert body is not None
    children = list(body)
    wp_ns = {
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    }
    assert children[0].find(".//wp:docPr", wp_ns).get("descr") == "表紙"
    assert [
        child.find(".//w:docPartGallery", ns).get(f"{{{ns['w']}}}val")
        for child in children[2:8:2]
    ] == ["Table of Contents", "List of Figures", "List of Tables"]
    assert not any(
        child.find(".//w:pStyle[@w:val='ImageCaption']", ns) is not None
        for child in children
    )
    assert not root.findall(".//*[@w:dirty]", ns)
    assert [
        "".join(node.itertext()) for node in children[2].findall("w:sdtContent/w:p", ns)
    ] == ["目次", "本文"]
    for index in (3, 5, 7):
        assert children[index].find(".//w:br[@w:type='page']", ns) is not None
    assert not root.findall(".//w:sdt//w:fldChar", ns)
    # 正規化の再実行が空欄や余分な改ページを作らないことも保証する。
    before = ET.tostring(root)
    pandoc._normalize_docx(path)  # noqa: SLF001
    with zipfile.ZipFile(path) as archive:
        assert ET.tostring(ET.fromstring(archive.read("word/document.xml"))) == before  # noqa: S314


def test_docx_normalization_rejects_external_file_relationship(tmp_path: Path) -> None:
    """Wordの外部ファイル参照は公開前に拒否する。"""

    path = tmp_path / "external.docx"
    _write_front_matter_docx(path, external_file=True)

    with pytest.raises(RuntimeError, match="external file relationship"):
        pandoc._normalize_docx(path)  # noqa: SLF001


@pytest.mark.parametrize("failure", ["markdown", "template", "output"])
def test_preflight_rejects_before_pandoc_conversion(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """入力・参照DOCX・出力先の不備では変換processを開始しない。"""

    markdown = tmp_path / "source.md"
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    markdown.write_text("# title", encoding="utf-8")
    _write_minimal_docx(template)
    output.write_bytes(b"old-complete")
    conversion_calls = 0

    def convert(*_args: object, **_kwargs: object) -> object:
        """事前検証で拒否すべきケースの変換呼出を検出する。"""

        nonlocal conversion_calls
        conversion_calls += 1
        message = "conversion must not start"
        raise AssertionError(message)

    monkeypatch.setattr(pandoc, "check_pandoc", lambda: None)
    monkeypatch.setattr(pandoc.subprocess, "run", convert)
    if failure == "markdown":
        markdown.unlink()
    elif failure == "template":
        template.write_bytes(b"invalid")
    else:
        monkeypatch.setattr(
            pandoc,
            "_validate_output_directory",
            lambda _output: (_ for _ in ()).throw(OSError("unwritable")),
        )

    with pytest.raises((ValueError, RuntimeError, OSError)):
        pandoc.create_docx(markdown, output, template)

    assert conversion_calls == 0
    assert output.read_bytes() == b"old-complete"


@pytest.mark.parametrize("failure", ["process", "replace"])
def test_conversion_and_replace_failure_clean_temporary_and_preserve_output(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """process/replace失敗でも旧完全版とcleanup済みdirectoryだけを残す。"""

    markdown = tmp_path / "source.md"
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    markdown.write_text("# title", encoding="utf-8")
    _write_minimal_docx(template)
    output.write_bytes(b"old-complete")
    monkeypatch.setattr(pandoc, "check_pandoc", lambda: None)
    monkeypatch.setattr(pandoc.shutil, "which", lambda _name: "pandoc")
    if failure == "process":

        def fail_process(*_args: object, **_kwargs: object) -> object:
            """Pandoc process失敗時の旧成果物保持を検査する。"""

            raise subprocess.CalledProcessError(1, "pandoc")

        monkeypatch.setattr(pandoc.subprocess, "run", fail_process)
    else:
        monkeypatch.setattr(pandoc.subprocess, "run", _fake_pandoc_run(valid=True))

        def fail_replace(_temporary: Path, _output: Path) -> None:
            """公開時の置換失敗を注入して一時File清掃を検査する。"""

            message = "replace failed"
            raise OSError(message)

        monkeypatch.setattr(pandoc, "_publish_docx", fail_replace)

    with pytest.raises((OSError, subprocess.CalledProcessError)):
        pandoc.create_docx(markdown, output, template)

    assert output.read_bytes() == b"old-complete"
    assert not list(tmp_path.glob(".output.*.docx"))


@pytest.mark.integration
def test_real_pandoc_preserves_required_document_structures(tmp_path: Path) -> None:
    """実Pandocで見出し・list・code・表・図・link・脚注のOOXMLと文字列を検査する。"""

    if pandoc.shutil.which("pandoc") is None:
        pytest.fail("Pandoc is required for the structure acceptance test")
    image = tmp_path / "figure.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe"
        b"\x02\xfeA\x89\x9b\x18\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    markdown = tmp_path / "source.md"
    markdown.write_text(
        """# Heading

- list item

```python
print(1)
```

| Column |
| --- |
| Value |

![Figure caption](figure.png)

[External link](https://example.com) with footnote.[^1]

[^1]: Footnote text.
""",
        encoding="utf-8",
    )
    template = Path(__file__).parents[1] / "translate" / "templates" / "template.docx"
    output = tmp_path / "result.docx"

    pandoc.create_docx(markdown, output, template)
    plain = pandoc.docx_to_text(output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        document = archive.read("word/document.xml").decode("utf-8")
        relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        assert "Heading" in document
        assert "w:pStyle" in document
        assert "w:numPr" in document
        assert "print(1)" in plain
        assert "w:tbl" in document
        assert "w:drawing" in document
        assert "Figure caption" in document
        assert "w:hyperlink" in document
        assert "https://example.com" in relationships
        assert "w:footnoteReference" in document
        assert "word/footnotes.xml" in names
        assert any(name.startswith("word/media/") for name in names)


def test_generated_table_and_indexes_survive_real_docx_conversion(
    tmp_path: Path,
) -> None:
    """製品rendererから結合表、明示改行、一覧および表紙を実変換する。"""

    picture = tmp_path / "picture.png"
    Image.new("RGB", (10, 10), "white").save(picture)
    table = Block(
        id="merged-table",
        kind="table",
        order=2,
        caption=[Inline(id="caption", text="表の題名")],
        cells=[
            TableCell(
                row=0,
                column=0,
                colspan=2,
                header=True,
                source=[Inline(id="a", text="結合見出し")],
            ),
            TableCell(
                row=1, column=0, rowspan=2, source=[Inline(id="b", text="縦結合")]
            ),
            TableCell(
                row=1,
                column=1,
                source=[
                    Inline(id="c", text="第一行"),
                    Inline(id="br", kind="line_break"),
                    Inline(id="d", text="第二行"),
                ],
            ),
            TableCell(
                row=2,
                column=1,
                source=[Inline(id="e", text="1,234.5 & <tag> | [値] ... --")],
            ),
        ],
    )
    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="h",
                        kind="heading",
                        order=0,
                        level=2,
                        source=[Inline(id="title", text="1. 見出し")],
                    ),
                    Block(
                        id="f",
                        kind="figure",
                        order=1,
                        asset_path="picture.png",
                        caption=[Inline(id="fc", text="図の題名")],
                    ),
                    table,
                    Block(
                        id="code",
                        kind="code",
                        order=3,
                        source=[Inline(id="code-text", text="# 偽の見出し")],
                    ),
                ],
            )
        ]
    )
    markdown = tmp_path / "document.md"
    markdown.write_text(render_document(document, picture), encoding="utf-8")
    template = Path(__file__).parents[1] / "translate/templates/template.docx"
    output = tmp_path / "document.docx"
    pandoc.create_docx(markdown, output, template)
    with zipfile.ZipFile(output) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))  # noqa: S314
        styles = ET.fromstring(archive.read("word/styles.xml"))  # noqa: S314
        settings = ET.fromstring(archive.read("word/settings.xml"))  # noqa: S314
    ns = {"w": pandoc.W_NS}
    tables = root.findall(".//w:tbl", ns)
    assert len(tables) == 1
    assert tables[0].find(".//w:gridSpan[@w:val='2']", ns) is not None
    assert tables[0].find(".//w:vMerge[@w:val='restart']", ns) is not None
    assert tables[0].find(".//w:br", ns) is not None
    assert "1,234.5 & <tag> | [値] ... --" in "".join(tables[0].itertext())
    indexes = root.findall(".//w:sdtContent", ns)
    assert [
        ["".join(p.itertext()) for p in index.findall("w:p", ns)] for index in indexes
    ] == [
        ["目次", "1. 見出し"],
        ["図一覧", "Figure\u00a01: 図の題名"],
        ["表一覧", "Table\u00a01: 表の題名"],
    ]
    for level in range(1, 10):
        style = styles.find(f"w:style[@w:styleId='Heading{level}']", ns)
        assert style is not None
        assert style.find("w:pPr/w:numPr", ns) is None
        assert style.find("w:pPr/w:outlineLvl", ns) is not None
    assert settings.find("w:updateFields", ns) is None
    assert not root.findall(".//*[@w:dirty]", ns)


@pytest.mark.parametrize("filename", ["picture.png", "表紙 画像.png"])
@pytest.mark.parametrize("figure_count", [0, 1, 2])
@pytest.mark.parametrize("extras", [False, True])
def test_cover_preserves_body_figure_numbers(
    tmp_path: Path, filename: str, figure_count: int, *, extras: bool
) -> None:
    """表紙の有無による採番差を実変換で検査し、画像・元Captionも保持する。"""

    picture = tmp_path / filename
    Image.new("RGB", (10, 10), "white").save(picture)
    blocks = [
        Block(
            id=f"figure-{index}",
            kind="figure",
            order=index,
            asset_path=filename,
            caption=[Inline(id=f"caption-{index}", text=f"Figure 7: 元の題名 {index}")],
        )
        for index in range(figure_count)
    ]
    if extras:
        blocks.extend(
            [
                Block(id="uncaptioned", kind="figure", order=10, asset_path=filename),
                Block(
                    id="table",
                    kind="table",
                    order=11,
                    caption=[Inline(id="tc", text="表の題名")],
                    cells=[
                        TableCell(
                            row=0, column=0, source=[Inline(id="cell", text="値")]
                        )
                    ],
                ),
            ]
        )
    document = Document(pages=[Page(number=2, blocks=blocks)])
    template = Path(__file__).parents[1] / "translate/templates/template.docx"
    ns = {
        "w": pandoc.W_NS,
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    }
    expected = [
        f"Figure\u00a0{index + 1}: Figure 7: 元の題名 {index}"
        for index in range(figure_count)
    ]
    results = []
    for with_cover in (False, True):
        markdown = tmp_path / f"document-{with_cover}.md"
        markdown.write_text(
            render_document(document, picture if with_cover else None), encoding="utf-8"
        )
        output = markdown.with_suffix(".docx")
        pandoc.create_docx(markdown, output, template)
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))  # noqa: S314
        body = root.find("w:body", ns)
        assert body is not None
        captions = [
            "".join(p.itertext())
            for p in body.findall("w:p", ns)
            if p.find("w:pPr/w:pStyle[@w:val='ImageCaption']", ns) is not None
        ]
        indexes = [
            ["".join(p.itertext()) for p in index.findall("w:p", ns)]
            for index in body.findall("w:sdt/w:sdtContent", ns)
        ]
        assert captions == expected
        assert indexes[1] == ["図一覧", *expected]
        assert indexes[2] == ["表一覧", *(["Table\u00a01: 表の題名"] if extras else [])]
        assert len(body.findall(".//wp:docPr", ns)) == figure_count + int(extras) + int(
            with_cover
        )
        results.append((captions, indexes))
        if with_cover:
            assert body[0].find(".//wp:docPr[@descr='表紙']", ns) is not None
            extent = body[0].find(".//wp:extent", ns)
            assert extent is not None
            # 修正前も同じ10 px画像は127000 EMU。幅指定と実寸を変えない。
            assert int(extent.attrib["cx"]) == 127000
            assert "{width=100%}" in markdown.read_text(encoding="utf-8")
            assert body[1].find(".//w:br[@w:type='page']", ns) is not None
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "cells",
    [
        [],
        [TableCell(row=-1, column=0)],
        [TableCell(row=0, column=0, rowspan=0)],
        [TableCell(row=0, column=0, colspan=2), TableCell(row=0, column=1)],
    ],
)
def test_invalid_table_shape_is_rejected(cells: list[TableCell]) -> None:
    """負座標、空表、不正span、結合領域の重なりを黙って変換しない。"""

    with pytest.raises(ValueError, match="invalid table shape"):
        render_block(Block(id="bad", kind="table", order=0, cells=cells))


def _convert_table_fixture(table: Block, tmp_path: Path) -> tuple[ET.Element, str]:
    """実rendererとPandocを通した本文XMLとLink参照先を返す。"""

    markdown = tmp_path / "table.md"
    markdown.write_text(render_block(table), encoding="utf-8")
    output = tmp_path / "table.docx"
    template = Path(__file__).parents[1] / "translate/templates/template.docx"
    pandoc.create_docx(markdown, output, template)
    with zipfile.ZipFile(output) as archive:
        return (
            ET.fromstring(archive.read("word/document.xml")),  # noqa: S314
            archive.read("word/_rels/document.xml.rels").decode("utf-8"),
        )


def test_header_to_body_rowspan_preserves_columns_without_repeated_header(
    tmp_path: Path,
) -> None:
    """見出し/本文をまたぐ縦結合では位置を優先し、見出しを太字にする。"""

    table = Block(
        id="crossing",
        kind="table",
        order=0,
        cells=[
            TableCell(
                row=0,
                column=0,
                rowspan=2,
                header=True,
                source=[Inline(id="merged", text="MERGED")],
            ),
            TableCell(
                row=0,
                column=1,
                header=True,
                source=[Inline(id="header", text="HEADER")],
            ),
            TableCell(row=1, column=1, source=[Inline(id="body", text="BODY")]),
        ],
    )
    root, _ = _convert_table_fixture(table, tmp_path)
    ns = {"w": pandoc.W_NS}
    rendered = root.find(".//w:tbl", ns)
    assert rendered is not None
    rows = rendered.findall("w:tr", ns)
    assert [
        ["".join(cell.itertext()) for cell in row.findall("w:tc", ns)] for row in rows
    ] == [["MERGED", "HEADER"], ["", "BODY"]]
    assert rows[0].find("w:tc/w:tcPr/w:vMerge[@w:val='restart']", ns) is not None
    assert rows[1].find("w:tc/w:tcPr/w:vMerge", ns) is not None
    assert not rendered.findall(".//w:tblHeader", ns)
    assert rows[0].find("w:tc//w:b", ns) is not None


@pytest.mark.parametrize("header_rows", [1, 2])
def test_empty_corner_multiple_headers_and_body_row_headers(
    tmp_path: Path,
    header_rows: int,
) -> None:
    """空隅セルを含む先頭見出し群と本文の行見出しを失わない。"""

    cells = [TableCell(row=0, column=0)]
    cells.append(
        TableCell(
            row=0, column=1, header=True, source=[Inline(id="head0", text="HEADER0")]
        )
    )
    if header_rows == 2:
        cells.extend(
            [
                TableCell(
                    row=1,
                    column=0,
                    header=True,
                    source=[Inline(id="sub0", text="SUB0")],
                ),
                TableCell(
                    row=1,
                    column=1,
                    header=True,
                    source=[Inline(id="sub1", text="SUB1")],
                ),
            ]
        )
    cells.extend(
        [
            TableCell(
                row=header_rows,
                column=0,
                header=True,
                source=[Inline(id="row", text="ROWHEADER")],
            ),
            TableCell(
                row=header_rows, column=1, source=[Inline(id="value", text="VALUE")]
            ),
        ]
    )
    root, _ = _convert_table_fixture(
        Block(id="headers", kind="table", order=0, cells=cells), tmp_path
    )
    ns = {"w": pandoc.W_NS}
    rendered = root.find(".//w:tbl", ns)
    assert rendered is not None
    assert len(rendered.findall("w:tr/w:trPr/w:tblHeader", ns)) == header_rows
    last_row = rendered.findall("w:tr", ns)[-1]
    assert ["".join(cell.itertext()) for cell in last_row.findall("w:tc", ns)] == [
        "ROWHEADER",
        "VALUE",
    ]
    assert last_row.find("w:tc//w:b", ns) is not None


@pytest.mark.parametrize("target", ["cell", "caption"])
def test_table_inlines_keep_links_code_marks_and_breaks(
    tmp_path: Path, target: str
) -> None:
    """表セルと表題のInlineを実DOCXのLink・Code・装飾へ保持する。"""

    inlines = [
        Inline(id="bold", text="BOLD", marks=["strong"]),
        Inline(id="italic", text="ITALIC", marks=["emphasis"]),
        Inline(id="strike", text="STRIKE", marks=["strikethrough"]),
        Inline(id="under", text="UNDER", marks=["underline"]),
        Inline(id="sub", text="SUB", marks=["subscript"]),
        Inline(id="super", text="SUPER", marks=["superscript"]),
        Inline(
            id="link",
            text="LINK",
            kind="link",
            href="https://example.com/table?x=1&y=2",
        ),
        Inline(id="code", text="x = `a`", kind="code"),
        Inline(id="br", kind="line_break"),
        Inline(id="end", text="END"),
    ]
    table = Block(
        id="inline-table",
        kind="table",
        order=0,
        caption=inlines if target == "caption" else [],
        cells=[
            TableCell(
                row=0,
                column=0,
                source=inlines if target == "cell" else [Inline(id="v", text="VALUE")],
            )
        ],
    )
    root, relationships = _convert_table_fixture(table, tmp_path)
    ns = {"w": pandoc.W_NS}
    container = (
        root.find(".//w:tbl", ns)
        if target == "cell"
        else next(
            paragraph
            for paragraph in root.findall(".//w:body/w:p", ns)
            if paragraph.find("w:pPr/w:pStyle[@w:val='TableCaption']", ns) is not None
        )
    )
    assert container is not None
    for tag in ("b", "i", "strike", "u"):
        assert container.find(f".//w:rPr/w:{tag}", ns) is not None
    for value in ("subscript", "superscript"):
        assert container.find(f".//w:vertAlign[@w:val='{value}']", ns) is not None
    assert container.find(".//w:rStyle[@w:val='VerbatimChar']", ns) is not None
    assert "x = `a`" in "".join(container.itertext())
    assert container.find(".//w:hyperlink", ns) is not None
    assert "https://example.com/table?x=1&amp;y=2" in relationships
    assert container.find(".//w:br", ns) is not None
