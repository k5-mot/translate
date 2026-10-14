"""Pandoc機能検査とMarkdownから中間DOCXへの変換。"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from translate.adapters.artifact_store import replace_path

logger = logging.getLogger(__name__)


class PandocError(RuntimeError):
    """Pandocの欠落、機能不足または変換失敗を表す。"""


def check_pandoc(timeout: float) -> str:
    """必要なoptionとDOCX extensionを確認し、実行file pathを返す。

    Args:
        timeout (float): 外部処理のTimeout秒数。

    Returns:
        str: 必要なoptionとDOCX extensionを確認し、実行file pathを返す。

    Raises:
        PandocError: `pandoc is required`、`pandoc feature check failed`、`f"pandoc lacks
            required features: {', '.join(missing)}"`のいずれかと判定した場合。
    """

    logger.debug("Pandoc機能確認開始")
    executable = shutil.which("pandoc")
    if executable is None:
        logger.warning("Pandoc機能確認失敗 type=MissingExecutable")
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
        logger.warning("Pandoc機能確認失敗 type=%s", type(error).__name__)
        raise PandocError("pandoc feature check failed") from error
    missing = [
        option
        for option in ("--reference-doc", "--list-of-figures", "--list-of-tables")
        if option not in help_text
    ]
    if "native_numbering" not in extensions:
        missing.append("docx+native_numbering")
    if missing:
        logger.warning("Pandoc機能確認失敗 missing=%s", ",".join(missing))
        raise PandocError(f"pandoc lacks required features: {', '.join(missing)}")
    logger.debug("Pandoc機能確認完了")
    return executable


def publish(markdown: Path, output: Path, template: Path, timeout: float) -> Path:
    """固定optionでMarkdownを中間DOCXへ変換する。

    Args:
        markdown (Path): DOCX変換またはPreview対象のMarkdown Path。
        output (Path): 変換結果を書き込むFile Path。
        template (Path): DOCX Style用のReference DOCX Path。
        timeout (float): 外部処理のTimeout秒数。

    Returns:
        Path: 固定optionでMarkdownを中間DOCXへ変換する。

    Raises:
        PandocError: `markdown and reference DOCX must exist`、`pandoc DOCX publication
            failed`のいずれかと判定した場合。
    """

    logger.info("Pandoc公開開始")
    executable = check_pandoc(timeout)
    if not markdown.is_file() or not template.is_file():
        raise PandocError("markdown and reference DOCX must exist")
    validate_docx(template)
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
        validate_docx(temporary)
        replace_path(temporary, output)
    except (
        KeyError,
        OSError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        logger.warning("Pandoc公開失敗 type=%s", type(error).__name__)
        raise PandocError("pandoc DOCX publication failed") from error
    finally:
        temporary.unlink(missing_ok=True)
    logger.info("Pandoc公開完了")
    return output


def table_to_markdown(table: dict[str, object], timeout: float) -> str:
    """Pandocの構文木を介して結合セル対応grid tableへ変換する。

    Args:
        table (dict[str, object]): Pandoc Markdownへ変換するTable Data。
        timeout (float): 外部処理のTimeout秒数。

    Returns:
        str: Pandocの構文木を介して結合セル対応grid tableへ変換する。

    Raises:
        PandocError: `pandoc table conversion failed`と判定した場合。
    """

    logger.debug("Pandoc表変換開始")
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
        result = subprocess.run(
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
        logger.warning("Pandoc表変換失敗 type=%s", type(error).__name__)
        raise PandocError("pandoc table conversion failed") from error
    logger.debug("Pandoc表変換完了")
    return result


def validate_docx(path: Path) -> None:
    """DOCXがCRCエラーなく必須部品を持つZIPであることを検査する。

    Args:
        path (Path): Package構造を検証するDOCX FileのPath。

    Raises:
        PandocError: `invalid DOCX package`と判定した場合。
    """

    with zipfile.ZipFile(path) as archive:
        required = {"[Content_Types].xml", "word/document.xml"}
        if not required.issubset(archive.namelist()) or archive.testzip() is not None:
            raise PandocError("invalid DOCX package")
