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


class Pandoc:
    """Timeoutと機能確認済み実行fileを保持し、Pandocによる変換を担当する。"""

    def __init__(self, timeout: float) -> None:
        """各Pandoc processへ適用するTimeoutを保持する。

        Args:
            timeout: 外部process一回あたりの待機上限秒数。
        """
        self.timeout = timeout
        self.executable: str | None = None

    def check(self) -> str:
        """必要なoptionとDOCX extensionを確認し、実行file pathを返す。

        Returns:
            str: 必要なoptionとDOCX extensionを確認し、実行file pathを返す。

        Raises:
            PandocError: `pandoc is required`、`pandoc feature check failed`、`f"pandoc lacks
                required features: {', '.join(missing)}"`のいずれかと判定した場合。
        """

        if self.executable is not None:
            return self.executable
        logger.debug("Checking Pandoc features")
        executable = shutil.which("pandoc")
        if executable is None:
            logger.warning("Pandoc feature check failed type=MissingExecutable")
            raise PandocError("pandoc is required")
        try:
            help_text = subprocess.run(
                [executable, "--help"],
                check=True,
                capture_output=True,
                encoding="utf-8",
                timeout=self.timeout,
            ).stdout
            extensions = subprocess.run(
                [executable, "--list-extensions=docx"],
                check=True,
                capture_output=True,
                encoding="utf-8",
                timeout=self.timeout,
            ).stdout
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("Pandoc feature check failed type=%s", type(error).__name__)
            raise PandocError("pandoc feature check failed") from error
        missing = [
            option
            for option in ("--reference-doc", "--list-of-figures", "--list-of-tables")
            if option not in help_text
        ]
        if "native_numbering" not in extensions:
            missing.append("docx+native_numbering")
        if missing:
            logger.warning("Pandoc feature check failed missing=%s", ",".join(missing))
            raise PandocError(f"pandoc lacks required features: {', '.join(missing)}")
        logger.debug("Pandoc feature check completed")
        self.executable = executable
        return executable

    def publish(self, markdown: Path, output: Path, template: Path) -> Path:
        """固定optionでMarkdownを中間DOCXへ変換する。

        Args:
            markdown (Path): DOCX変換またはPreview対象のMarkdown Path。
            output (Path): 変換結果を書き込むFile Path。
            template (Path): DOCX Style用のReference DOCX Path。

        Returns:
            Path: 固定optionでMarkdownを中間DOCXへ変換する。

        Raises:
            PandocError: `markdown and reference DOCX must exist`、`pandoc DOCX publication
                failed`のいずれかと判定した場合。
        """

        logger.info("Pandoc publication started")
        executable = self.check()
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
                timeout=self.timeout,
            )
            validate_docx(temporary)
            replace_path(temporary, output)
        except (
            KeyError,
            OSError,
            subprocess.SubprocessError,
            zipfile.BadZipFile,
        ) as error:
            logger.warning("Pandoc publication failed type=%s", type(error).__name__)
            raise PandocError("pandoc DOCX publication failed") from error
        finally:
            temporary.unlink(missing_ok=True)
        logger.info("Pandoc publication completed")
        return output

    def table_to_markdown(self, table: dict[str, object]) -> str:
        """Pandocの構文木を介して結合セル対応grid tableへ変換する。

        Args:
            table (dict[str, object]): Pandoc Markdownへ変換するTable Data。

        Returns:
            str: Pandocの構文木を介して結合セル対応grid tableへ変換する。

        Raises:
            PandocError: `pandoc table conversion failed`と判定した場合。
        """

        logger.debug("Pandoc table conversion started")
        executable = self.check()
        try:
            envelope = json.loads(
                subprocess.run(
                    [executable, "--from", "markdown", "--to", "json"],
                    input="",
                    check=True,
                    capture_output=True,
                    encoding="utf-8",
                    timeout=self.timeout,
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
                timeout=self.timeout,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            logger.warning(
                "Pandoc table conversion failed type=%s", type(error).__name__
            )
            raise PandocError("pandoc table conversion failed") from error
        logger.debug("Pandoc table conversion completed")
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
