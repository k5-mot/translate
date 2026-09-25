"""PDF翻訳Capabilityを両BackendのTask連鎖で検証する。"""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from translate.adapters import pandoc
from translate.common.settings import load_settings
from translate.document import (
    Block,
    Document,
    Finding,
    Inline,
    Page,
    TableCell,
    page_text,
)
from translate.tasks import (
    check,
    cover,
    fix,
    markdown,
    report,
    review,
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


@pytest.mark.parametrize("backend", ["llm", "libretranslate"])
@pytest.mark.parametrize("location", ["body", "caption", "cell"])
def test_translation_fix_export_preserve_structured_code_and_links(  # noqa: PLR0915
    backend: Backend,
    location: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """両BackendとFIXを経てもCodeとhrefを保ち、ラベルは翻訳して実DOCXへ出す。"""

    values = [
        Inline(id="code", kind="code", text="print('U.S.')"),
        Inline(
            id="label", kind="link", text="U.S. manual.pdf", href="https://example.com"
        ),
    ]
    block = Block(
        id="unit", order=0, kind="paragraph" if location == "body" else "table"
    )
    if location == "body":
        block.source = values
    elif location == "caption":
        block.caption = values
        block.cells = [TableCell(row=0, column=0)]
    else:
        block.cells = [TableCell(row=0, column=0, source=values)]
    document = Document(pages=[Page(number=2, blocks=[block])])
    settings = settings_factory(libretranslate_url="https://libre.invalid")
    calls: list[str] = []

    def translate_response(
        *args: object, **_kwargs: object
    ) -> translate.TranslationResponse:
        """Codeが送信されず、通常の原文が直接送られることを検査する。"""

        calls.append("translate")
        assert isinstance(args[4], str)
        assert json.loads(args[4])["target"] == [
            {"id": "label", "text": "U.S. manual.pdf"}
        ]
        return translate.TranslationResponse(
            translations=[translate.TranslationItem(id="label", text="米国の手引書")]
        )

    def lite_response(
        _url: str, _key: str | None, texts: list[str], **_kwargs: object
    ) -> list[str]:
        """LibreTranslateにも保護記号やCodeを送らない。"""

        calls.append("translate")
        assert texts == ["U.S. manual.pdf"]
        return ["米国の手引書"]

    def review_response(*args: object, **_kwargs: object) -> review.ReviewResponse:
        """CHECKの根拠付きwarningを受け取り、モデルは追加指摘なしとする。"""

        calls.append("review")
        assert isinstance(args[4], str)
        assert json.loads(args[4])["automatic_findings"] == [
            item.model_dump() for item in checks[2]
        ]
        return review.ReviewResponse()

    def fix_response(*args: object, **_kwargs: object) -> fix.FixResponse:
        """ラベルだけを修正し、Codeが修正対象へ混入しないことを検査する。"""

        calls.append("fix")
        assert isinstance(args[4], str)
        payload = json.loads(args[4])
        assert payload["translations"] == [{"id": "label", "text": "米国の手引書"}]
        assert payload["findings"] == [item.model_dump() for item in checks[2]]
        return fix.FixResponse(revisions=[fix.Revision(id="label", text="米国の資料")])

    def verify_response(*args: object, **_kwargs: object) -> verify.VerifyResponse:
        """既存VERIFY一回だけで警告付き候補を採用する。"""

        calls.append("verify")
        assert isinstance(args[4], str)
        assert json.loads(args[4])["findings"] == [
            item.model_dump() for item in checks[2]
        ]
        return verify.VerifyResponse(approved=True)

    monkeypatch.setattr(translate, "structured", translate_response)
    monkeypatch.setattr(translate_lite, "translate_texts", lite_response)
    monkeypatch.setattr(translate, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(review, "search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(review, "structured", review_response)
    monkeypatch.setattr(fix, "structured", fix_response)
    monkeypatch.setattr(verify, "structured", verify_response)
    translated = (
        translate.run(document, "rules", [], settings, tmp_path / "translate")
        if backend == "llm"
        else translate_lite.run(document, settings, tmp_path / "translate")
    )
    checks = check.run(translated, None, tmp_path / "check")
    assert len(checks[2]) == 1
    assert checks[2][0].severity == "warning"
    assert checks[2][0].evidence == "manual.pdf"
    assert checks[2][0].target_ids
    stored = json.loads((tmp_path / "check/page-0002.json").read_text(encoding="utf-8"))
    assert stored == [item.model_dump() for item in checks[2]]
    findings = review.run(
        translated, checks, "rules", [], settings, tmp_path / "review"
    )
    assert findings == checks
    fixed = fix.run(translated, findings, "rules", settings, tmp_path / "fix")
    verified = verify.run(fixed, findings, settings, tmp_path / "verify")
    assert calls == ["translate", "review", "fix", "verify"]
    rendered = markdown.render_document(verified)
    assert "print('U.S.')" in rendered
    assert "米国の資料" in rendered
    source = tmp_path / "document.md"
    source.write_text(rendered, encoding="utf-8")
    output = tmp_path / "document.docx"
    template = load_settings("convert", env={}).templates_dir / "template.docx"
    pandoc.create_docx(source, output, template)
    assert "print('U.S.')" in pandoc.docx_to_text(output)
    assert "米国の資料" in pandoc.docx_to_text(output)
    with zipfile.ZipFile(output) as archive:
        assert (
            "https://example.com"
            in archive.read("word/_rels/document.xml.rels").decode()
        )
    report_path = report.run(
        [], checks[2], findings[2], tmp_path / "report.md", tmp_path / "report"
    )
    assert "warning / literal-reference" in report_path.read_text(encoding="utf-8")
    assert "manual.pdf" in report_path.read_text(encoding="utf-8")
    stored_report = json.loads(
        (tmp_path / "report/review.json").read_text(encoding="utf-8")
    )
    assert stored_report["counts"] == {"warning/literal-reference": 1}
    assert stored_report["findings"] == [item.model_dump() for item in checks[2]]


@pytest.mark.parametrize("failure", ["short", "long", "service"])
def test_libre_failure_keeps_input_and_existing_artifacts(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """件数不一致とサービス障害でも入力や既存成果物を部分更新しない。"""

    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="body",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="text", text="U.S.")],
                    )
                ],
            )
        ]
    )
    original = document.model_dump_json()
    output = tmp_path / "translate"
    output.mkdir()
    previous = output / "previous.json"
    previous.write_text("previous", encoding="utf-8")

    def respond(*_args: object, **_kwargs: object) -> list[str]:
        """一回のサービス障害または不正件数を返す。"""

        if failure == "service":
            message = "service unavailable"
            raise OSError(message)
        return [] if failure == "short" else ["米国", "余分"]

    monkeypatch.setattr(translate_lite, "translate_texts", respond)
    with pytest.raises(OSError if failure == "service" else ValueError):
        translate_lite.run(document, settings_factory(), output)
    assert document.model_dump_json() == original
    assert previous.read_text(encoding="utf-8") == "previous"
    assert list(output.iterdir()) == [previous]


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
