"""Pandocの中間DOCXを仕上げ、検証済みの最終DOCXを公開する。"""

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from translate.adapters.artifact_store import temporary_task_directory
from translate.adapters.pandoc import validate_docx

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MATH_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_WORD = f"{{{_WORD_NAMESPACE}}}"
_STYLE_ROLES = {
    "TableCaption": (("TableCaption",), ("表タイトル", "Table Caption")),
    "ImageCaption": (("ImageCaption",), ("図タイトル", "Image Caption")),
    "SourceCode": (("SourceCode",), ("コードブロック", "Source Code")),
    "Equation": (("EquationBlock",), ("数式ブロック", "Equation Block")),
}


def publish(source: Path, output: Path) -> Path:
    """style参照と一覧更新設定を調整し、ZIP検証後にDOCXを公開する。

    Args:
        source: PANDOCが生成した中間DOCX。
        output: 最終DOCXの保存先。専用Task directory内に配置する。

    Returns:
        公開した最終DOCXのPath。

    Raises:
        OSError: 入出力を開けない場合。
        zipfile.BadZipFile: DOCXのZIP構造が壊れている場合。
        KeyError: 必須OOXML部品がない場合。
        ET.ParseError: OOXMLが不正な場合。
    """
    validate_docx(source)
    with temporary_task_directory(output.parent) as temporary:
        staged = temporary / output.name
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(staged, "w") as target:
            styles = _parse_xml(archive.read("word/styles.xml"))
            mappings, names = _style_mappings(styles)
            for info in archive.infolist():
                value = archive.read(info.filename)
                if info.filename == "word/document.xml":
                    value = _finalize_document(value, mappings, names)
                elif info.filename == "word/settings.xml":
                    value = _enable_field_updates(value)
                target.writestr(info, value)
        validate_docx(staged)
    return output


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

    namespace = {
        "m": _MATH_NAMESPACE,
        "w": _WORD_NAMESPACE,
        "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    }
    document = _parse_xml(value)
    body = document.find("w:body", namespace)
    if body is not None:
        children = list(body)
        for index, paragraph in enumerate(children):
            if (
                paragraph.find('.//pic:cNvPr[@descr="assets/cover.png"]', namespace)
                is None
            ):
                continue
            # 一覧より前へ表紙を移す。独立した改ページ段落は空白pageを生む。
            body.remove(paragraph)
            body.insert(0, paragraph)
            if (
                index + 1 < len(children)
                and children[index + 1].find('.//w:br[@w:type="page"]', namespace)
                is not None
            ):
                body.remove(children[index + 1])
            if all(
                child.tag in {f"{_WORD}sdt", f"{_WORD}sectPr"}
                for child in list(body)[1:]
            ):
                # 本文のない1ページPDFは、空の自動一覧を加えず表紙だけを公開する。
                for child in list(body)[1:]:
                    if child.tag == f"{_WORD}sdt":
                        body.remove(child)
            following = body[1] if len(body) > 1 else None
            if following is not None:
                first = (
                    following
                    if following.tag == f"{_WORD}p"
                    else following.find(".//w:p", namespace)
                )
                if first is not None:
                    properties = first.find("w:pPr", namespace)
                    if properties is None:
                        properties = ET.Element(f"{_WORD}pPr")
                        first.insert(0, properties)
                    ET.SubElement(properties, f"{_WORD}pageBreakBefore")
            break
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
