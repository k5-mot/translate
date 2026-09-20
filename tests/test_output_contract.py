"""Markdown/DOCXの構造保持とatomic公開を検証する。"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from translate.adapters import pandoc
from translate.document import Block, Document, Inline, Page, TableCell
from translate.tasks.markdown import render_document

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
    assert "<th>列</th>" in rendered
    assert "<td>値</td>" in rendered
    assert "assets/figure\\.png" in rendered
    assert 'fig-alt="図"' in rendered


def _fake_pandoc_run(*, valid: bool) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
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
    """必須OOXML部品を持つDOCXだけを最終pathへ公開する。"""

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
            raise subprocess.CalledProcessError(1, "pandoc")

        monkeypatch.setattr(pandoc.subprocess, "run", fail_process)
    else:
        monkeypatch.setattr(pandoc.subprocess, "run", _fake_pandoc_run(valid=True))

        def fail_replace(_temporary: Path, _output: Path) -> None:
            message = "replace failed"
            raise OSError(message)

        monkeypatch.setattr(pandoc, "_publish_docx", fail_replace)

    with pytest.raises((OSError, subprocess.CalledProcessError)):
        pandoc.create_docx(markdown, output, template)

    assert output.read_bytes() == b"old-complete"
    assert not list(tmp_path.glob(".output.*.docx"))


@pytest.mark.integration
def test_real_pandoc_preserves_required_document_structures(tmp_path: Path) -> None:
    """実PandocのDOCXに全要求要素のOOXML表現が存在する。"""

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
