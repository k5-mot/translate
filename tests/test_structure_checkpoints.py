"""STRUCTUREの非公開page checkpointとTask全体の公開境界を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from translate.adapters.llm import LLMError
from translate.document import Block, Document, Inline, Page
from translate.tasks import structure

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def _document() -> Document:
    return Document(
        pages=[
            Page(
                number=number,
                blocks=[
                    Block(
                        id=f"block-{number}",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id=f"source-{number}", text=f"PAGE-{number}")],
                    )
                ],
            )
            for number in (2, 3)
        ]
    )


def _render(_source: Path, _page: int, output: Path) -> Path:
    Image.new("RGB", (8, 8), "white").save(output)
    return output


def _page_from_user(args: tuple[object, ...]) -> int:
    user = args[4]
    assert isinstance(user, str)
    return 2 if "PAGE-2" in user else 3


def test_structure_resume_reuses_only_completed_page_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """page 3失敗後のResumeではpage 2を再推論しない。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"PDF-INPUT-A")
    output = tmp_path / "structure"
    calls: list[int] = []
    failing = True

    def respond(*args: object, **_kwargs: object) -> structure.StructureResponse:
        page = _page_from_user(args)
        calls.append(page)
        if page == 3 and failing:
            stage = "vision-invoke"
            raise LLMError(stage, RuntimeError("safe"))
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    settings = settings_factory(structure_model="model-a")

    with pytest.raises(structure.StructurePageError):
        structure.run(_document(), source, "rules", settings, output)

    checkpoint = tmp_path / "structure-pages" / "page-0002"
    assert (checkpoint / ".complete.json").is_file()
    metadata = (checkpoint / "meta.json").read_text(encoding="utf-8")
    assert all(value not in metadata for value in ("PAGE-2", "PDF-INPUT-A", "model-a"))
    assert not output.exists()
    assert calls == [2, 3, 3]

    failing = False
    result = structure.run(_document(), source, "rules", settings, output)

    assert [page.number for page in result.pages] == [2, 3]
    assert calls == [2, 3, 3, 3]
    assert (output / ".complete.json").is_file()
    assert (output / "page-0002.json").is_file()
    assert (output / "page-0003.json").is_file()
    assert (output / "document.json").is_file()


@pytest.mark.parametrize("change", ["source", "model", "corrupt"])
def test_structure_reprocesses_incompatible_or_corrupt_page_checkpoint(
    change: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """入力、Modelまたはpage内容が不一致なら旧結果を採用しない。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"PDF-INPUT-A")
    output = tmp_path / "structure"
    calls: list[int] = []
    failing = True

    def respond(*args: object, **_kwargs: object) -> structure.StructureResponse:
        page = _page_from_user(args)
        calls.append(page)
        if page == 3 and failing:
            stage = "vision-invoke"
            raise LLMError(stage, RuntimeError("safe"))
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    settings = settings_factory(structure_model="model-a")

    with pytest.raises(structure.StructurePageError):
        structure.run(_document(), source, "rules", settings, output)

    checkpoint = tmp_path / "structure-pages" / "page-0002"
    assert checkpoint.is_dir()
    if change == "source":
        source.write_bytes(b"PDF-INPUT-B")
    elif change == "model":
        settings = settings_factory(structure_model="model-b")
    else:
        (checkpoint / "page.json").write_text("broken", encoding="utf-8")

    failing = False
    structure.run(_document(), source, "rules", settings, output)

    assert calls.count(2) == 2
    assert (output / ".complete.json").is_file()


def test_structure_old_run_without_page_progress_starts_normally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """旧Runにpage progressがなくても全pageを一度ずつ処理する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"PDF-INPUT-A")
    calls: list[int] = []

    def respond(*args: object, **_kwargs: object) -> structure.StructureResponse:
        calls.append(_page_from_user(args))
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    output = tmp_path / "structure"

    structure.run(_document(), source, "rules", settings_factory(), output)

    assert calls == [2, 3]
    assert (output / ".complete.json").is_file()
