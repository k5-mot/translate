"""PandocによるDOCX入出力を提供する。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


def check_pandoc() -> None:
    """v5が必要とするPandoc機能が存在するか検査する。

    Returns:
        なし。

    Raises:
        RuntimeError: Pandocまたは必要option/extensionがない場合。
    """

    executable = shutil.which("pandoc")
    if not executable:
        msg = "pandoc is required"
        raise RuntimeError(msg)
    help_text = subprocess.run(
        [executable, "--help"], check=True, capture_output=True, encoding="utf-8"
    ).stdout
    missing = [
        option
        for option in ("--list-of-figures", "--list-of-tables", "--number-sections")
        if option not in help_text
    ]
    extensions = subprocess.run(
        [executable, "--list-extensions=docx"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    if "native_numbering" not in extensions:
        missing.append("docx+native_numbering")
    if missing:
        msg = f"pandoc lacks required features: {', '.join(missing)}"
        raise RuntimeError(msg)


def create_docx(markdown: Path, output: Path, template: Path) -> None:
    """固定したPandoc契約でMarkdownからDOCXを生成する。

    Args:
        markdown: 内部Markdown。
        output: 最終DOCX。
        template: reference DOCX。

    Returns:
        なし。
    """

    _preflight(markdown, output, template)
    executable = shutil.which("pandoc") or "pandoc"
    # 失敗途中のDOCXで既存成果物を上書きしないよう、同じdirectoryへ一時生成する。
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.stem}.", suffix=".docx"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        subprocess.run(
            [
                executable,
                str(markdown.resolve()),
                "--from",
                "markdown",
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
                "--number-sections",
                "--output",
                str(temporary.resolve()),
            ],
            check=True,
        )
        _validate_docx(temporary, "Pandoc generated an invalid DOCX package")
        _publish_docx(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def docx_to_text(path: Path) -> str:
    """PandocでDOCXを見出し付きplain textへ変換する。

    Args:
        path: 入力DOCX。

    Returns:
        UTF-8文字列。
    """

    check_pandoc()
    return subprocess.run(
        ["pandoc", str(path), "--to", "plain"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout


def _preflight(markdown: Path, output: Path, template: Path) -> None:
    """変換process開始前に入力、Toolおよび出力先を検証する。"""

    if not markdown.is_file():
        msg = f"Markdown input is not a readable file: {markdown.name}"
        raise ValueError(msg)
    try:
        with markdown.open("rb") as stream:
            stream.read(1)
    except OSError as error:
        msg = f"Markdown input is not readable: {markdown.name}"
        raise ValueError(msg) from error
    _validate_docx(template, "Reference DOCX is invalid")
    check_pandoc()
    _validate_output_directory(output)


def _validate_docx(path: Path, message: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(archive.namelist()) or archive.testzip():
                raise RuntimeError(message)
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError(message) from error


def _validate_output_directory(output: Path) -> None:
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, probe_name = tempfile.mkstemp(
            dir=output.parent, prefix=f".{output.name}.preflight."
        )
        os.close(descriptor)
        Path(probe_name).unlink()
    except OSError as error:
        msg = f"DOCX output directory is not writable: {output.parent}"
        raise RuntimeError(msg) from error


def _publish_docx(temporary: Path, output: Path) -> None:
    """障害注入可能な最終replace境界。"""

    temporary.replace(output)
