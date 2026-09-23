"""環境変数を検証し、実行設定を提供する。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, model_validator

if TYPE_CHECKING:
    from collections.abc import Mapping

Backend = Literal["llm", "libretranslate"]
Command = Literal["translate", "review", "register", "convert"]
# The deployed Gemma endpoint exposes a 30,208-token context window.
GEMMA_MAX_CONTEXT = 30_208
# Keep generation finite while leaving room for input, schema instructions, and images.
DEFAULT_OUTPUT_TOKENS = 16_384
DEFAULT_IMAGE_TOKENS = 2_048
DEFAULT_REQUEST_TIMEOUT_SECONDS = 1_800.0
# A fixed reserve absorbs tokenizer estimation and provider framing overhead.
LLM_SAFETY_TOKENS = 1_024
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    """一回の実行で共有する検証済み設定。"""

    model_config = ConfigDict(frozen=True)

    # CLI and Streamlit share durable runs under this absolute root.
    runs_dir: Path = PROJECT_ROOT / "runs"
    retry_attempts: int = 3
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 30.0
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    task_deadline_seconds: float = 21_600.0

    # Docling transport and OCR accuracy controls.
    docling_url: str | None = None
    docling_api_key: str | None = None
    # `tesseract` selects the server preset; `eng` is its trained-data code.
    docling_ocr_preset: str = "tesseract"
    docling_ocr_lang: str = "eng"
    # Keep false for digital PDFs; true discards their text layer and OCRs all pages.
    docling_force_ocr: bool = False

    # OpenAI-compatible endpoint and purpose-specific model assignments.
    openai_base_url: str = ""
    openai_api_key: str = ""
    # STRUCTURE disables reasoning; translation/review/fix use high reasoning.
    structure_model: str | None = None
    translation_model: str | None = None
    review_model: str | None = None
    fix_model: str | None = None
    embedding_model: str | None = None

    # Gemma has a 30,208-token hard ceiling in this deployment.
    context_tokens: int = GEMMA_MAX_CONTEXT
    # Output, image, and safety reservations are subtracted from input capacity.
    output_tokens: int = DEFAULT_OUTPUT_TOKENS
    image_tokens: int = DEFAULT_IMAGE_TOKENS

    # Optional alternate translation backend.
    libretranslate_url: str | None = None
    libretranslate_api_key: str | None = None

    # Optional tracing. Missing keys disable tracing without blocking a run.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_otel_host: str | None = None

    # RAG is enabled only when endpoint, collection, and embedding model all exist.
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str | None = None
    # Rules and the Pandoc reference document ship with this package.
    templates_dir: Path
    # Smaller parts reduce Docling retry cost; 10 pages is the operational default.
    split_pages: int = 10

    @property
    def qdrant_enabled(self) -> bool:
        """RAG検索に必要な設定が揃っているか返す。"""

        return bool(self.qdrant_url and self.qdrant_collection and self.embedding_model)

    @property
    def langfuse_enabled(self) -> bool:
        """Langfuse認証情報が揃っているか返す。"""

        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def available_input_tokens(self) -> int:
        """Model contextから有限予約を除いたrequest入力上限を返す。"""

        return (
            self.context_tokens
            - self.output_tokens
            - self.image_tokens
            - LLM_SAFETY_TOKENS
        )

    @model_validator(mode="after")
    def validate_token_budget(self) -> Settings:
        """Tokenizer誤差とは別に最低1,024 tokensの入力領域を保証する。"""

        if self.available_input_tokens < 1_024:
            msg = (
                "LLM_OUTPUT_TOKENS and LLM_IMAGE_TOKENS must leave at least "
                "1024 input tokens after the 1024-token safety reserve"
            )
            raise ValueError(msg)
        return self


def _positive(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as error:
        msg = f"{name} must be a positive integer"
        raise ValueError(msg) from error
    if value <= 0:
        msg = f"{name} must be a positive integer"
        raise ValueError(msg)
    return value


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    try:
        value = float(env.get(name, str(default)))
    except ValueError as error:
        msg = f"{name} must be a positive number"
        raise ValueError(msg) from error
    if value <= 0:
        msg = f"{name} must be a positive number"
        raise ValueError(msg)
    return value


def _runs_dir(value: str | None) -> Path:
    path = Path(value).expanduser() if value else PROJECT_ROOT / "runs"
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_settings(
    command: Command,
    backend: Backend = "llm",
    env: Mapping[str, str] | None = None,
) -> Settings:
    """commandで実際に使用する環境変数だけを検証する。"""

    if env is None:
        load_dotenv()
        env = os.environ
    # Note 1: Never accept a larger environment value than the deployed model limit.
    context_tokens = min(
        _positive(env, "LLM_CONTEXT_TOKENS", GEMMA_MAX_CONTEXT),
        GEMMA_MAX_CONTEXT,
    )
    output_tokens = _positive(env, "LLM_OUTPUT_TOKENS", DEFAULT_OUTPUT_TOKENS)
    image_tokens = _positive(env, "LLM_IMAGE_TOKENS", DEFAULT_IMAGE_TOKENS)

    settings = Settings(
        runs_dir=_runs_dir(env.get("TRANSLATE_RUNS_DIR")),
        retry_attempts=_positive(env, "TRANSLATE_RETRY_ATTEMPTS", 3),
        retry_base_seconds=_positive_float(env, "TRANSLATE_RETRY_BASE_SECONDS", 1.0),
        retry_max_seconds=_positive_float(env, "TRANSLATE_RETRY_MAX_SECONDS", 30.0),
        request_timeout_seconds=_positive_float(
            env, "TRANSLATE_REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
        task_deadline_seconds=_positive_float(
            env, "TRANSLATE_TASK_DEADLINE_SECONDS", 21_600.0
        ),
        docling_url=env.get("DOCLING_SERVER_URL") or env.get("DOCLING_URL"),
        docling_api_key=env.get("DOCLING_API_KEY"),
        docling_ocr_preset=env.get("DOCLING_OCR_PRESET", "tesseract"),
        docling_ocr_lang=env.get("DOCLING_OCR_LANG", "eng"),
        docling_force_ocr=env.get("DOCLING_FORCE_OCR", "false").casefold()
        in {"1", "true", "yes"},
        openai_base_url=env.get("OPENAI_BASE_URL", ""),
        openai_api_key=env.get("OPENAI_API_KEY", ""),
        structure_model=env.get("OPENAI_STRUCTURE_MODEL"),
        translation_model=env.get("OPENAI_TRANSLATION_MODEL"),
        review_model=env.get("OPENAI_REVIEW_MODEL"),
        fix_model=env.get("OPENAI_FIX_MODEL") or env.get("OPENAI_REVISER_MODEL"),
        embedding_model=env.get("OPENAI_EMBEDDING_MODEL"),
        context_tokens=context_tokens,
        output_tokens=output_tokens,
        image_tokens=image_tokens,
        libretranslate_url=env.get("LIBRETRANSLATE_URL"),
        libretranslate_api_key=env.get("LIBRETRANSLATE_API_KEY"),
        langfuse_public_key=env.get("LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=env.get("LANGFUSE_SECRET_KEY"),
        langfuse_otel_host=env.get("LANGFUSE_OTEL_HOST"),
        qdrant_url=env.get("QDRANT_URI"),
        qdrant_api_key=env.get("QDRANT_API_KEY"),
        qdrant_collection=env.get("QDRANT_COLLECTION"),
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        split_pages=_positive(env, "PDF_SPLIT_PAGES", 10),
    )
    _validate(settings, command, backend)
    return settings


def _validate(settings: Settings, command: Command, backend: Backend) -> None:
    required: dict[str, str | None] = {}
    if command == "translate":
        required = {
            "DOCLING_SERVER_URL": settings.docling_url,
            "OPENAI_BASE_URL": settings.openai_base_url,
            "OPENAI_API_KEY": settings.openai_api_key,
            "OPENAI_STRUCTURE_MODEL": settings.structure_model,
            "OPENAI_REVIEW_MODEL": settings.review_model,
        }
        if backend == "llm":
            required["OPENAI_TRANSLATION_MODEL"] = settings.translation_model
        else:
            required["LIBRETRANSLATE_URL"] = settings.libretranslate_url
    elif command == "review":
        required = {
            "DOCLING_SERVER_URL": settings.docling_url,
            "OPENAI_BASE_URL": settings.openai_base_url,
            "OPENAI_API_KEY": settings.openai_api_key,
            "OPENAI_STRUCTURE_MODEL": settings.structure_model,
            "OPENAI_REVIEW_MODEL": settings.review_model,
        }
    elif command == "register":
        required = {
            "OPENAI_BASE_URL": settings.openai_base_url,
            "OPENAI_API_KEY": settings.openai_api_key,
            "OPENAI_EMBEDDING_MODEL": settings.embedding_model,
            "QDRANT_URI": settings.qdrant_url,
            "QDRANT_COLLECTION": settings.qdrant_collection,
        }
    missing = [name for name, value in required.items() if not value]
    if missing:
        msg = f"missing settings: {', '.join(missing)}"
        raise ValueError(msg)


def read_rules(
    settings: Settings, name: Literal["structure", "translation", "review"]
) -> str:
    """同梱ruleをUTF-8で読む。"""

    return (settings.templates_dir / f"{name}-rules.md").read_text(encoding="utf-8")
