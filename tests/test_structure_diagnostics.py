"""STRUCTUREのfallback、page診断およびAtomic Artifactを検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image, ImageDraw

from translate.adapters.llm import LLMError
from translate.document import Block, Document, Inline, Page
from translate.tasks import cover, structure

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
    Image.new("RGB", (8, 8), "white").save(output)
    return output


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"PDF-FIXTURE")
    return source


@pytest.mark.parametrize(
    "case",
    [
        (0, ConnectionError, 1, True),
        (1, ConnectionError, 2, True),
        (2, ConnectionError, 2, False),
        (1, TimeoutError, 1, False),
    ],
)
def test_structure_request_preserves_typed_arguments_and_retry_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    case: tuple[int, type[Exception], int, bool],
) -> None:
    """型付き転送でも同じ引数で最大一回だけ接続断を再送する。"""

    failures, cause, expected_calls, succeeds = case
    settings = settings_factory()
    expected = structure.StructureResponse()
    args = (settings, "model", structure.StructureResponse, "rules", "body")
    kwargs = {
        "reasoning": "none",
        "schema_mode": "json-schema",
        "thinking": "disabled",
        "image": tmp_path / "page.png",
    }
    calls = []
    failure = LLMError("vision-invoke", cause("private body"))

    def invoke(*actual: object, **options: object) -> structure.StructureResponse:
        calls.append((actual, options))
        if len(calls) <= failures:
            raise failure
        return expected

    monkeypatch.setattr(structure, "structured", invoke)
    if succeeds:
        assert structure._structure_request(*args, **kwargs) is expected  # noqa: SLF001
    else:
        with pytest.raises(LLMError) as raised:
            structure._structure_request(*args, **kwargs)  # noqa: SLF001
        assert raised.value is failure
    assert calls == [(args, kwargs)] * expected_calls


def test_structure_bounds_vision_image_without_cropping(tmp_path: Path) -> None:
    """大きな画像だけを全page保持のまま上限内へ縮小する。"""

    image = tmp_path / "page.png"
    with Image.new("RGB", (2000, 1000), "white") as original:
        draw = ImageDraw.Draw(original)
        for box, color in (
            ((0, 0, 100, 100), "red"),
            ((1899, 0, 1999, 100), "green"),
            ((0, 899, 100, 999), "blue"),
            ((1899, 899, 1999, 999), "yellow"),
        ):
            draw.rectangle(box, fill=color)
        original.save(image)

    structure._bound_image(image)  # noqa: SLF001

    with Image.open(image) as bounded:
        assert bounded.width * bounded.height <= 1_000_000
        assert abs(bounded.width / bounded.height - 2) < 0.01
        assert [
            bounded.getpixel(point)
            for point in (
                (0, 0),
                (bounded.width - 1, 0),
                (0, bounded.height - 1),
                (bounded.width - 1, bounded.height - 1),
            )
        ] == [(255, 0, 0), (0, 128, 0), (0, 0, 255), (255, 255, 0)]


def test_structure_leaves_small_image_and_cover_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STRUCTUREの上限は既存の小画像とCOVERの150 DPIへ影響しない。"""

    image = tmp_path / "small.png"
    Image.new("RGB", (500, 600), "white").save(image)
    before = image.read_bytes()
    structure._bound_image(image)  # noqa: SLF001
    assert image.read_bytes() == before

    seen_dpi: list[int] = []

    def render_cover(_source: Path, _page: int, output: Path, *, dpi: int) -> Path:
        seen_dpi.append(dpi)
        Image.new("RGB", (8, 8), "white").save(output)
        return output

    monkeypatch.setattr(cover, "render_page", render_cover)
    cover.run(tmp_path / "source.pdf", tmp_path / "cover" / "cover.png")
    assert seen_dpi == [150]


def test_structure_uses_text_when_image_cannot_be_prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """画像化できないpageは本文だけの完全応答で回復する。"""

    calls: list[bool] = []

    def fail_render(_source: Path, _page: int, output: Path) -> Path:
        output.write_bytes(b"partial")
        message = "image unavailable"
        raise OSError(message)

    def respond(*_args: object, **kwargs: object) -> structure.StructureResponse:
        calls.append(kwargs.get("image") is not None)
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", fail_render)
    monkeypatch.setattr(structure, "structured", respond)
    output = tmp_path / "structure"

    structure.run(_document(), _source(tmp_path), "rules", settings_factory(), output)

    assert calls == [False]
    assert not list(output.glob("*.png"))
    assert (output / "document.json").is_file()


