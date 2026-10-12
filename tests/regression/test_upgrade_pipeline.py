"""Upgrade PipelineのTask接続、成果物およびResume契約を検証する。"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from translate.artifact_store import (
    describe_artifact,
    load_model,
    sha256_file,
    write_model,
)
from translate.common.config import Config
from translate.models.artifacts import (
    CoverResult,
    DoclingManifest,
    LintResult,
    SplitManifest,
    UnpackManifest,
)
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.models.upgrade import UpgradePlan, UpgradeRecord
from translate.pipeline import upgrade

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _document(identifier: str, text: str) -> Document:
    """一つの本文TextUnitを持つPipeline test用文書を作る。"""

    return Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id=f"block-{identifier}",
                        order=0,
                        kind="paragraph",
                        content=TextUnit(
                            id=identifier,
                            spans=[TextSpan(id=f"span-{identifier}", source=text)],
                        ),
                    )
                ],
            )
        ]
    )


def test_upgrade_pipeline_reuses_translation_and_resumes(  # noqa: C901, PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同文の日本語v1を再利用し、DOCXだけを公開してResumeでは再実行しない。"""

    calls: Counter[str] = Counter()
    source_v1 = tmp_path / "source-v1.pdf"
    source_v2 = tmp_path / "source-v2.pdf"
    translation_v1 = tmp_path / "translation-v1.pdf"
    for path in (source_v1, source_v2, translation_v1):
        path.write_bytes(path.name.encode())
    documents = {
        source_v1.name: _document("source-v1", "Stable text"),
        source_v2.name: _document("source-v2", "Stable text"),
        translation_v1.name: _document("translation-v1", "安定した文章"),
    }
    documents[source_v2.name].pages[0].blocks.append(
        Block(
            id="block-removed",
            order=1,
            kind="paragraph",
            content=TextUnit(
                id="removed",
                spans=[TextSpan(id="span-removed", source="Structure removes this")],
            ),
        )
    )

    def fake_split(
        source: Path, directory: Path, _root: Path, _pages: int
    ) -> SplitManifest:
        """外部PDF分割の代わりに空partの有効Manifestを保存する。"""

        calls["split"] += 1
        result = SplitManifest(
            source_sha256=sha256_file(source), total_pages=1, parts=[]
        )
        write_model(directory / "manifest.json", result)
        return result

    def fake_docling(
        _manifest: SplitManifest,
        directory: Path,
        _root: Path,
        _config: Config,
    ) -> DoclingManifest:
        """Docling外部接続を空の有効Manifestへ置き換える。"""

        calls["docling"] += 1
        result = DoclingManifest(parts=[])
        write_model(directory / "manifest.json", result)
        return result

    def fake_unpack(
        _manifest: DoclingManifest, directory: Path, _root: Path
    ) -> UnpackManifest:
        """archive展開を空の有効Manifestへ置き換える。"""

        calls["unpack"] += 1
        result = UnpackManifest(parts=[])
        write_model(directory / "manifest.json", result)
        return result

    def fake_merge(
        _manifest: UnpackManifest,
        source: Path,
        directory: Path,
        _root: Path,
    ) -> Path:
        """入力roleに対応する内部DocumentをMERGE成果として保存する。"""

        calls["merge"] += 1
        path = directory / "document.json"
        write_model(path, documents[source.name])
        return path

    def fake_transform(source: Path, directory: Path) -> Path:
        """POSITION、NORMALIZE、LOADを検証済みDocumentの複製に置き換える。"""

        calls["transform"] += 1
        path = directory / "document.json"
        write_model(path, load_model(source, Document))
        return path

    def fake_structure(
        document: Document,
        _source: Path,
        directory: Path,
        _root: Path,
        _config: Config,
        _rules: str,
    ) -> Document:
        """LLM接続なしで英文v2の不要単位を除いた構造を保存する。"""

        calls["structure"] += 1
        structured = document.model_copy(deep=True)
        structured.pages[0].blocks.pop()
        write_model(directory / "document.json", structured)
        return structured

    def fake_lint(_document: Document, _assets: Path) -> LintResult:
        """公開構造を有効とする固定LINT結果を返す。"""

        calls["lint"] += 1
        return LintResult(valid=True, document_sha256="0" * 64, diagnostics=[])

    def fake_cover(_source: Path, directory: Path, root: Path) -> CoverResult:
        """表紙画像とManifestの最小成果物を保存する。"""

        calls["cover"] += 1
        image = directory / "cover.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"png")
        result = CoverResult(
            image=describe_artifact(root, image),
            width=1,
            height=1,
            excluded_page_numbers=[1],
        )
        write_model(directory / "manifest.json", result)
        return result

    def fake_markdown(
        _document: Document,
        output: Path,
        _cover: Path,
        _assets: Path,
        _excluded: set[int],
        _timeout: float,
    ) -> Path:
        """Pandoc入力となる中間Markdownを保存する。"""

        calls["markdown"] += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("日本語v2", encoding="utf-8")
        return output

    def fake_publish(
        _markdown: Path, output: Path, _template: Path, _timeout: float
    ) -> Path:
        """Pandoc実行を固定DOCX byte列へ置き換える。"""

        calls["docx"] += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"docx")
        return output

    for name, value in (
        ("split", fake_split),
        ("convert_with_docling", fake_docling),
        ("unpack", fake_unpack),
        ("merge", fake_merge),
        ("position", fake_transform),
        ("normalize", fake_transform),
        ("load", fake_transform),
        ("structure", fake_structure),
        ("lint", fake_lint),
        ("create_cover", fake_cover),
        ("convert_document", fake_markdown),
        ("publish", fake_publish),
    ):
        monkeypatch.setattr(upgrade, name, value)

    config = Config(
        docling_server_url="http://docling",
        libretranslate_url="http://libretranslate",
        openai_base_url="http://llm/v1",
        openai_structure_model="structure",
        openai_review_model="review",
    )
    outcome = upgrade.upgrade_pdfs(
        source_v1,
        source_v2,
        translation_v1,
        config,
        backend="libretranslate",
        outputs=tmp_path / "outputs",
    )
    before_resume = calls.copy()
    resumed = upgrade.upgrade_pdfs(
        source_v1,
        source_v2,
        translation_v1,
        config,
        backend="libretranslate",
        resume_id=outcome.upgrade_id,
        outputs=tmp_path / "outputs",
    )

    record = load_model(outcome.processing_directory / "upgrade.json", UpgradeRecord)
    plan = load_model(
        outcome.processing_directory / "upgrade/diff/plan.json", UpgradePlan
    )
    assert {
        identifier for change in plan.changes for identifier in change.source_v2_ids
    } == {"source-v2"}
    assert outcome.docx.read_bytes() == b"docx"
    assert resumed.docx == outcome.docx
    assert calls == before_resume
    assert [item.relative_path for item in record.outputs] == [
        "publisher/docx/document.ja.docx"
    ]
    assert record.source_v1.role == "source_v1"
    assert record.source_v2.role == "source_v2"
    assert record.translation_v1.role == "translation_v1"
    assert (
        next(
            item for item in record.tasks if item.task.value == "TRANSLATE_LITE"
        ).status
        == "skipped"
    )
    assert (
        next(item for item in record.tasks if item.task.value == "REVIEW").status
        == "skipped"
    )
