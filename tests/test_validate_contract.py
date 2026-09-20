"""VALIDATEのwarning通過とError停止を検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from translate.document import Block, Document, Inline, Page
from translate.tasks import validate

if TYPE_CHECKING:
    from pathlib import Path


def test_skipped_fix_is_preserved_as_warning(tmp_path: Path) -> None:
    """FIX/VERIFY skippedを成果物へ残しつつVALIDATEを通す。"""

    translated = Inline(
        id="block/translated",
        text="訳文",
        fix_status="skipped",
        fix_error="service unavailable",
    )
    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="block",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="block/source", text="source")],
                        translated=[translated],
                        final=[translated.model_copy(deep=True)],
                    )
                ],
            )
        ]
    )
    output = tmp_path / "report.json"

    assert validate.run(document, tmp_path, output) == document
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["valid"] is True
    assert report["warnings"] == [
        {
            "kind": "fix-skipped",
            "target_id": "block/translated",
            "message": "service unavailable",
        }
    ]


def test_missing_translation_stops_without_publishing_report(tmp_path: Path) -> None:
    """本文訳欠落をErrorとして停止しvalid reportを公開しない。"""

    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="missing",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="source", text="source")],
                    )
                ],
            )
        ]
    )
    output = tmp_path / "report.json"

    with pytest.raises(ValueError, match="missing translation"):
        validate.run(document, tmp_path, output)

    assert not output.exists()
