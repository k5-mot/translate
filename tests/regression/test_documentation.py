"""公開文書の相対linkと環境変数名を検査する。"""

from __future__ import annotations

import ast
import html
import io
import re
import shutil
import tokenize
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from translate.adapters.pdf import page_count
from translate.tasks.publisher.docx import publish

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Linterや型検査の制御指定だけでは、関数の目的説明を代替できない。
CONTROL_COMMENTS = ("noqa", "type: ignore", "ty: ignore", "pragma:", "ruff:")
ENV_NAMES = {
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_STRUCTURE_MODEL",
    "OPENAI_REVIEW_MODEL",
    "OPENAI_TRANSLATION_MODEL",
    "OPENAI_EMBEDDING_MODEL",
    "LLM_CONTEXT_TOKENS",
    "LLM_IMAGE_TOKENS",
    "LLM_SAFETY_TOKENS",
    "STRUCTURE_INPUT_TOKENS",
    "STRUCTURE_OUTPUT_TOKENS",
    "STRUCTURE_MAX_BLOCKS",
    "TRANSLATE_INPUT_TOKENS",
    "TRANSLATE_OUTPUT_TOKENS",
    "TRANSLATE_MAX_UNITS",
    "REVIEW_INPUT_TOKENS",
    "REVIEW_OUTPUT_TOKENS",
    "REVIEW_MAX_TARGETS",
    "LLM_RETRY_ATTEMPTS",
    "LLM_SPLIT_MAX_DEPTH",
    "LLM_REQUEST_TIMEOUT_SECONDS",
    "LLM_TASK_DEADLINE_SECONDS",
    "LLM_STRUCTURED_OUTPUT_MODE",
    "LLM_SCHEMA_MAX_BYTES",
    "LLM_SCHEMA_MAX_DEPTH",
    "LLM_RESPONSE_MAX_BYTES",
    "REVIEW_MAX_FINDINGS",
    "REVIEW_MAX_REVISIONS",
    "REVIEW_MAX_EDITS_PER_REVISION",
    "DOCLING_SERVER_URL",
    "DOCLING_API_KEY",
    "DOCLING_OCR_PRESET",
    "DOCLING_OCR_LANG",
    "DOCLING_FORCE_OCR",
    "PDF_SPLIT_PAGES",
    "HTTP_RETRY_ATTEMPTS",
    "HTTP_REQUEST_TIMEOUT_SECONDS",
    "EXTERNAL_TASK_DEADLINE_SECONDS",
    "LIBRETRANSLATE_URL",
    "LIBRETRANSLATE_API_KEY",
    "QDRANT_API_KEY",
    "QDRANT_URI",
    "QDRANT_COLLECTION",
}
VISIBLE_WORD_PART = re.compile(
    r"word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml"
)
WORD_TEXT_NODE = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)
JAPANESE_CHARACTER = re.compile(r"[\u3000\u3040-\u30ff\u3400-\u9fff]")


