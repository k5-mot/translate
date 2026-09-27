"""Pandoc機能検査とMarkdownからDOCXへの公開。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


class PandocError(RuntimeError):
    """Pandocの欠落、機能不足または変換失敗を表す。"""


def check_pandoc(timeout: float) -> str:
    """必要なoptionとDOCX extensionを確認し、実行file pathを返す。"""

    executable = shutil.which("pandoc")
    if executable is None:
        raise PandocError("pandoc is required")
    try:
        help_text = subprocess.run(
            [executable, "--help"],
            check=True,
            capture_output=True,
            encoding="utf-8",
            timeout=timeout,
        ).stdout
        extensions = subprocess.run(
            [executable, "--list-extensions=docx"],
            check=True,
            capture_output=True,
            encoding="utf-8",
            timeout=timeout,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise PandocError("pandoc feature check failed") from error
    missing = [
        option
        for option in ("--reference-doc", "--list-of-figures", "--list-of-tables")
        if option not in help_text
    ]
    if "native_numbering" not in extensions:
        missing.append("docx+native_numbering")
    if missing:
        raise PandocError(f"pandoc lacks required features: {', '.join(missing)}")
    return executable


def publish(markdown: Path, output: Path, template: Path, timeout: float) -> Path:
    """固定optionでMarkdownをDOCXへ変換し、成功したfileだけを公開する。"""

    executable = check_pandoc(timeout)
    if not markdown.is_file() or not template.is_file():
        raise PandocError("markdown and reference DOCX must exist")
    _validate_docx(template)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.stem}.",
        suffix=".docx",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        subprocess.run(
            [
                executable,
                str(markdown.resolve()),
                "--from",
                "markdown-smart",
                "--to",
                "docx+native_numbering",
                "--standalone",
                "--reference-doc",
                str(template.resolve()),
                "--resource-path",
                str(markdown.parent.resolve()),
                "--toc",
                "--toc-depth",
                "6",
                "--list-of-figures",
                "--list-of-tables",
                "--output",
                str(temporary.resolve()),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        _validate_docx(temporary)
        temporary.replace(output)
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        raise PandocError("pandoc DOCX publication failed") from error
    finally:
        temporary.unlink(missing_ok=True)
    return output


def table_to_markdown(table: dict[str, object], timeout: float) -> str:
    """Pandocの構文木を介して結合セル対応grid tableへ変換する。"""

    executable = check_pandoc(timeout)
    try:
        envelope = json.loads(
            subprocess.run(
                [executable, "--from", "markdown", "--to", "json"],
                input="",
                check=True,
                capture_output=True,
                encoding="utf-8",
                timeout=timeout,
            ).stdout
        )
        envelope["blocks"] = [table]
        return subprocess.run(
            [
                executable,
                "--from",
                "json",
                "--to",
                "markdown-simple_tables-multiline_tables-pipe_tables",
                "--columns",
                "100",
            ],
            input=json.dumps(envelope, ensure_ascii=False),
            check=True,
            capture_output=True,
            encoding="utf-8",
            timeout=timeout,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise PandocError("pandoc table conversion failed") from error


def _validate_docx(path: Path) -> None:
    """DOCXがCRCエラーなく必須部品を持つZIPであることを検査する。"""

    with zipfile.ZipFile(path) as archive:
        required = {"[Content_Types].xml", "word/document.xml"}
        if not required.issubset(archive.namelist()) or archive.testzip() is not None:
            raise PandocError("invalid DOCX package")
