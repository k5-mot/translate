"""公開文書の相対linkと環境変数名を検査する。"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
