"""Office acceptance conversion uses cached field results without recalculating them."""

import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> None:
    source, target = map(Path, sys.argv[1:3])
    with (
        ZipFile(source) as input_docx,
        ZipFile(target, "w", ZIP_DEFLATED) as output_docx,
    ):
        for item in input_docx.infolist():
            data = input_docx.read(item.filename)
            if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                data = re.sub(rb"<w:fldChar\b[^>]*/>", b"", data)
                data = re.sub(rb"<w:instrText\b[^>]*>.*?</w:instrText>", b"", data)
            output_docx.writestr(item, data)


if __name__ == "__main__":
    main()
