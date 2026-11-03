"""Pandocの中間DOCXを仕上げ、検証済みの最終DOCXを公開する。"""

from pathlib import Path
from typing import Any

import docx
from docx.document import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import nsmap, qn
from docx.text.paragraph import Paragraph

from translate.adapters.artifact_store import temporary_task_directory
from translate.adapters.pandoc import validate_docx

_STYLE_ROLES = {
    "TableCaption": (("TableCaption",), ("表タイトル", "Table Caption")),
    "ImageCaption": (("ImageCaption",), ("図タイトル", "Image Caption")),
    "SourceCode": (("SourceCode",), ("コードブロック", "Source Code")),
    "Equation": (("EquationBlock",), ("数式ブロック", "Equation Block")),
}
_DISABLED = {"0", "false", "off"}


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
    """
    validate_docx(source)
    with temporary_task_directory(output.parent) as temporary:
        staged = temporary / output.name
        document = docx.Document(str(source))
        mappings, names = _style_mappings(document)
        _finalize_document(document, mappings, names)
        _enable_field_updates(document)
        document.save(str(staged))
        validate_docx(staged)
    return output


def _style_mappings(document: Document) -> tuple[dict[str, str], dict[str, str]]:
    """Pandoc style IDからtemplate style IDと表示名への対応を得る。

    Args:
        document: Style定義を持つDOCX。

    Returns:
        Pandoc style IDをtemplate style IDへ写す辞書と、表示名へ写す辞書。
    """

    # python-docxの表示名は組込み名を読み替えるため、XML上のw:nameで照合する。
    by_name: dict[str, Any] = {}
    by_id: dict[str, Any] = {}
    for style in document.styles.element.style_lst:
        name = style.name_val
        if style.styleId:
            by_id[style.styleId] = style
        if name:
            by_name[name] = style
    mappings: dict[str, str] = {}
    names: dict[str, str] = {}
    for source_id, (preferred_ids, preferred_names) in _STYLE_ROLES.items():
        candidates = [by_name[value] for value in preferred_names if value in by_name]
        candidates += [by_id[value] for value in preferred_ids if value in by_id]
        style = candidates[0] if candidates else None
        if style is not None and style.styleId and style.name_val:
            mappings[source_id] = style.styleId
            names[source_id] = style.name_val
    return mappings, names


def _move_cover_first(document: Document) -> None:
    """表紙を一覧より前へ移し、後続の先頭段落から改ページする。

    Args:
        document: 表紙画像を含む可能性があるDOCX。
    """

    body = document.element.body
    children = list(body)
    for index, paragraph in enumerate(children):
        if paragraph.find('.//pic:cNvPr[@descr="assets/cover.png"]', nsmap) is None:
            continue
        # 一覧より前へ表紙を移す。独立した改ページ段落は空白pageを生む。
        body.remove(paragraph)
        body.insert(0, paragraph)
        if (
            index + 1 < len(children)
            and children[index + 1].find('.//w:br[@w:type="page"]', nsmap) is not None
        ):
            body.remove(children[index + 1])
        rest = list(body)[1:]
        if all(child.tag in {qn("w:sdt"), qn("w:sectPr")} for child in rest):
            # 本文のない1ページPDFは、空の自動一覧を加えず表紙だけを公開する。
            for child in rest:
                if child.tag == qn("w:sdt"):
                    body.remove(child)
        following = body[1] if len(body) > 1 else None
        if following is not None:
            first = (
                following
                if following.tag == qn("w:p")
                else following.find(".//w:p", nsmap)
            )
            if first is not None:
                Paragraph(first, document).paragraph_format.page_break_before = True
        return


def _keep_table_rows(document: Document) -> None:
    """表の行途中での改ページを抑止し、見出し行を最初の本文行とつなぐ。

    Args:
        document: 表を含む可能性があるDOCX。
    """

    for row in document.element.body.xpath(".//w:tr"):
        properties = row.get_or_add_trPr()
        keep_row = properties.find(qn("w:cantSplit"))
        if keep_row is None:
            keep_row = OxmlElement("w:cantSplit")
            properties.append(keep_row)
        keep_row.set(qn("w:val"), "true")
        header = properties.find(qn("w:tblHeader"))
        if header is None or header.get(qn("w:val")) in _DISABLED:
            continue
        for paragraph in row.xpath(".//w:p"):
            Paragraph(paragraph, document).paragraph_format.keep_with_next = True


def _finalize_document(
    document: Document,
    mappings: dict[str, str],
    names: dict[str, str],
) -> None:
    """本文のstyle参照・一覧fieldを整え、表の行途中での改ページを抑止する。

    Args:
        document: 更新するDOCX。
        mappings (dict[str, str]): 旧Style IDからTemplate Style IDへの対応表。
        names (dict[str, str]): Style IDと表示名の対応表。
    """

    _move_cover_first(document)
    _keep_table_rows(document)
    body = document.element.body
    for style in body.xpath(".//w:pStyle"):
        current = style.get(qn("w:val"))
        if current in mappings:
            style.set(qn("w:val"), mappings[current])
    equation_style = mappings.get("Equation")
    if equation_style is not None:
        for paragraph in body.xpath(".//w:p[m:oMathPara]"):
            paragraph.get_or_add_pPr().style = equation_style
    for instruction in body.xpath(".//w:instrText"):
        if instruction.text is None:
            continue
        instruction.text = instruction.text.replace(
            "Image Caption", names.get("ImageCaption", "Image Caption")
        ).replace("Table Caption", names.get("TableCaption", "Table Caption"))
    for field in body.xpath('.//w:fldChar[@w:fldCharType="begin"]'):
        field.set(qn("w:dirty"), "true")


def _enable_field_updates(document: Document) -> None:
    """Wordで開いた時に目次、図一覧および表一覧を更新させる。

    Args:
        document: Field自動更新を設定するDOCX。
    """

    settings = document.settings.element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")
