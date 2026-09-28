"""Pipeline外部境界を置換して実Streamlit UIを起動するE2E driver。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from translate import ui
from translate.artifact_store import describe_artifact, sha256_file, write_model
from translate.common.config import Config
from translate.models.artifacts import (
    InputFile,
    RegistrationRecord,
    RegistrationResult,
    RegistrationSourceResult,
    ReviewRecord,
    TranslationRecord,
)
from translate.models.upgrade import UpgradeRecord
from translate.pipeline.register import RegistrationOutcome
from translate.pipeline.review import ReviewOutcome
from translate.pipeline.translate import TranslationOutcome
from translate.pipeline.upgrade import UpgradeOutcome


def _input(path: Path, role: str) -> InputFile:
    """staged uploadから最上位記録用InputFileを作る。"""

    return InputFile(
        role=role,
        logical_path=path.name,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


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
    markdown = root / "document.ja.md"
    docx = root / "document.ja.docx"
    root.mkdir(parents=True)
    markdown.write_text("# E2E\n", encoding="utf-8")
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


ui.load_config = Config
ui.translate_pdf = _translate
ui.review_pdfs = _review
ui.register_paths = _register
ui.upgrade_pdfs = _upgrade

ui.main()
