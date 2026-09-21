"""STRUCTUREのfallback、page診断およびAtomic Artifactを検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
                number=2,
                blocks=[
                    Block(
                        id="page-2-block-1",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="source-1", text="SOURCE-SENTINEL")],
                    )
                ],
            )
        ]
    )


def _render(_source: Path, page: int, output: Path) -> Path:
    assert page == 2
    output.write_bytes(b"image")
    return output


def test_structure_falls_back_to_text_after_finite_vision_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Visionの安全な最終失敗後だけTextへ逐次fallbackする。"""

    calls: list[bool] = []

    def respond(*_args: object, **kwargs: object) -> structure.StructureResponse:
        calls.append(kwargs.get("image") is not None)
        if kwargs.get("image") is not None:
            stage = "vision-invoke"
            raise LLMError(stage, TypeError("RAW-VISION-SENTINEL"))
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    output = tmp_path / "structure"

    result = structure.run(
        _document(),
        tmp_path / "source.pdf",
        "rules",
        settings_factory(),
        output,
    )

    assert result.pages[0].number == 2
    assert calls == [True, False]
    assert (output / "page-0002.json").is_file()
    assert (output / ".complete.json").is_file()


def test_structure_final_llm_failure_has_safe_page_context_and_no_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Text fallback失敗をpage単位へ正規化し未完成Directoryを除去する。"""

    sentinel = "SECRET-PROMPT-RAW-RESPONSE"
    calls: list[bool] = []

    def fail(*_args: object, **kwargs: object) -> structure.StructureResponse:
        vision = kwargs.get("image") is not None
        calls.append(vision)
        stage = "vision-invoke" if vision else "text-parse"
        raise LLMError(stage, TypeError(sentinel))

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", fail)
    output = tmp_path / "structure"

    with pytest.raises(structure.StructurePageError) as captured:
        structure.run(
            _document(),
            tmp_path / "source.pdf",
            "rules",
            settings_factory(),
            output,
        )

    assert calls == [True, False]
    assert captured.value.page == 2
    assert captured.value.target_id == "page/2"
    assert captured.value.stage == "text-parse"
    assert captured.value.cause_type == "TypeError"
    assert sentinel not in str(captured.value)
    assert "SOURCE-SENTINEL" not in str(captured.value)
    assert not output.exists()
    assert not list(tmp_path.glob(".structure.*"))


def test_structure_does_not_hide_task_programming_type_error_with_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """LLM安全Error以外のTypeErrorはText fallbackせず即時失敗する。"""

    calls = 0

    def fail(*_args: object, **_kwargs: object) -> structure.StructureResponse:
        nonlocal calls
        calls += 1
        message = "application programming error"
        raise TypeError(message)

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", fail)

    with pytest.raises(TypeError, match="application programming error"):
        structure.run(
            _document(),
            tmp_path / "source.pdf",
            "rules",
            settings_factory(),
            tmp_path / "structure",
        )

    assert calls == 1
    assert not (tmp_path / "structure").exists()
