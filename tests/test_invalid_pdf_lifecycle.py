"""不正PDFを公開Lifecycleへ渡した場合の失敗契約を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pypdfium2 as pdfium
import pytest

from translate.adapters import pdf
from translate.common.lifecycle import (
    PublicRunError,
    execute_public_run,
    load_failure,
    prepare_run,
)
from translate.common.runs import Operation, RunRepository

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def _templates(root: Path) -> Path:
    root.mkdir()
    for name in ("structure", "translation", "review"):
        (root / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (root / "glossary.csv").write_text("en,ja\n", encoding="utf-8")
    (root / "template.docx").write_bytes(b"template")
    return root


def _valid_pdf(path: Path) -> Path:
    with pdfium.PdfDocument.new() as document:
        document.new_page(100, 100)
        document.save(path)
    return path


@pytest.mark.integration
@pytest.mark.parametrize(
    ("operation", "invalid_kind", "expected_role"),
    [
        ("translate", "empty", "source"),
        ("translate", "corrupt", "source"),
        ("translate", "encrypted", "source"),
        ("review", "unreadable", "translation_ja"),
    ],
)
def test_invalid_pdf_creates_resumable_failed_run_without_output(  # noqa: PLR0913, PLR0917
    operation: Operation,
    invalid_kind: str,
    expected_role: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """空・暗号化・破損・読取り不能PDFはrole付きで停止する。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )
    invalid = tmp_path / "invalid.pdf"
    if invalid_kind == "empty":
        invalid.write_bytes(b"")
    elif invalid_kind == "corrupt":
        invalid.write_bytes(b"not a PDF")
    else:
        _valid_pdf(invalid)

    if operation == "translate":
        inputs = {"source": invalid}
    else:
        inputs = {
            "source_en": _valid_pdf(tmp_path / "source.pdf"),
            "translation_ja": invalid,
        }

    if invalid_kind in {"encrypted", "unreadable"}:
        original_validate = pdf.validate

        def injected_validate(path: Path) -> None:
            if path.name == invalid.name:
                error_type = (
                    PermissionError if invalid_kind == "unreadable" else OSError
                )
                message = f"{invalid_kind} body and password must stay private"
                raise error_type(message)
            original_validate(path)

        monkeypatch.setattr(pdf, "validate", injected_validate)

    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, operation, inputs, settings)

    with pytest.raises(PublicRunError) as caught:
        execute_public_run(repository, prepared, settings)

    failure = load_failure(repository, prepared.record.run_id)
    assert failure is not None
    assert failure.task.endswith("SPLIT")
    assert failure.target_id == expected_role
    assert f"target={expected_role}" in str(caught.value)
    assert "password" not in str(caught.value)
    assert repository.load(prepared.record.run_id).status == "failed"
    assert not any(prepared.paths.outputs.rglob("*"))

    resumed = prepare_run(
        repository,
        operation,
        inputs,
        settings,
        resume_id=prepared.record.run_id,
    )
    assert resumed.resumed is True
    assert resumed.record.run_id == prepared.record.run_id
