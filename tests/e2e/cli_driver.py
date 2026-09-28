"""外部service境界を置換して公開Typer appを起動するE2E driver。"""

from pathlib import Path

from translate import cli
from translate.common.config import Config
from translate.pipeline.register import RegistrationOutcome
from translate.pipeline.review import ReviewOutcome
from translate.pipeline.translate import TranslationOutcome
from translate.pipeline.upgrade import UpgradeOutcome


def _translate(source: Path, *_args: object, **_kwargs: object) -> TranslationOutcome:
    """Translate CLIが表示する成果物を返す。"""

    root = Path.cwd() / "outputs" / source.stem / "translate-e2e"
    return TranslationOutcome(
        translation_id="translate-e2e",
        processing_directory=root,
        markdown=root / "document.ja.md",
        docx=root / "document.ja.docx",
    )


def _review(
    _source: Path, translation: Path, *_args: object, **_kwargs: object
) -> ReviewOutcome:
    """Review CLIが表示する成果物を返す。"""

    root = Path.cwd() / "outputs" / translation.stem / "review-e2e"
    return ReviewOutcome(
        review_id="review-e2e",
        processing_directory=root,
        report=root / "review.md",
    )


def _register(
    paths: list[Path], *_args: object, **_kwargs: object
) -> RegistrationOutcome:
    """Register CLIが表示する成果物を返す。"""

    root = Path.cwd() / "outputs" / paths[0].stem / "register-e2e"
    return RegistrationOutcome(
        registration_id="register-e2e",
        processing_directory=root,
        record=root / "registration.json",
    )


def _upgrade(
    _source_v1: Path,
    source_v2: Path,
    _translation_v1: Path,
    *_args: object,
    **_kwargs: object,
) -> UpgradeOutcome:
    """Upgrade CLIが表示する成果物を返す。"""

    root = Path.cwd() / "outputs" / source_v2.stem / "upgrade-e2e"
    return UpgradeOutcome(
        upgrade_id="upgrade-e2e",
        processing_directory=root,
        docx=root / "document.ja.docx",
    )


cli.load_config = Config
cli.translate_pdf = _translate
cli.review_pdfs = _review
cli.register_paths = _register
cli.upgrade_pdfs = _upgrade
