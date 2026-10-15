"""実ファイル処理のDocumentとDOCXを独立に検査する。"""

import sys
from pathlib import Path
from zipfile import ZipFile

from translate.models.document import Document


def main() -> None:
    """入力構造と最終訳のID・原文・処理漏れ・DOCXを照合する。"""

    root = Path(sys.argv[1])
    source_name = "preprocess/structure/document.json"
    source = Document.model_validate_json(
        (root / source_name).read_text(encoding="utf-8")
    )
    final_path = root / "review/fix/document.json"
    if not final_path.is_file():
        final_path = root / "translation/translate/document.json"
    final = Document.model_validate_json(final_path.read_text(encoding="utf-8"))
    before = [unit for _, unit in source.text_units()]
    after = [unit for _, unit in final.text_units()]
    assert len(source.pages) == len(final.pages)
    assert [unit.id for unit in before] == [unit.id for unit in after]
    assert len({unit.id for unit in after}) == len(after)
    for original, translated in zip(before, after, strict=True):
        assert [(span.id, span.source, span.kind) for span in original.spans] == [
            (span.id, span.source, span.kind) for span in translated.spans
        ]
        assert all(
            span.translated is not None
            for span in translated.spans
            if span.source.strip() and span.kind not in {"code", "line_break"}
        ), f"untranslated span in {translated.id}"
    docx = root / "publisher/ooxml/document.ja.docx"
    with ZipFile(docx) as archive:
        assert archive.testzip() is None
        assert archive.read("word/document.xml")
    sys.stdout.write(
        f"PASS pages={len(final.pages)} units={len(after)} docx={docx.stat().st_size}\n"
    )


if __name__ == "__main__":
    main()
