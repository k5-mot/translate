"""Pandoc機能検査とMarkdownからDOCXへの公開。"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from translate.artifact_store import replace_path

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MATH_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_WORD = f"{{{_WORD_NAMESPACE}}}"
_STYLE_ROLES = {
    "TableCaption": (("TableCaption",), ("表タイトル", "Table Caption")),
    "ImageCaption": (("ImageCaption",), ("図タイトル", "Image Caption")),
    "SourceCode": (("SourceCode",), ("コードブロック", "Source Code")),
    "Equation": (("EquationBlock",), ("数式ブロック", "Equation Block")),
}


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
    """固定optionでMarkdownをDOCXへ変換し、成功したfileだけを公開する。

    Args:
        markdown (Path): DOCX変換またはPreview対象のMarkdown Path。
        output (Path): 変換結果を書き込むFile Path。
        template (Path): DOCX Style用のReference DOCX Path。
        timeout (float): 外部処理のTimeout秒数。

    Returns:
        Path: 固定optionでMarkdownをDOCXへ変換し、成功したfileだけを公開する。

    Raises:
        PandocError: `markdown and reference DOCX must exist`、`pandoc DOCX publication
            failed`のいずれかと判定した場合。
    """

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
        _finalize_docx(temporary)
        _validate_docx(temporary)
        replace_path(temporary, output)
    except (
        ET.ParseError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        raise PandocError("pandoc DOCX publication failed") from error
    finally:
        temporary.unlink(missing_ok=True)
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


def _finalize_docx(path: Path) -> None:
    """Pandoc固定styleを参照templateの実styleへ結び、field更新を予約する。

    Args:
        path (Path): StyleとFieldを仕上げるDOCX FileのPath。
    """

    descriptor, rewritten_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.stem}.finalize.",
        suffix=".docx",
    )
    os.close(descriptor)
    rewritten = Path(rewritten_name)
    try:
        with (
            zipfile.ZipFile(path) as source,
            zipfile.ZipFile(rewritten, "w") as target,
        ):
            styles = _parse_xml(source.read("word/styles.xml"))
            mappings, names = _style_mappings(styles)
            for info in source.infolist():
                value = source.read(info.filename)
                if info.filename == "word/document.xml":
                    value = _finalize_document(value, mappings, names)
                elif info.filename == "word/settings.xml":
                    value = _enable_field_updates(value)
                target.writestr(info, value)
        replace_path(rewritten, path)
    finally:
        rewritten.unlink(missing_ok=True)


def _parse_xml(value: bytes) -> ET.Element:
    """元のnamespace prefixを登録してOOXMLを解析する。

    Args:
        value (bytes): 解析するOOXMLのByte列。

    Returns:
        ET.Element: 元のnamespace prefixを登録してOOXMLを解析する。
    """

    # DOCX Taskが生成したOOXMLに限定し、外部entityを使用しない。
    for _, namespace in ET.iterparse(  # noqa: S314
        io.BytesIO(value), events=("start-ns",)
    ):
        prefix, uri = namespace
        if prefix != "xml":
            ET.register_namespace(prefix, uri)
    return ET.fromstring(value)  # noqa: S314


def _style_mappings(
    styles: ET.Element,
) -> tuple[dict[str, str], dict[str, str]]:
    """Pandoc style IDからtemplate style IDと表示名への対応を得る。

    Args:
        styles (ET.Element): Style定義を保持するOOXML要素。

    Returns:
        tuple[dict[str, str], dict[str, str]]: Pandoc style IDからtemplate style IDと表示名への対応を得る。
    """

    namespace = {"w": _WORD_NAMESPACE}
    styles_by_id: dict[str, ET.Element] = {}
    styles_by_name: dict[str, ET.Element] = {}
    for style in styles.findall("w:style", namespace):
        style_id = style.get(f"{_WORD}styleId")
        name = style.find("w:name", namespace)
        display_name = name.get(f"{_WORD}val") if name is not None else None
        if style_id:
            styles_by_id[style_id] = style
        if display_name:
            styles_by_name[display_name] = style

    mappings: dict[str, str] = {}
    names: dict[str, str] = {}
    for source_id, (preferred_ids, preferred_names) in _STYLE_ROLES.items():
        style = next(
            (
                styles_by_name[value]
                for value in preferred_names
                if value in styles_by_name
            ),
            None,
        )
        if style is None:
            style = next(
                (
                    styles_by_id[value]
                    for value in preferred_ids
                    if value in styles_by_id
                ),
                None,
            )
        if style is None:
            continue
        target_id = style.get(f"{_WORD}styleId")
        name = style.find("w:name", namespace)
        display_name = name.get(f"{_WORD}val") if name is not None else None
        if target_id and display_name:
            mappings[source_id] = target_id
            names[source_id] = display_name
    return mappings, names


def _finalize_document(
    value: bytes,
    mappings: dict[str, str],
    names: dict[str, str],
) -> bytes:
    """本文のstyle参照と図表一覧fieldをtemplate定義へ合わせる。

    Args:
        value (bytes): Style参照を更新するDocument XMLのByte列。
        mappings (dict[str, str]): 旧Style IDからTemplate Style IDへの対応表。
        names (dict[str, str]): Style IDと表示名の対応表。

    Returns:
        bytes: 本文のstyle参照と図表一覧fieldをtemplate定義へ合わせる。
    """

    namespace = {"m": _MATH_NAMESPACE, "w": _WORD_NAMESPACE}
    document = _parse_xml(value)
    for style in document.findall(".//w:pStyle", namespace):
        current = style.get(f"{_WORD}val")
        if current in mappings:
            style.set(f"{_WORD}val", mappings[current])
    equation_style = mappings.get("Equation")
    if equation_style is not None:
        for paragraph in document.findall(".//w:p", namespace):
            if paragraph.find("m:oMathPara", namespace) is None:
                continue
            properties = paragraph.find("w:pPr", namespace)
            if properties is None:
                properties = ET.Element(f"{_WORD}pPr")
                paragraph.insert(0, properties)
            style = properties.find("w:pStyle", namespace)
            if style is None:
                style = ET.Element(f"{_WORD}pStyle")
                properties.insert(0, style)
            style.set(f"{_WORD}val", equation_style)
    for instruction in document.findall(".//w:instrText", namespace):
        if instruction.text is None:
            continue
        instruction.text = instruction.text.replace(
            "Image Caption", names.get("ImageCaption", "Image Caption")
        ).replace("Table Caption", names.get("TableCaption", "Table Caption"))
    for field in document.findall(".//w:fldChar", namespace):
        if field.get(f"{_WORD}fldCharType") == "begin":
            field.set(f"{_WORD}dirty", "true")
    return ET.tostring(document, encoding="utf-8", xml_declaration=True)


def _enable_field_updates(value: bytes) -> bytes:
    """Wordで開いた時に目次、図一覧および表一覧を更新させる。

    Args:
        value (bytes): Field自動更新設定を追加するSettings XMLのByte列。

    Returns:
        bytes: Wordで開いた時に目次、図一覧および表一覧を更新させる。
    """

    namespace = {"w": _WORD_NAMESPACE}
    settings = _parse_xml(value)
    update = settings.find("w:updateFields", namespace)
    if update is None:
        update = ET.SubElement(settings, f"{_WORD}updateFields")
    update.set(f"{_WORD}val", "true")
    return ET.tostring(settings, encoding="utf-8", xml_declaration=True)
