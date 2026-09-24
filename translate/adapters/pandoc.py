"""PandocによるDOCX入出力を提供する。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
W = f"{{{W_NS}}}"
WP = f"{{{WP_NS}}}"
REL = f"{{{REL_NS}}}"
FRONT_MATTER_TITLES = {
    "Table of Contents": "目次",
    "List of Figures": "図一覧",
    "List of Tables": "表一覧",
}

ET.register_namespace("w", W_NS)
ET.register_namespace("wp", WP_NS)
ET.register_namespace(
    "r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)


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
        for option in ("--list-of-figures", "--list-of-tables")
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
                # 数値表の連続ピリオドやdashをsmart punctuationで書換えない。
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
        )
        _normalize_docx(temporary)
        _validate_docx(temporary, "Pandoc generated an invalid DOCX package")
        _publish_docx(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def table_to_markdown(table: dict[str, object]) -> str:
    """構造化された表を既存Pandocでgrid tableへ直列化する。"""

    executable = shutil.which("pandoc") or "pandoc"
    # API versionを固定せず、実行中のPandocから空文書のJSON envelopeを得る。
    envelope = json.loads(
        subprocess.run(
            [executable, "--from", "markdown", "--to", "json"],
            input="",
            check=True,
            capture_output=True,
            encoding="utf-8",
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
    ).stdout.strip()


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
            entries = {name: archive.read(name) for name in archive.namelist()}
        _validate_docx_layout(entries)
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError(message) from error


def _validate_docx_layout(entries: dict[str, bytes]) -> None:
    document_data = entries.get("word/document.xml")
    if document_data is None:
        return
    try:
        root = ET.fromstring(document_data)  # noqa: S314
    except ET.ParseError as error:
        raise RuntimeError("DOCX document.xml is malformed") from error
    if any(f"{W}dirty" in element.attrib for element in root.iter()):
        raise RuntimeError("DOCX contains a dirty field update marker")
    if root.findall(f".//{W}rStyle[@{W}val='SectionNumber']"):
        raise RuntimeError("DOCX contains explicit SectionNumber runs")
    body = root.find(f"{W}body")
    if body is None:
        return
    children = list(body)
    cover_indices = [
        index for index, item in enumerate(children) if _is_cover_paragraph(item)
    ]
    if len(cover_indices) > 1:
        raise RuntimeError("DOCX must contain exactly one cover image")
    list_indices = [
        index for index, item in enumerate(children) if _is_generated_front_matter(item)
    ]
    if cover_indices and list_indices and cover_indices[0] > min(list_indices):
        raise RuntimeError("DOCX front matter appears before the cover")
    for paragraph in children:
        style = paragraph.find(f".//{W}pStyle")
        if style is not None and style.get(f"{W}val") == "ImageCaption":
            text = "".join(paragraph.itertext()).strip()
            if text.endswith("表紙") or text == "表紙":
                raise RuntimeError("DOCX contains a cover caption")
    _reject_external_file_relationships(entries)


def _normalize_docx(path: Path) -> None:
    """Normalize Word fields and the cover/front-matter order in a DOCX.

    Pandoc emits generated TOC/list SDTs before Markdown content.  The cover is
    a Markdown image and is therefore also emitted as a normal body paragraph;
    moving the generated SDTs after that paragraph gives Word users the expected
    cover-first document without adding another converter or dependency.
    """

    try:
        with zipfile.ZipFile(path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError("Pandoc generated an invalid DOCX package") from error
    document_name = "word/document.xml"
    document_data = entries.get(document_name)
    if document_data is None:
        return
    try:
        root = ET.fromstring(document_data)  # noqa: S314
    except ET.ParseError as error:
        raise RuntimeError("Pandoc generated malformed word/document.xml") from error
    body = root.find(f"{W}body")
    if body is not None:
        _remove_dirty_fields(root)
        _reorder_front_matter(body)
        _populate_front_matter(body)
        _normalize_table_widths(body)
        entries[document_name] = ET.tostring(
            root, encoding="utf-8", xml_declaration=True
        )
    settings_data = entries.get("word/settings.xml")
    if settings_data is not None:
        entries["word/settings.xml"] = _remove_update_fields(settings_data)
    styles_data = entries.get("word/styles.xml")
    if styles_data is not None:
        entries["word/styles.xml"] = _remove_heading_numbering(styles_data)
    _reject_external_file_relationships(entries)
    temporary = path.with_name(f".{path.name}.normalized")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_dirty_fields(root: ET.Element) -> None:
    """Prevent Word from asking to update generated fields on open."""

    for element in root.iter():
        element.attrib.pop(f"{W}dirty", None)
    # Settings are handled by the package rewrite caller; document fields are
    # the prompt trigger in Pandoc's generated output, so no external update
    # flag is introduced here.


def _remove_update_fields(data: bytes) -> bytes:
    try:
        root = ET.fromstring(data)  # noqa: S314
    except ET.ParseError as error:
        raise RuntimeError("Malformed Word settings part") from error
    for element in list(root):
        if element.tag == f"{W}updateFields":
            root.remove(element)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _remove_heading_numbering(data: bytes) -> bytes:
    """本文の番号を保持し、見出しスタイル由来の二重採番を抑止する。"""

    root = ET.fromstring(data)  # noqa: S314
    for style in root.findall(f"{W}style"):
        if style.get(f"{W}styleId") not in {f"Heading{i}" for i in range(1, 10)}:
            continue
        properties = style.find(f"{W}pPr")
        if properties is not None:
            for numbering in properties.findall(f"{W}numPr"):
                properties.remove(numbering)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _index_paragraph(text: str, style: str) -> ET.Element:
    paragraph = ET.Element(f"{W}p")
    properties = ET.SubElement(paragraph, f"{W}pPr")
    ET.SubElement(properties, f"{W}pStyle", {f"{W}val": style})
    ET.SubElement(ET.SubElement(paragraph, f"{W}r"), f"{W}t").text = text
    return paragraph


def _normalize_table_widths(body: ET.Element) -> None:
    """空白の少ない日本語セルが短い数値列を圧迫するのを防ぐ。"""

    for table in body.iter(f"{W}tbl"):
        columns = table.findall(f"{W}tblGrid/{W}gridCol")
        widths = [int(column.get(f"{W}w", "0")) for column in columns]
        total = sum(widths)
        if not total or min(widths) >= total / (2 * len(columns)):
            continue
        # 各列へ均等幅の半分を最低保証し、残り半分を元の比率で配分する。
        # 全体幅と列数・結合位置は変えず、極端な一文字幅の列を回避する。
        adjusted = [round(total / (2 * len(columns)) + width / 2) for width in widths]
        adjusted[-1] += total - sum(adjusted)
        for column, width in zip(columns, adjusted, strict=True):
            column.set(f"{W}w", str(width))


def _index_entries(body: ET.Element) -> dict[str, list[ET.Element]]:
    """変換済み本文から一覧を得る。Code、表紙および一覧自身は対象外。"""

    entries: dict[str, list[ET.Element]] = {key: [] for key in FRONT_MATTER_TITLES}
    styles = {f"Heading{i}": ("Table of Contents", f"TOC{i}") for i in range(1, 7)}
    styles.update(
        {
            "ImageCaption": ("List of Figures", "TOC1"),
            "TableCaption": ("List of Tables", "TOC1"),
        }
    )
    for child in body:
        if _is_generated_front_matter(child):
            continue
        for paragraph in child.iter(f"{W}p"):
            style = paragraph.find(f"{W}pPr/{W}pStyle")
            target = styles.get(style.get(f"{W}val", "")) if style is not None else None
            text = "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()
            if target and text:
                gallery, entry_style = target
                entries[gallery].append(_index_paragraph(text, entry_style))
    return entries


def _populate_front_matter(body: ET.Element) -> None:
    """Wordの更新操作なしで読める一覧と、一覧ごとの改ページを保存する。"""

    entries = _index_entries(body)
    children = list(body)
    result: list[ET.Element] = []
    for index, child in enumerate(children):
        result.append(child)
        if not _is_generated_front_matter(child):
            continue
        gallery = child.find(f".//{W}docPartGallery")
        assert gallery is not None
        key = gallery.get(f"{W}val", "")
        content = child.find(f"{W}sdtContent")
        if content is None:
            content = ET.SubElement(child, f"{W}sdtContent")
        content[:] = [
            _index_paragraph(FRONT_MATTER_TITLES[key], "TOCHeading"),
            *entries[key],
        ]
        # 二度正規化しても改ページを増やさない。
        if index + 1 == len(children) or not _is_page_break(children[index + 1]):
            page_break = ET.Element(f"{W}p")
            ET.SubElement(
                ET.SubElement(page_break, f"{W}r"), f"{W}br", {f"{W}type": "page"}
            )
            result.append(page_break)
    body[:] = result


def _is_cover_paragraph(element: ET.Element) -> bool:
    if element.tag != f"{W}p":
        return False
    return any(node.get("descr") == "表紙" for node in element.iter(f"{WP}docPr"))


def _is_page_break(element: ET.Element) -> bool:
    return element.tag == f"{W}p" and any(
        br.get(f"{W}type") == "page" for br in element.iter(f"{W}br")
    )


def _is_generated_front_matter(element: ET.Element) -> bool:
    if element.tag != f"{W}sdt":
        return False
    gallery = element.find(f".//{W}docPartGallery")
    return gallery is not None and gallery.get(f"{W}val") in {
        "Table of Contents",
        "List of Figures",
        "List of Tables",
    }


def _reorder_front_matter(body: ET.Element) -> None:
    """Place cover first and retain only its image before generated lists."""

    children = list(body)
    front_matter = []
    for index, item in enumerate(children):
        if _is_generated_front_matter(item):
            front_matter.append(item)
            if index + 1 < len(children) and _is_page_break(children[index + 1]):
                front_matter.append(children[index + 1])
    if not front_matter:
        return
    cover_index = next(
        (index for index, item in enumerate(children) if _is_cover_paragraph(item)),
        None,
    )
    if cover_index is None:
        return
    cover = children[cover_index]
    cover_count = sum(1 for item in children if _is_cover_paragraph(item))
    if cover_count != 1:
        raise RuntimeError("DOCX must contain exactly one cover image")
    break_index = next(
        (
            index
            for index in range(cover_index + 1, len(children))
            if _is_page_break(children[index])
        ),
        None,
    )
    if break_index is None:
        raise RuntimeError("DOCX cover is missing its page break")
    page_break = children[break_index]
    # Drop generated lists from their Pandoc position and discard everything
    # between the cover image and page break (usually the automatic cover
    # caption).  The source PDF's first-page body is excluded upstream.
    tail = [item for item in children[break_index + 1 :] if item not in front_matter]
    body[:] = [cover, page_break, *front_matter, *tail]


def _reject_external_file_relationships(entries: dict[str, bytes]) -> None:
    """Reject file/UNC relationships that can trigger Word's update prompt."""

    for name, data in entries.items():
        if not name.endswith(".rels"):
            continue
        try:
            root = ET.fromstring(data)  # noqa: S314
        except ET.ParseError as error:
            raise RuntimeError(f"Malformed relationship part: {name}") from error
        for relationship in root.findall(f"{REL}Relationship"):
            if relationship.get("TargetMode") != "External":
                continue
            target = relationship.get("Target", "")
            lowered = target.casefold()
            if lowered.startswith(("file:", "\\\\")) or (
                len(target) >= 2 and target[1] == ":"
            ):
                raise RuntimeError("DOCX contains an external file relationship")


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
