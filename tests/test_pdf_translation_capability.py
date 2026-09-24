"""PDF翻訳Capabilityを両BackendのTask連鎖で検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from translate.document import Block, Document, Finding, Inline, Page, page_text
from translate.tasks import (
    check,
    cover,
    fix,
    markdown,
    structure,
    translate,
    translate_lite,
    validate,
    verify,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Backend, Settings


def test_fix_and_verify_adopt_valid_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """固定の修正応答と承認応答を与え、候補が最終訳へ採用されるか確認する。"""

    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="body",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="source", text="Source")],
                        translated=[Inline(id="target", text="修正前")],
                    )
                ],
            )
        ]
    )
    findings = {2: [Finding(kind="accuracy", target_ids=["target"], message="要修正")]}
    settings = settings_factory(fix_model="fix", review_model="review")
    monkeypatch.setattr(
        fix,
        "structured",
        lambda *_args, **_kwargs: fix.FixResponse(
            revisions=[fix.Revision(id="target", text="修正後")]
        ),
    )
    monkeypatch.setattr(
        verify,
        "structured",
        lambda *_args, **_kwargs: verify.VerifyResponse(approved=True),
    )

    fixed = fix.run(document, findings, "rules", settings, tmp_path / "fix")
    verified = verify.run(fixed, findings, settings, tmp_path / "verify")

    final = verified.pages[0].blocks[0].final
    assert final is not None
    assert final[0].text == "修正後"
    assert final[0].fix_status == "fixed"


@pytest.mark.integration
@pytest.mark.parametrize("backend", ["llm", "libretranslate"])
def test_translation_capability_preserves_contract_with_fix_fallback(  # noqa: PLR0915
    backend: Backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """表紙、構造、保護対象、検査およびFIX/VERIFY fallbackを一続きで通す。"""

    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="cover-body",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="cover-text", text="COVER-BODY-SENTINEL")],
                    )
                ],
            ),
            Page(
                number=2,
                blocks=[
                    Block(
                        id="heading",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="heading-text", text="Installation")],
                    ),
                    Block(
                        id="body",
                        order=1,
                        kind="paragraph",
                        source=[
                            Inline(
                                id="body-text",
                                text=(
                                    "Use https://example.com with 10 MB "
                                    "and `tool --safe`."
                                ),
                            )
                        ],
                    ),
                ],
            ),
        ]
    )
    templates = tmp_path / "templates"
    templates.mkdir()
    settings = settings_factory(
        templates_dir=templates,
        translation_model="translation",
        review_model="review",
        fix_model="fix",
        libretranslate_url="https://libre.invalid",
    )
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"readable fixture")

    def render_page(_source: Path, _page: int, output: Path, **_kwargs: object) -> Path:
        """構造推定と表紙Taskに検証可能なPNGを供給し、実PDF描画への依存を除く。"""

        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), "white").save(output)
        return output

    monkeypatch.setattr(structure.pdf, "render_page", render_page)
    monkeypatch.setattr(
        structure,
        "structured",
        lambda *_args, **_kwargs: structure.StructureResponse(
            patches=[
                structure.StructurePatch(
                    block_id="heading", kind="heading", level=1, reason="fixture"
                )
            ]
        ),
    )
    structured = structure.run(
        document, source_pdf, "structure rules", settings, tmp_path / "structure"
    )
    assert structured.pages[1].blocks[0].kind == "heading"
    assert structured.pages[1].blocks[0].level == 1

    if backend == "llm":

        def translate_response(
            *_args: object, **_kwargs: object
        ) -> translate.TranslationResponse:
            """
            URL・数量・codeを保持した固定訳を返し、後続検査とfallbackの基準にする。
            """

            return translate.TranslationResponse(
                translations=[
                    translate.TranslationItem(id="heading-text", text="インストール"),
                    translate.TranslationItem(
                        id="body-text",
                        text=(
                            "https://example.com を 10 MB と "
                            "`tool --safe` で使用します。"
                        ),
                    ),
                ]
            )

        monkeypatch.setattr(translate, "structured", translate_response)
        translated = translate.run(
            structured, "translation rules", [], settings, tmp_path / "translate"
        )
    else:
        monkeypatch.setattr(
            translate_lite,
            "translate_texts",
            lambda _url, _key, texts, **_kwargs: [f"訳: {text}" for text in texts],
        )
        translated = translate_lite.run(structured, settings, tmp_path / "translate")

    translated_text = page_text(translated.pages[1], final=False)
    for protected in ("https://example.com", "10 MB", "`tool --safe`"):
        assert protected in translated_text
    deterministic = check.run(translated, None, tmp_path / "check")
    assert not deterministic[2]

    findings = {
        2: [
            Finding(
                kind="style",
                target_ids=["body-text"],
                message="fallbackを検証する指摘",
            )
        ]
    }

    sensitive = "SECRET-BODY-SENTINEL"

    def service_failure(*_args: object, **_kwargs: object) -> object:
        """秘密値を含むFIX/VERIFY障害を発生させ、初回訳の保持と安全な診断を検証する。"""

        message = f"token=credential {sensitive}"
        raise OSError(message)

    monkeypatch.setattr(fix, "structured", service_failure)
    monkeypatch.setattr(verify, "structured", service_failure)
    fixed = fix.run(translated, findings, "review rules", settings, tmp_path / "fix")
    verified = verify.run(fixed, findings, settings, tmp_path / "verify")
    assert page_text(verified.pages[1]) == translated_text
    assert all(
        item.fix_status == "skipped"
        for block in verified.pages[1].blocks
        for item in block.final or []
    )
    errors = [
        item.fix_error
        for block in verified.pages[1].blocks
        for item in block.final or []
        if item.fix_error
    ]
    assert errors
    assert all("page=2" in error and "body-text" in error for error in errors)
    assert all("OSError" in error and sensitive not in error for error in errors)

    validation = tmp_path / "validate" / "report.json"
    validate.run(verified, tmp_path / "assets", validation)
    report = json.loads(validation.read_text(encoding="utf-8"))
    assert report["valid"] is True
    assert report["warnings"]

    monkeypatch.setattr(cover, "render_page", render_page)
    cover_path = cover.run(source_pdf, tmp_path / "cover" / "cover.png")
    markdown_path = markdown.run(
        verified,
        tmp_path / "markdown" / "document.ja.md",
        cover_path,
        tmp_path / "assets",
    )
    output = markdown_path.read_text(encoding="utf-8")
    assert output.count("![表紙](") == 1
    assert "COVER-BODY-SENTINEL" not in output
    assert "https://example" in output
