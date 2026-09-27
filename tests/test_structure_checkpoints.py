"""STRUCTUREの既存Page Cacheと公開境界を検査する。LangGraph統合の証拠ではない。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from translate_v1.adapters.llm import LLMError
from translate_v1.document import Block, Document, Inline, Page
from translate_v1.tasks import structure

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate_v1.common.settings import Settings


def _document() -> Document:
    """
    ページ2・3を本文markerで区別できる文書を作り、再推論したページを追跡可能にする。
    """

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
    """実PDFを描画せず小さなPNGを用意し、構造推定の再開試験を入力画像から独立させる。"""

    Image.new("RGB", (8, 8), "white").save(output)
    return output


def _page_from_user(args: tuple[object, ...]) -> int:
    """
    構造推定prompt内のfixture markerから対象ページを読み取り、モデル呼出履歴に使う。
    """

    user = args[4]
    assert isinstance(user, str)
    return 2 if "PAGE-2" in user else 3


def test_structure_page_key_tracks_generation_policy_and_schema(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """生成policyとResponse schemaの変更が既存Page Cacheのkeyを変えるか検査する。"""

    page = _document().pages[0]
    settings = settings_factory(structure_model="model-a")
    baseline = structure._page_key(page, "source-hash", "rules", settings)  # noqa: SLF001

    assert structure.PAGE_CHECKPOINT_VERSION == 4
    assert structure.STRUCTURE_THINKING_BUDGET_TOKENS == 0
    with monkeypatch.context() as scoped:
        scoped.setattr(structure, "STRUCTURE_REASONING_EFFORT", "low", raising=False)
        assert (
            structure._page_key(page, "source-hash", "rules", settings)  # noqa: SLF001
            != baseline
        )
    with monkeypatch.context() as scoped:
        scoped.setattr(structure, "STRUCTURE_SCHEMA_MODE", "prompt", raising=False)
        assert (
            structure._page_key(page, "source-hash", "rules", settings)  # noqa: SLF001
            != baseline
        )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            structure, "STRUCTURE_THINKING_POLICY", "provider-default", raising=False
        )
        assert (
            structure._page_key(page, "source-hash", "rules", settings)  # noqa: SLF001
            != baseline
        )
    with monkeypatch.context() as scoped:
        scoped.setattr(structure, "STRUCTURE_THINKING_BUDGET_TOKENS", 1, raising=False)
        assert (
            structure._page_key(page, "source-hash", "rules", settings)  # noqa: SLF001
            != baseline
        )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            structure.StructureResponse,
            "model_json_schema",
            classmethod(
                lambda _cls: {
                    "type": "object",
                    "properties": {"changed": {"type": "boolean"}},
                }
            ),
        )
        assert (
            structure._page_key(page, "source-hash", "rules", settings)  # noqa: SLF001
            != baseline
        )


def test_structure_resume_reuses_only_completed_page_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Task直接再呼出時に、失敗したpage 3だけを推論し成功済みpage 2を再利用する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"PDF-INPUT-A")
    output = tmp_path / "structure"
    calls: list[int] = []
    failing = True

    def respond(*args: object, **_kwargs: object) -> structure.StructureResponse:
        """
        ページ3だけを停止条件付きで失敗させ、既存Page Cacheの再利用範囲を呼出履歴で調べ
        る。
        """

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
        """
        ページ2成功後にページ3を失敗させ、条件変更後の再推論を記録できる中断状態を作る。
        """

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
    """既存Page Cacheのない新規保存先では、両pageを一度ずつ順番に処理する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"PDF-INPUT-A")
    calls: list[int] = []

    def respond(*args: object, **_kwargs: object) -> structure.StructureResponse:
        """
        ページごとに正常な空patchを返し、既存Page記録なしでの初回処理順を記録する。
        """

        calls.append(_page_from_user(args))
        return structure.StructureResponse()

    monkeypatch.setattr(structure.pdf, "render_page", _render)
    monkeypatch.setattr(structure, "structured", respond)
    output = tmp_path / "structure"

    structure.run(_document(), source, "rules", settings_factory(), output)

    assert calls == [2, 3]
    assert (output / ".complete.json").is_file()
