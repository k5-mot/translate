"""環境変数を検証済み設定へ変換する。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping


class ConfigError(ValueError):
    """環境変数が仕様上の範囲または組合せを満たさないことを表す。"""


class Config(BaseModel):
    """PipelineとAdapterが共有する検証済み設定。"""

    model_config = ConfigDict(extra="ignore")

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

    libretranslate_url: str | None = None
    libretranslate_api_key: str | None = None

    qdrant_uri: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str | None = None

    http_retry_attempts: int = Field(default=3, gt=0, le=3)
    http_request_timeout_seconds: float = Field(default=300, gt=0, le=1800)
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
    llm_retry_attempts: int = Field(default=3, gt=0, le=3)
    llm_split_max_depth: int = Field(default=6, gt=0, le=6)
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

    @model_validator(mode="after")
    def validate_token_budgets(self) -> Self:
        """Task別の入出力と予約tokenがcontext上限内であることを検査する。

        Returns:
            Self: Task別の入出力と予約tokenがcontext上限内であることを検査する。

        Raises:
            ValueError: Task別のtoken予算が`LLM_CONTEXT_TOKENS`を超えた場合。
        """

        budgets = (
            (
                "STRUCTURE",
                self.structure_input_tokens,
                self.structure_output_tokens,
                self.llm_image_tokens,
            ),
            ("TRANSLATE", self.translate_input_tokens, self.translate_output_tokens, 0),
            ("REVIEW", self.review_input_tokens, self.review_output_tokens, 0),
        )
        for task, input_tokens, output_tokens, image_tokens in budgets:
            total = input_tokens + output_tokens + image_tokens + self.llm_safety_tokens
            if total > self.llm_context_tokens:
                components = (
                    f"{task}_INPUT_TOKENS={input_tokens} + "
                    f"{task}_OUTPUT_TOKENS={output_tokens}"
                )
                if image_tokens:
                    components += f" + LLM_IMAGE_TOKENS={image_tokens}"
                components += f" + LLM_SAFETY_TOKENS={self.llm_safety_tokens}"
                raise ValueError(
                    f"{task} token budget: {components} = {total} > "
                    f"LLM_CONTEXT_TOKENS={self.llm_context_tokens}"
                )
        return self

    def require_translate(self, backend: Literal["llm", "libretranslate"]) -> None:
        """Translateに必要なendpoint設定が揃っていることを検査する。

        Args:
            backend (Literal['llm', 'libretranslate']): 翻訳に使用するBackend名。
        """

        self._require_docling()
        if backend == "llm":
            self._require(
                "LLM translate",
                self.openai_llm_base_url or self.openai_base_url,
                self.openai_structure_model,
                self.openai_translation_model,
                self.openai_review_model,
            )
        else:
            self._require("LibreTranslate", self.libretranslate_url)
            self._require(
                "LLM structure/review",
                self.openai_llm_base_url or self.openai_base_url,
                self.openai_structure_model,
                self.openai_review_model,
            )

    def require_review(self) -> None:
        """比較Reviewに必要なDoclingとLLM設定を検査する。"""

        self._require_docling()
        self._require(
            "LLM review",
            self.openai_llm_base_url or self.openai_base_url,
            self.openai_review_model,
        )

    def require_register(self) -> None:
        """Registerに必要なEmbeddingとQdrant設定を検査する。"""

        self._require(
            "Register",
            self.openai_base_url,
            self.openai_embedding_model,
            self.qdrant_uri,
            self.qdrant_collection,
        )

    def qdrant_enabled(self) -> bool:
        """任意のRAG設定が完全に有効かを返し、部分設定は拒否する。

        Returns:
            bool: 任意のRAG設定が完全に有効かを返し、部分設定は拒否する。

        Raises:
            ConfigError: `Qdrant RAG settings must be complete`と判定した場合。
        """

        values = (
            self.openai_embedding_model,
            self.qdrant_uri,
            self.qdrant_collection,
        )
        if any(values) and not all(values):
            raise ConfigError("Qdrant RAG settings must be complete")
        if all(values) and not self.openai_base_url:
            raise ConfigError("RAG requires OPENAI_BASE_URL for embeddings")
        return all(values)

    def _require_docling(self) -> None:
        """PDF処理に必要なDocling endpointを検査する。"""

        self._require("Docling", self.docling_server_url)

    @staticmethod
    def _require(label: str, *values: str | None) -> None:
        """一つでも空の必須設定があれば用途名付きで拒否する。

        Args:
            label (str): 不足設定をErrorへ示す表示名。
            *values (str | None): 一括処理する入力Text列。

        Raises:
            ConfigError: `f'{label} settings are incomplete'`と判定した場合。
        """

        if not all(value and value.strip() for value in values):
            raise ConfigError(f"{label} settings are incomplete")


class _EnvironmentConfig(BaseSettings, Config):
    """Configのfieldを.envとprocess環境変数から取得する。"""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)


def load_config(
    directory: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """現在directoryの.envへprocess環境変数を上書きし、設定を検証する。

    Args:
        directory (Path | None): LLM Call Artifactの保存Directory。
        environ (Mapping[str, str] | None): Process環境変数の代替Mapping。

    Returns:
        Config: 現在directoryの.envへprocess環境変数を上書きし、設定を検証する。

    Raises:
        ConfigError: 現在directoryの.envへprocess環境変数を上書きし、設定を検証する処理を完了できない場合。
    """

    base = directory or Path.cwd()
    try:
        if environ is None:
            return Config.model_validate(
                _EnvironmentConfig(_env_file=base / ".env").model_dump()
            )
        dotenv = dotenv_values(base / ".env")
        return Config.model_validate(
            {
                name: value
                for name in Config.model_fields
                if (value := environ.get(name.upper(), dotenv.get(name.upper())))
                not in {None, ""}
            }
        )
    except ValidationError as error:
        raise ConfigError(str(error)) from error
