"""環境変数と用途別の設定を検証する。"""

from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(ValueError):
    """設定の値または組合せが操作の要件を満たさない。"""


class Config(BaseSettings):
    """環境変数を直接読む、PipelineとAdapterの共通設定。"""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_llm_base_url: str | None = None
    openai_llm_api_key: str | None = None
    openai_structure_model: str | None = None
    openai_translation_model: str | None = None
    openai_review_model: str | None = None
    openai_embedding_model: str | None = None

    docling_server_url: str | None = None
    docling_api_key: str | None = None
    docling_ocr_preset: str = "tesseract"
    docling_ocr_lang: str = "eng"
    docling_force_ocr: bool = False
    pdf_split_pages: int = Field(default=10, gt=0, le=100)

    qdrant_uri: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str | None = None

    http_retry_attempts: int = Field(default=6, gt=0, le=6)
    http_request_timeout_seconds: float = Field(default=3000, gt=0, le=3000)
    external_task_deadline_seconds: float = Field(default=21600, gt=0, le=21600)

    llm_context_tokens: int = Field(default=30208, gt=0)
    llm_image_tokens: int = Field(default=2048, gt=0)
    llm_safety_tokens: int = Field(default=1024, ge=1024)
    structure_input_tokens: int = Field(default=6144, gt=0)
    structure_output_tokens: int = Field(default=2048, gt=0)
    structure_max_blocks: int = Field(default=64, gt=0, le=64)
    translate_input_tokens: int = Field(default=8192, gt=0)
    translate_output_tokens: int = Field(default=4096, gt=0)
    translate_max_units: int = Field(default=64, gt=0, le=64)
    review_input_tokens: int = Field(default=8192, gt=0)
    review_output_tokens: int = Field(default=4096, gt=0)
    review_max_targets: int = Field(default=32, gt=0, le=32)
    llm_retry_attempts: int = Field(default=5, gt=0, le=5)
    llm_split_max_depth: int = Field(default=10, gt=0, le=10)
    llm_request_timeout_seconds: float = Field(default=1800, gt=0, le=1800)
    llm_task_deadline_seconds: float = Field(default=21600, gt=0, le=21600)

    llm_structured_output_mode: Literal["json_object", "json_schema", "prompt"] = (
        "json_object"
    )
    llm_schema_max_bytes: int = Field(default=8192, gt=0, le=16384)
    llm_schema_max_depth: int = Field(default=4, gt=0, le=6)
    llm_response_max_bytes: int = Field(default=262144, gt=0, le=1048576)
    review_max_findings: int = Field(default=32, gt=0, le=32)
    review_max_revisions: int = Field(default=32, gt=0, le=32)
    review_max_edits_per_revision: int = Field(default=16, gt=0, le=16)


def validate_config(config: Config, operation: str | None = None) -> None:
    """予算、任意RAG、操作に必要な環境変数を一か所で検証する。

    Args:
        config: 型と数値範囲の検証を終えた設定。
        operation: translate、review、upgrade、register。Noneは共通検証のみ。

    Raises:
        ConfigError: 予算超過、部分的なRAG設定、必須項目の不足がある場合。
    """
    for task in ("structure", "translate", "review"):
        total = (
            getattr(config, f"{task}_input_tokens")
            + getattr(config, f"{task}_output_tokens")
            + config.llm_safety_tokens
            + (config.llm_image_tokens if task == "structure" else 0)
        )
        if total > config.llm_context_tokens:
            raise ConfigError(
                f"{task.upper()} token budget {total} exceeds "
                f"LLM_CONTEXT_TOKENS={config.llm_context_tokens}"
            )
    rag = (config.openai_embedding_model, config.qdrant_uri, config.qdrant_collection)
    if any(rag) and not all(rag):
        raise ConfigError("Qdrant RAG settings must be complete")
    required: list[str] = []
    if all(rag):
        required.append("openai_base_url")
    if operation:
        if operation not in {"translate", "review", "upgrade", "register"}:
            raise ConfigError(f"Unknown operation: {operation}")
        required.append("docling_server_url")
        if operation == "register":
            required.extend(
                (
                    "openai_base_url",
                    "openai_embedding_model",
                    "qdrant_uri",
                    "qdrant_collection",
                )
            )
        else:
            if not (config.openai_llm_base_url or config.openai_base_url):
                raise ConfigError("OPENAI_LLM_BASE_URL or OPENAI_BASE_URL is required")
            required.append("openai_review_model")
            if operation == "translate":
                required.extend(("openai_structure_model", "openai_translation_model"))
    missing = [
        name.upper() for name in required if not (getattr(config, name) or "").strip()
    ]
    if missing:
        raise ConfigError("Required settings: " + ", ".join(missing))


def load_config(directory: Path | None = None, operation: str | None = None) -> Config:
    """作業directoryの.envを読み、process環境変数を優先して検証する。

    Args:
        directory: .envを探す場所。省略時は現在の作業directory。
        operation: 用途別の必須項目も検証する場合の操作名。

    Returns:
        数値範囲、token予算、用途の組合せを検証済みの設定。

    Raises:
        ConfigError: 環境変数の型、範囲、組合せが不正な場合。
    """
    try:
        config = Config(_env_file=(directory or Path.cwd()) / ".env")
    except ValidationError as error:
        # ValidationErrorの入力値には認証情報が含まれ得るため表示しない。
        details = "; ".join(
            f"{'.'.join(map(str, item['loc']))}: {item['type']}"
            for item in error.errors(include_input=False)
        )
        raise ConfigError(details) from None
    validate_config(config, operation)
    return config