def test_structure_falls_back_to_text_after_finite_vision_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Visionの安全な最終失敗後だけTextへ逐次fallbackする。"""

    calls: list[tuple[bool, object, object, object]] = []

    def respond(*_args: object, **kwargs: object) -> structure.StructureResponse:
        calls.append(
            (
                kwargs.get("image") is not None,
                kwargs.get("reasoning"),
                kwargs.get("schema_mode"),
                kwargs.get("thinking"),
            )
        )
        if kwargs.get("image") is not None:
            stage = "vision-invoke"
            raise LLMError(stage, TypeError("RAW-VISION-SENTINEL"))
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    output = tmp_path / "structure"

    result = structure.run(
        _document(),
        _source(tmp_path),
        "rules",
        settings_factory(),
        output,
    )

    assert result.pages[0].number == 2
    assert calls == [
        (True, "none", "json-schema", "disabled"),
        (False, "none", "json-schema", "disabled"),
    ]
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
            _source(tmp_path),
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
            _source(tmp_path),
            "rules",
            settings_factory(),
            tmp_path / "structure",
        )

    assert calls == 1
    assert not (tmp_path / "structure").exists()


def test_structure_uses_text_only_after_vision_output_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """切れたVision結果を捨て、一度だけTextの完全応答へ切り替える。"""

    calls: list[bool] = []

    def respond(*_args: object, **kwargs: object) -> structure.StructureResponse:
        vision = kwargs.get("image") is not None
        calls.append(vision)
        if vision:
            stage = "vision-output"
            raise LLMError(
                stage,
                RuntimeError("RAW-TRUNCATED-SENTINEL"),
                failure_kind="output-truncated",
                finish_reason="length",
            )
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    output = tmp_path / "structure"

    result = structure.run(
        _document(),
        _source(tmp_path),
        "rules",
        settings_factory(),
        output,
    )

    assert result.pages[0].number == 2
    assert calls == [True, False]
    assert (output / ".complete.json").is_file()


def test_structure_stops_when_vision_and_text_both_truncate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """両modeの出力枯渇では最終stageだけを安全に公開する。"""

    calls: list[tuple[bool, object]] = []

    def fail(*_args: object, **kwargs: object) -> structure.StructureResponse:
        vision = kwargs.get("image") is not None
        calls.append((vision, kwargs.get("schema_mode")))
        raise LLMError(
            "vision-output" if vision else "text-output",
            RuntimeError("RAW-TRUNCATED-SENTINEL"),
            failure_kind="output-truncated",
            finish_reason="length",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
        )

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", fail)

    with pytest.raises(structure.StructurePageError) as captured:
        structure.run(
            _document(),
            _source(tmp_path),
            "rules",
            settings_factory(),
            tmp_path / "structure",
        )

    assert calls == [
        (True, "json-schema"),
        (False, "json-schema"),
        (False, "prompt"),
    ]
    assert captured.value.stage == "text-output"
    assert captured.value.failure_kind == "output-truncated"
    assert captured.value.finish_reason == "length"
    assert "RAW-TRUNCATED-SENTINEL" not in str(captured.value)
    assert not (tmp_path / "structure").exists()


def test_structure_recovers_text_truncation_with_prompt_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Text json-schema枯渇後だけprompt modeへ一度切り替える。"""

    calls: list[tuple[bool, object]] = []

    def respond(*_args: object, **kwargs: object) -> structure.StructureResponse:
        vision = kwargs.get("image") is not None
        schema_mode = kwargs.get("schema_mode")
        calls.append((vision, schema_mode))
        if vision:
            stage = "vision-output"
            raise LLMError(
                stage,
                RuntimeError("VISION-TRUNCATED"),
                failure_kind="output-truncated",
                finish_reason="length",
            )
        if schema_mode == "json-schema":
            stage = "text-output"
            raise LLMError(
                stage,
                RuntimeError("SCHEMA-TRUNCATED"),
                failure_kind="output-truncated",
                finish_reason="length",
            )
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    output = tmp_path / "structure"

    result = structure.run(
        _document(),
        _source(tmp_path),
        "rules",
        settings_factory(),
        output,
    )

    assert result.pages[0].number == 2
    assert calls == [
        (True, "json-schema"),
        (False, "json-schema"),
        (False, "prompt"),
    ]
    assert (output / "page-0002.json").is_file()
    assert (output / ".complete.json").is_file()