def test_readme_relative_links_exist() -> None:
    """README内のlocal Markdown linkが存在する。"""

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\[[^]]+\]\((?!https?://)([^)#]+)", readme)

    assert links
    assert all((PROJECT_ROOT / link).is_file() for link in links)


def test_env_sample_uses_supported_setting_names() -> None:
    """環境変数雛形に廃止済みまたは無関係な設定を混在させない。"""

    lines = (PROJECT_ROOT / ".env.sample").read_text(encoding="utf-8").splitlines()
    names = {
        line.partition("=")[0] for line in lines if line and not line.startswith("#")
    }

    assert names == ENV_NAMES


def test_run_layout_names_are_consistent() -> None:
    """新しい成果物rootと処理IDの配置を一貫して文書化する。"""

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "`outputs/<file-basename>/<uuidv7>/`" in readme
    assert "`translation.json`" in readme
    assert "`review.json`" in readme
    assert "`registration.json`" in readme
    assert "runs/" not in readme


def test_repository_sample_pdf_is_a_runnable_fixture() -> None:
    """Clone直後に利用するsample PDFが存在し、有効なpageを持つ。"""

    assert page_count(PROJECT_ROOT / "inputs/sample.pdf") == 14


def test_bundled_docx_template_has_english_page_furniture() -> None:
    """同梱templateの表示文を英語に限定し、headerとfooter仕様を保持する。"""

    template = PROJECT_ROOT / "translate/templates/template.docx"
    text_by_part: dict[str, str] = {}
    with zipfile.ZipFile(template) as archive:
        for name in archive.namelist():
            if not VISIBLE_WORD_PART.fullmatch(name):
                continue
            xml = archive.read(name).decode("utf-8")
            text_by_part[name] = "".join(
                html.unescape(text) for text in WORD_TEXT_NODE.findall(xml)
            )

    visible_text = "".join(text_by_part.values())
    header_text = "".join(
        text for name, text in text_by_part.items() if "/header" in name
    )
    footer_text = "".join(
        text for name, text in text_by_part.items() if "/footer" in name
    )

    assert not JAPANESE_CHARACTER.search(visible_text)
    assert "Example System Detail Design Specification" in header_text
    assert "SYS-DD-001" in header_text
    assert "CONFIDENTIAL / Example Corporation" in footer_text
    assert "Last updated: " in footer_text


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is required")
def test_docx_publication_applies_template_styles_and_embeds_images(
    tmp_path: Path,
) -> None:
    """DOCX公開後も一覧、装飾styleおよび相対path画像を有効に保つ。"""

    markdown = PROJECT_ROOT / "translate/templates/sample.md"
    template = PROJECT_ROOT / "translate/templates/template.docx"
    placeholder = PROJECT_ROOT / "translate/templates/placeholder.png"
    output = tmp_path / "sample.docx"

    publish(markdown, output, template, 30.0)

    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    namespaces = {"w": word}
    with zipfile.ZipFile(output) as archive:
        # 製品処理が直前に生成した固定fixtureのOOXMLだけを検証する。
        document = ET.fromstring(archive.read("word/document.xml"))  # noqa: S314
        settings = ET.fromstring(archive.read("word/settings.xml"))  # noqa: S314
        styles = ET.fromstring(archive.read("word/styles.xml"))  # noqa: S314
        media = [
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/media/")
        ]

    styles_by_name = {
        name.get(f"{{{word}}}val"): style
        for style in styles.findall("w:style", namespaces)
        if (name := style.find("w:name", namespaces)) is not None
    }
    styles_by_id = {
        style.get(f"{{{word}}}styleId"): style
        for style in styles.findall("w:style", namespaces)
    }
    paragraph_styles = {
        style.get(f"{{{word}}}val")
        for style in document.findall(".//w:pStyle", namespaces)
    }
    field_codes = "\n".join(
        node.text or "" for node in document.findall(".//w:instrText", namespaces)
    )

    table_caption = styles_by_name["表タイトル"]
    image_caption = styles_by_name["図タイトル"]
    caption_base_id = table_caption.find("w:basedOn", namespaces).get(f"{{{word}}}val")
    caption_base = styles_by_id[caption_base_id]
    assert caption_base.find("w:pPr/w:jc", namespaces).get(f"{{{word}}}val") == "center"
    assert (
        image_caption.find("w:basedOn", namespaces).get(f"{{{word}}}val")
        == caption_base_id
    )
    assert table_caption.get(f"{{{word}}}styleId") in paragraph_styles
    assert image_caption.get(f"{{{word}}}styleId") in paragraph_styles

    for name in ("コードブロック", "数式ブロック"):
        style = styles_by_name[name]
        assert style.get(f"{{{word}}}styleId") in paragraph_styles
        assert style.find("w:pPr/w:pBdr", namespaces) is not None

    note_styles = [
        style
        for style in styles.findall("w:style", namespaces)
        if style.get(f"{{{word}}}styleId") == "Note"
    ]
    assert len(note_styles) == 1
    assert note_styles[0].find("w:pPr/w:shd", namespaces) is not None
    assert "Note" in paragraph_styles

    assert settings.find("w:updateFields", namespaces).get(f"{{{word}}}val") == "true"
    assert 'TOC \\o "1-6"' in field_codes
    assert "図タイトル" in field_codes
    assert "表タイトル" in field_codes
    assert placeholder.read_bytes() in media


def _missing_function_explanations(source: str) -> list[str]:
    """可視性を問わず関数の説明欠落を検出する。説明内容の正しさは別途確認する。"""

    lines = source.splitlines()
    comments = {
        token.start
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
        and not lines[token.start[0] - 1][: token.start[1]].strip()
        and (text := token.string.lstrip("# ").strip())
        and any(character.isalnum() for character in text)
        and not text.casefold().startswith(CONTROL_COMMENTS)
    }
    missing: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        docstring = ast.get_docstring(node)
        if docstring is not None:
            explained = bool(docstring.strip())
        else:
            start = min([node.lineno, *(item.lineno for item in node.decorator_list)])
            adjacent = {
                (start - 1, node.col_offset),
                (node.body[0].lineno - 1, node.body[0].col_offset),
            }
            explained = bool(comments & adjacent)
        if not explained:
            missing.append(f"{node.lineno}:{node.name}")
    return missing


@pytest.mark.parametrize(
    ("source", "missing_names"),
    [
        ("def public():\n    pass\n", ["public"]),
        ("def _private():\n    pass\n", ["_private"]),
        ("async def fetch():\n    pass\n", ["fetch"]),
        ("class Hidden:\n    def __init__(self):\n        pass\n", ["__init__"]),
        (
            (
                'def outer():\n    """Prepare the nested fixture."""\n'
                "    def inner():\n        pass\n"
            ),
            ["inner"],
        ),
        ('def described():\n    """Provide a fixed fixture."""\n    pass\n', []),
        ("# Provide a fixed fixture.\ndef described():\n    pass\n", []),
        (
            "# Provide a fixed fixture.\n@fixture()\ndef described():\n    pass\n",
            [],
        ),
        ("def described():\n    # Provide a fixed fixture.\n    pass\n", []),
        ('def empty():\n    """   """\n    pass\n', ["empty"]),
        (
            '# Keep the empty docstring invalid.\ndef empty():\n    """ """\n',
            ["empty"],
        ),
        ("# noqa: D103\ndef missing():\n    pass\n", ["missing"]),
        ("def missing():\n    # type: ignore\n    pass\n", ["missing"]),
        ("def missing():\n    # ty: ignore[rule]\n    pass\n", ["missing"]),
        ("def missing():\n    # ---\n    pass\n", ["missing"]),
        (
            "def missing():\n    value = 1  # inline only\n    return value\n",
            ["missing"],
        ),
        (
            "# Module comment.\nvalue = 1\ndef missing():\n    return value\n",
            ["missing"],
        ),
    ],
)
def test_function_explanations_cover_private_nested_and_comment_forms(
    source: str, missing_names: list[str]
) -> None:
    """非公開・入れ子・特殊methodを含め、説明と制御Commentを区別できるか検証する。"""

    missing = _missing_function_explanations(source)

    assert [item.partition(":")[2] for item in missing] == missing_names


def test_all_python_functions_have_explanations() -> None:
    """公開入口・製品・Testの全関数で説明の存在を検査し、欠落位置を一覧にする。"""

    paths = [PROJECT_ROOT / "main.py"]
    for directory in ("translate", "tests"):
        paths.extend(sorted((PROJECT_ROOT / directory).rglob("*.py")))
    missing = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{location}"
        for path in paths
        for location in _missing_function_explanations(path.read_text(encoding="utf-8"))
    ]

    assert not missing, "\n".join(missing)
