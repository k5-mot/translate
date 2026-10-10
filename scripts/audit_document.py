"""実ファイル処理のDocumentとDOCXを独立に検査する。"""

import re
import sys
from pathlib import Path
from zipfile import ZipFile

from translate.models.document import Document, iter_text_units


def main() -> None:
    """入力構造と最終訳のID・原文・空訳・DOCXを照合する。"""

    root = Path(sys.argv[1])
    operation = sys.argv[2]
    source_name = (
        "preprocess/source-v2/structure/document.json"
        if operation == "upgrade"
        else "preprocess/structure/document.json"
    )
    source = Document.model_validate_json(
        (root / source_name).read_text(encoding="utf-8")
    )
    final = Document.model_validate_json(
        (root / "review/fix/document.json").read_text(encoding="utf-8")
    )
    before = [unit for _, unit in iter_text_units(source)]
    after = [unit for _, unit in iter_text_units(final)]
    assert len(source.pages) == len(final.pages)
    assert [unit.id for unit in before] == [unit.id for unit in after]
    assert len({unit.id for unit in after}) == len(after)
    empty = 0
    english_only: list[str] = []
    for original, translated in zip(before, after, strict=True):
        assert [(span.id, span.source, span.kind) for span in original.spans] == [
            (span.id, span.source, span.kind) for span in translated.spans
        ]
        empty += sum(
            not span.translated or not span.translated.strip()
            for span in translated.spans
            if span.source.strip() and span.kind not in {"code", "line_break"}
        )
        for source_span, translated_span in zip(
            original.spans, translated.spans, strict=True
        ):
            source = source_span.source.strip()
            target = (translated_span.translated or "").strip()
            if (
                source_span.kind not in {"code", "line_break"}
                and len(source) >= 12
                and len(source.split()) >= 2
                and re.search(r"[A-Za-z]", source)
                and not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", target)
            ):
                english_only.append(source_span.id)
    assert empty == 0, f"empty translations: {empty}"
    assert not english_only, f"English-only translations: {english_only[:10]}"
    docx = root / "publisher/docx/document.ja.docx"
    with ZipFile(docx) as archive:
        assert archive.testzip() is None
        assert archive.read("word/document.xml")
    sys.stdout.write(
        f"PASS pages={len(final.pages)} units={len(after)} "
        f"empty={empty} docx={docx.stat().st_size}\n"
    )


if __name__ == "__main__":
    main()
