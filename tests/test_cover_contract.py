"""表紙画像と第1ページ本文の排他契約を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from translate.document import Block, Document, Inline, Page
from translate.tasks import cover, markdown

if TYPE_CHECKING:
    from pathlib import Path


def _fake_render(_source: Path, _page: int, output: Path, dpi: int = 120) -> Path:
    assert dpi > 0
    Image.new("RGB", (10, 10), "white").save(output, format="PNG")
    return output


def test_cover_manifest_excludes_first_page_from_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """表紙画像を一度出力し、対応する本文はMarkdownへ含めない。"""

    monkeypatch.setattr(cover, "render_page", _fake_render)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    cover_path = cover.run(source, tmp_path / "cover" / "cover.png")
    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="page-1",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="first", text="FIRSTPAGEBODY")],
                    )
                ],
            ),
            Page(
                number=2,
                blocks=[
                    Block(
                        id="page-2",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="second", text="SECONDPAGEBODY")],
                    )
                ],
            ),
        ]
    )

    result = markdown.run(document, tmp_path / "markdown" / "result.md", cover_path)
    rendered = result.read_text(encoding="utf-8")

    assert rendered.count("![表紙]") == 1
    assert "FIRSTPAGEBODY" not in rendered
    assert rendered.count("SECONDPAGEBODY") == 1


def test_cover_failure_preserves_previous_artifact_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COVER失敗時に不完全成果物を公開せず旧完全版を保持する。"""

    output = tmp_path / "cover" / "cover.png"
    output.parent.mkdir()
    output.write_bytes(b"old-complete")

    def fail(*_args: object, **_kwargs: object) -> Path:
        msg = "injected COVER failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(cover, "render_page", fail)

    with pytest.raises(RuntimeError, match="COVER"):
        cover.run(tmp_path / "source.pdf", output)

    assert output.read_bytes() == b"old-complete"
    assert not list(tmp_path.glob(".cover.*"))
