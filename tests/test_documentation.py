"""公開文書の相対linkと環境変数名を検査する。"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Linterや型検査の制御指定だけでは、関数の目的説明を代替できない。
CONTROL_COMMENTS = ("noqa", "type: ignore", "ty: ignore", "pragma:", "ruff:")
ENV_NAMES = {
    "TRANSLATE_RUNS_DIR",
    "TRANSLATE_RETRY_ATTEMPTS",
    "TRANSLATE_RETRY_BASE_SECONDS",
    "TRANSLATE_RETRY_MAX_SECONDS",
    "TRANSLATE_REQUEST_TIMEOUT_SECONDS",
    "TRANSLATE_TASK_DEADLINE_SECONDS",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_STRUCTURE_MODEL",
    "OPENAI_REVIEW_MODEL",
    "OPENAI_TRANSLATION_MODEL",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_FIX_MODEL",
    "LLM_CONTEXT_TOKENS",
    "LLM_OUTPUT_TOKENS",
    "LLM_IMAGE_TOKENS",
    "DOCLING_SERVER_URL",
    "DOCLING_API_KEY",
    "DOCLING_OCR_PRESET",
    "DOCLING_OCR_LANG",
    "DOCLING_FORCE_OCR",
    "PDF_SPLIT_PAGES",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_OTEL_HOST",
    "LIBRETRANSLATE_URL",
    "LIBRETRANSLATE_API_KEY",
    "QDRANT_API_KEY",
    "QDRANT_URI",
    "QDRANT_COLLECTION",
}


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
    """Lifecycle metadataとWorkflow metadataの同名衝突を文書化しない。"""

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    operations = (PROJECT_ROOT / "docs" / "operations.md").read_text(encoding="utf-8")

    assert "root直下の`<run-id>/run.json`" in readme
    assert "`.workspace/workflow.json`" in readme
    assert "root直下の`run.json`" in operations
    assert "`.workspace/workflow.json`" in operations
    assert ".workspace/run.json" not in readme + operations
    assert "旧`.work/`" in operations


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

    paths = [PROJECT_ROOT / "cli.py", PROJECT_ROOT / "main.py"]
    for directory in ("translate", "tests"):
        paths.extend(sorted((PROJECT_ROOT / directory).rglob("*.py")))
    missing = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{location}"
        for path in paths
        for location in _missing_function_explanations(path.read_text(encoding="utf-8"))
    ]

    assert not missing, "\n".join(missing)
