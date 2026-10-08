"""Pipeline外部境界を置換して実Streamlit UIを起動するE2E driver。"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from translate import ui
from translate.artifact_store import describe_artifact, sha256_file, write_model
from translate.common.config import Config
from translate.models.artifacts import (
    InputFile,
    LLMCallArtifact,
    RegistrationRecord,
    RegistrationResult,
    RegistrationSourceResult,
    ReviewRecord,
    TaskName,
    TaskState,
    TranslationRecord,
)
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.models.upgrade import UpgradeRecord
from translate.pipeline.register import RegistrationOutcome
from translate.pipeline.review import ReviewOutcome
from translate.pipeline.translate import TranslationOutcome
from translate.pipeline.upgrade import UpgradeOutcome
from translate.tasks.translation.translate import TranslationItem, TranslationResponse


def _input(path: Path, role: str) -> InputFile:
    """staged uploadから最上位記録用InputFileを作る。"""

    return InputFile(
        role=role,
        logical_path=path.name,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def _write_translation_progress(
    root: Path,
    source: Path,
    processing_id: str,
    backend: str,
) -> None:
    """処理中Callから確定Callへ変わるUI用Artifactを時間差で公開する。"""

    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block-1",
                        order=0,
                        kind="paragraph",
                        content=TextUnit(
                            id="unit-1",
                            spans=[TextSpan(id="span-1", source="English")],
                        ),
                    )
                ],
            )
        ]
    )
    write_model(root / "preprocess/structure/document.json", document)
    call_dir = root / "translation/translate/calls/call-1"
    now = datetime.now(UTC)
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="TRANSLATE",
            status="processing",
            fingerprint="translate-1",
            target_ids=["span-1"],
            attempts=1,
            started_at=now,
            updated_at=now,
        ),
    )
    write_model(
        root / "translation.json",
        TranslationRecord(
            translation_id=processing_id,
            status="processing",
            source=_input(source, "source"),
            backend=backend,
            tasks=[
                TaskState(
                    task=TaskName.TRANSLATE,
                    status="processing",
                    fingerprint="translate",
                    started_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        ),
    )
    time.sleep(1.2)
    write_model(
        call_dir / "response.json",
        TranslationResponse(
            translations=[TranslationItem(span_id="span-1", text="日本語")]
        ),
    )
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="TRANSLATE",
            status="partial",
            fingerprint="translate-1",
            target_ids=["span-1"],
            attempts=1,
            response_sha256=sha256_file(call_dir / "response.json"),
            started_at=now,
            updated_at=datetime.now(UTC),
        ),
    )
    next_call = root / "translation/translate/calls/call-2/call.json"
    write_model(
        next_call,
        LLMCallArtifact(
            call_id="call-2",
            task="TRANSLATE",
            status="processing",
            fingerprint="translate-2",
            target_ids=["span-1"],
            attempts=1,
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )
    time.sleep(1.2)


def _translate(
    source: Path,
    _config: Config,
    *,
    backend: str = "llm",
    processing_id: str,
    **_kwargs: object,
) -> TranslationOutcome:
    """成功したTranslate記録とdownload成果物を公開する。"""

    root = Path.cwd() / "outputs" / source.stem / processing_id
    _write_translation_progress(root, source, processing_id, backend)
    markdown = root / "document.ja.md"
    docx = root / "document.ja.docx"
    root.mkdir(parents=True, exist_ok=True)
    image = root / "assets/preview.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "red").save(image)
    markdown.write_text(
        '# E2E\n\n![preview](assets/preview.png){fig-alt="preview"}\n',
        encoding="utf-8",
    )
    docx.write_bytes(b"docx")
    now = datetime.now(UTC)
    write_model(
        root / "translation.json",
        TranslationRecord(
            translation_id=processing_id,
            status="succeeded",
            source=_input(source, "source"),
            backend=backend,
            outputs=[describe_artifact(root, markdown), describe_artifact(root, docx)],
            created_at=now,
            updated_at=now,
        ),
    )
    return TranslationOutcome(
        translation_id=processing_id,
        processing_directory=root,
        markdown=markdown,
        docx=docx,
    )


def _review(
    source: Path,
    translation: Path,
    _config: Config,
    *,
    processing_id: str,
    **_kwargs: object,
) -> ReviewOutcome:
    """成功したReview記録とreportを公開する。"""

    root = Path.cwd() / "outputs" / translation.stem / processing_id
    report = root / "review.md"
    root.mkdir(parents=True)
    report.write_text("# Review E2E\n", encoding="utf-8")
    now = datetime.now(UTC)
    write_model(
        root / "review.json",
        ReviewRecord(
            review_id=processing_id,
            status="succeeded",
            source=_input(source, "source"),
            translation=_input(translation, "translation"),
            outputs=[describe_artifact(root, report)],
            created_at=now,
            updated_at=now,
        ),
    )
    return ReviewOutcome(
        review_id=processing_id,
        processing_directory=root,
        report=report,
    )


def _register(
    paths: list[Path],
    _config: Config,
    *,
    source_id: str | None,
    processing_id: str,
    **_kwargs: object,
) -> RegistrationOutcome:
    """成功したRegister記録を公開する。"""

    root = Path.cwd() / "outputs" / (source_id or paths[0].stem) / processing_id
    now = datetime.now(UTC)
    inputs = [_input(path, "reference") for path in paths]
    result = RegistrationResult(
        collection="e2e",
        embedding_model="e2e",
        sources=[
            RegistrationSourceResult(
                logical_path=path.name,
                sha256=sha256_file(path),
                revision="e2e",
                point_count=1,
                status="registered",
            )
            for path in paths
        ],
        total_points=len(paths),
    )
    write_model(
        root / "registration.json",
        RegistrationRecord(
            registration_id=processing_id,
            status="succeeded",
            source_id=source_id,
            inputs=inputs,
            fingerprint="e2e",
            collection="e2e",
            embedding_model="e2e",
            result=result,
            created_at=now,
            updated_at=now,
        ),
    )
    return RegistrationOutcome(
        registration_id=processing_id,
        processing_directory=root,
        record=root / "registration.json",
    )


def _upgrade(
    source_v1: Path,
    source_v2: Path,
    translation_v1: Path,
    _config: Config,
    *,
    backend: str = "llm",
    processing_id: str,
    **_kwargs: object,
) -> UpgradeOutcome:
    """成功したUpgrade記録と日本語v2 DOCXを公開する。"""

    root = Path.cwd() / "outputs" / source_v2.stem / processing_id
    docx = root / "document.ja.docx"
    root.mkdir(parents=True)
    docx.write_bytes(b"docx")
    now = datetime.now(UTC)
    write_model(
        root / "upgrade.json",
        UpgradeRecord(
            upgrade_id=processing_id,
            status="succeeded",
            source_v1=_input(source_v1, "source-v1"),
            source_v2=_input(source_v2, "source-v2"),
            translation_v1=_input(translation_v1, "translation-v1"),
            backend=backend,
            outputs=[describe_artifact(root, docx)],
            created_at=now,
            updated_at=now,
        ),
    )
    return UpgradeOutcome(
        upgrade_id=processing_id,
        processing_directory=root,
        docx=docx,
    )


def execute_translate(source: Path, backend: str, processing_id: str) -> object:
    """子processからE2E用Translate成果物を生成する。"""

    return _translate(source, Config(), backend=backend, processing_id=processing_id)


def execute_review(source: Path, translation: Path, processing_id: str) -> object:
    """子processからE2E用Review成果物を生成する。"""

    return _review(source, translation, Config(), processing_id=processing_id)


def execute_register(
    paths: list[Path], source_id: str | None, processing_id: str
) -> object:
    """子processからE2E用Register成果物を生成する。"""

    return _register(paths, Config(), source_id=source_id, processing_id=processing_id)


def execute_upgrade(
    source_v1: Path,
    source_v2: Path,
    translation_v1: Path,
    backend: str,
    processing_id: str,
) -> object:
    """子processからE2E用Upgrade成果物を生成する。"""

    return _upgrade(
        source_v1,
        source_v2,
        translation_v1,
        Config(),
        backend=backend,
        processing_id=processing_id,
    )


if __name__ == "__main__":
    # Streamlitは本fileを__main__で実行するため、spawn可能なmodule名を別途使う。
    from tests.e2e import streamlit_driver as worker  # noqa: PLW0406

    ui.load_config = Config
    ui.translate_pdf = _translate
    ui.review_pdfs = _review
    ui.register_paths = _register
    ui.upgrade_pdfs = _upgrade
    ui._execute_translate = worker.execute_translate  # noqa: SLF001
    ui._execute_review = worker.execute_review  # noqa: SLF001
    ui._execute_register = worker.execute_register  # noqa: SLF001
    ui._execute_upgrade = worker.execute_upgrade  # noqa: SLF001
    ui.main()
