"""新しいtranslateパッケージの基盤契約を検証する。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx
import httpx2
import pytest
from openai import APIStatusError, BadRequestError, OpenAI
from pydantic import ValidationError
from qdrant_client.http import models as qdrant_models

from translate.adapters import qdrant
from translate.adapters.embedding import embed
from translate.adapters.libretranslate import translate_texts
from translate.adapters.llm import (
    LLMAuthenticationError,
    LLMClient,
    LLMInputExceededError,
    LLMOutputTokenExceededError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    _provider_error,
)
from translate.artifact_store import canonical_hash, load_model, write_model
from translate.common.config import Config, ConfigError, load_config
from translate.common.logger import configure_adapter_logging
from translate.models.artifacts import ArtifactFile, LLMCallIndex, LLMTaskDiagnostics
from translate.models.document import Document, Page, TextSpan, TextUnit
from translate.tasks.translation.translate import TranslationResponse

if TYPE_CHECKING:
    from pathlib import Path


def test_models_ignore_unknown_fields_and_preserve_empty_translation() -> None:
    """未知fieldを捨て、空訳と未設定を区別することを確認する。"""

    span = TextSpan.model_validate(
        {"id": "span-1", "source": "source", "translated": "", "future": 1}
    )

    assert span.translated == ""
    assert span.text() == ""
    assert "future" not in span.model_dump()


def test_artifact_path_rejects_parent_traversal() -> None:
    """永続化する相対pathから親参照を排除する。"""

    with pytest.raises(ValidationError):
        ArtifactFile(relative_path="../secret", sha256="0" * 64, size_bytes=1)


def test_model_storage_round_trip(tmp_path: Path) -> None:
    """Pydantic成果物を原子的に保存して再検証できることを確認する。"""

    path = tmp_path / "task-structure.json"
    value = LLMTaskDiagnostics(
        task="STRUCTURE",
        diagnostics=[],
        updated_at=datetime.now(UTC),
    )

    write_model(path, value)
    loaded = load_model(path, LLMTaskDiagnostics)

    assert loaded == value
    assert path.read_bytes().endswith(b"\n")


def test_canonical_hash_is_independent_of_json_key_order() -> None:
    """構造化値のfingerprintがkey順へ依存しないことを確認する。"""

    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_config_environment_overrides_dotenv(tmp_path: Path) -> None:
    """process環境変数が.envより優先されることを確認する。"""

    (tmp_path / ".env").write_text("PDF_SPLIT_PAGES=5\n", encoding="utf-8")

    config = load_config(tmp_path, {"PDF_SPLIT_PAGES": "7"})

    assert config.pdf_split_pages == 7


def test_adapter_log_level_comes_from_dotenv(tmp_path: Path) -> None:
    """Adapterのログlevelを.envで変更できることを確認する。"""

    (tmp_path / ".env").write_text("LOG_LEVEL=DEBUG\n", encoding="utf-8")
    assert load_config(tmp_path, {}).log_level == "DEBUG"


def test_adapter_logging_writes_debug_to_stderr_without_changing_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Adapter専用LoggerだけにDEBUGを設定し、標準エラーへ出力する。"""

    adapter_logger = logging.getLogger("translate.adapters")
    old_handlers = adapter_logger.handlers[:]
    old_level = adapter_logger.level
    old_propagate = adapter_logger.propagate
    root_level = logging.getLogger().level
    try:
        adapter_logger.handlers.clear()
        configure_adapter_logging("DEBUG")
        logging.getLogger("translate.adapters.docling").debug("adapter-diagnostic")
        assert "adapter-diagnostic" in capsys.readouterr().err
        assert logging.getLogger().level == root_level
    finally:
        adapter_logger.handlers = old_handlers
        adapter_logger.setLevel(old_level)
        adapter_logger.propagate = old_propagate


def test_libretranslate_logs_counts_without_request_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """翻訳Adapterのログが件数を示し、本文と認証情報を含まない。"""

    def respond(*_args: object, **_kwargs: object) -> httpx.Response:
        """実HTTP接続を使わず成功応答を返す。"""

        return httpx.Response(
            200,
            json={"translatedText": ["secret-output"]},
            request=httpx.Request("POST", "http://localhost/translate"),
        )

    monkeypatch.setattr(httpx, "post", respond)
    monkeypatch.setattr(logging.getLogger("translate.adapters"), "propagate", True)
    with caplog.at_level(logging.DEBUG, logger="translate.adapters.libretranslate"):
        assert translate_texts(
            ["secret-input"],
            Config(
                libretranslate_url="http://localhost",
                libretranslate_api_key="secret-key",
            ),
        ) == ["secret-output"]

    output = caplog.text
    assert "LibreTranslate開始 items=1" in output
    assert "LibreTranslate完了 items=1" in output
    assert "secret-" not in output


def test_settings_use_process_environment_without_changing_direct_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """実環境変数を優先し、空値は無視して直接生成の既定値を維持する。"""

    (tmp_path / ".env").write_text("PDF_SPLIT_PAGES=5\n", encoding="utf-8")
    monkeypatch.setenv("PDF_SPLIT_PAGES", "7")
    assert load_config(tmp_path).pdf_split_pages == 7
    assert Config().pdf_split_pages == 10
    monkeypatch.setenv("PDF_SPLIT_PAGES", "")
    assert load_config(tmp_path).pdf_split_pages == 5


def test_config_rejects_context_budget_overflow() -> None:
    """Task別token予算の超過を設定名と合計付きで拒否する。"""

    with pytest.raises(
        ValidationError,
        match=r"STRUCTURE token budget: .* = 11264 > LLM_CONTEXT_TOKENS=10000",
    ):
        Config(
            llm_context_tokens=10000,
            structure_input_tokens=6144,
            structure_output_tokens=2048,
            llm_image_tokens=2048,
            llm_safety_tokens=1024,
        )


def test_config_allows_output_above_previous_individual_limit() -> None:
    """各token設定が旧個別上限を超えてもcontext予算内なら許可する。"""

    assert Config(review_output_tokens=8192).review_output_tokens == 8192
    config = Config(
        llm_context_tokens=65536,
        llm_image_tokens=4096,
        llm_safety_tokens=5000,
        structure_input_tokens=10000,
        structure_output_tokens=8192,
        translate_input_tokens=10000,
        translate_output_tokens=8192,
        review_input_tokens=10000,
        review_output_tokens=16384,
    )
    assert config.review_output_tokens == 16384


def test_config_rejects_review_budget_over_context() -> None:
    """REVIEWの予算超過を個別上限ではなく合計で拒否する。"""

    with pytest.raises(
        ValidationError,
        match=r"REVIEW token budget: .* = 33216 > LLM_CONTEXT_TOKENS=30208",
    ):
        Config(review_output_tokens=24000)


def test_partial_qdrant_settings_are_rejected() -> None:
    """任意RAGの部分設定を黙って無効化しないことを確認する。"""

    config = Config(qdrant_uri="http://qdrant")

    with pytest.raises(ConfigError):
        config.qdrant_enabled()


def test_qdrant_registration_uses_bounded_upload_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """大量PointをQdrant clientの有限batch uploadへ委譲する。"""

    points = [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "vector": [0.0, 1.0],
            "payload": {"chunk_index": index},
        }
        for index in range(65)
    ]
    client = MagicMock()
    client.collection_exists.return_value = False
    client.retrieve.side_effect = [
        [],
        [MagicMock(id=point["id"]) for point in points],
    ]
    monkeypatch.setattr(
        qdrant,
        "_client",
        MagicMock(return_value=(client, qdrant_models)),
    )

    written = qdrant.upsert_revision(
        config=Config(
            qdrant_uri="http://qdrant",
            qdrant_collection="translation",
        ),
        source_key="source/sample.pdf",
        revision="revision",
        points=points,
        vector_size=2,
    )

    assert written is True
    client.upload_points.assert_called_once()
    assert client.upload_points.call_args.kwargs["batch_size"] == 64
    assert client.upload_points.call_args.kwargs["wait"] is True
    assert len(client.upload_points.call_args.kwargs["points"]) == 65
    client.upsert.assert_not_called()


def test_document_json_uses_schema_version_one() -> None:
    """Documentの永続化Schema versionとJSON互換性を確認する。"""

    document = Document(
        pages=[Page(number=1)],
        metadata={"unit": json.loads('{"kind":"sample"}')},
    )

    assert document.schema_version == 1
    assert TextUnit(id="unit", spans=[]).text() == ""


def test_llm_payload_uses_non_thinking_sampling() -> None:
    """LLM要求に現在の非推論sampling設定を指定する。"""

    client = LLMClient(Config(openai_base_url="http://llm"))

    payload = client._payload(  # noqa: SLF001
        model="model",
        system="system",
        user="user",
        contract="contract",
        native_schema={"type": "object"},
        output_tokens=128,
        image=None,
    )

    assert "reasoning_effort" not in payload
    assert "thinking_budget_tokens" not in payload
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.8
    assert payload["extra_body"] == {
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "repetition_penalty": 1.01,
        "enable_thinking": False,
        "preserve_thinking": False,
        "chat_template_kwargs": {
            "enable_thinking": False,
            "preserve_thinking": False,
        },
    }


def test_llm_rejects_oversized_complete_prompt_before_http() -> None:
    """本文以外のsystemと契約を含む実入力を送信前に制限する。"""

    client = LLMClient(Config(openai_base_url="http://llm"))

    with pytest.raises(LLMInputExceededError, match="task limit"):
        client.structured(
            task="TRANSLATE",
            model="model",
            response_type=LLMTaskDiagnostics,
            system="s" * 100,
            user="user",
            contract="contract",
            native_schema=LLMTaskDiagnostics.model_json_schema(),
            input_tokens=64,
            output_tokens=128,
        )


@pytest.mark.parametrize(
    "message", ["maximum context length exceeded", "Context size has been exceeded."]
)
def test_llm_classifies_provider_context_error_for_task_splitting(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    """endpointのcontext超過HTTP 400を通常のLLM失敗と区別する。"""

    response = httpx2.Response(
        400,
        json={"error": {"message": message}},
        request=httpx2.Request("POST", "http://llm/chat/completions"),
    )
    client = LLMClient(Config(openai_base_url="http://llm"))
    monkeypatch.setattr(
        client.client.chat.completions,
        "create",
        MagicMock(side_effect=BadRequestError(message, response=response, body=None)),
    )

    with pytest.raises(LLMInputExceededError, match="providerのcontext"):
        client.structured(
            task="TRANSLATE",
            model="model",
            response_type=LLMTaskDiagnostics,
            system="system",
            user="user",
            contract="contract",
            native_schema=LLMTaskDiagnostics.model_json_schema(),
            input_tokens=8192,
            output_tokens=128,
        )


@pytest.mark.parametrize(
    ("api_key", "expected_auth"),
    [(None, None), ("test-key", "Bearer test-key")],
)
def test_llm_sdk_sends_compatible_payload_and_auth(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
    expected_auth: str | None,
) -> None:
    """SDK経由の互換要求で認証headerを設定どおり送る。"""

    seen: dict[str, object] = {}

    def handle(request: httpx2.Request) -> httpx2.Response:
        """送信headerと本文を記録し、正常なChatCompletionを返す。"""

        seen["authorization"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"translations":[]}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 9,
                    "completion_tokens": 4,
                    "total_tokens": 13,
                },
            },
            request=request,
        )

    def make_client(**kwargs: object) -> OpenAI:
        """LLMClientのSDK設定をそのまま使い、HTTPだけ置き換える。"""

        seen["max_retries"] = kwargs["max_retries"]
        return OpenAI(
            **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handle))
        )

    monkeypatch.setattr("translate.adapters.llm.OpenAI", make_client)
    client = LLMClient(Config(openai_base_url="http://llm", openai_api_key=api_key))
    result = client.structured(
        task="TRANSLATE",
        model="model",
        response_type=TranslationResponse,
        system="system",
        user="user",
        contract="contract",
        native_schema=TranslationResponse.model_json_schema(),
        output_tokens=128,
    )

    assert result.output_tokens == 4
    assert seen["max_retries"] == 0
    assert seen["authorization"] == expected_auth
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["repetition_penalty"] == 1.01
    assert payload["max_tokens"] == 128


def test_llm_reports_output_token_limit_with_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本文が空でもlength終了を出力予算エラーとして説明する。"""

    client = LLMClient(Config(openai_base_url="http://llm"))
    completion = MagicMock()
    completion.choices = [MagicMock(finish_reason="length")]
    completion.choices[0].message.content = None
    completion.usage = None
    monkeypatch.setattr(
        client.client.chat.completions, "create", MagicMock(return_value=completion)
    )

    with pytest.raises(
        LLMOutputTokenExceededError, match=r"TRANSLATE_OUTPUT_TOKENS=128.*対策:"
    ):
        client.structured(
            task="TRANSLATE",
            model="model",
            response_type=LLMTaskDiagnostics,
            system="system",
            user="user",
            contract="contract",
            native_schema=LLMTaskDiagnostics.model_json_schema(),
            output_tokens=128,
        )


@pytest.mark.parametrize(
    ("status", "expected_type"),
    [
        (400, LLMProviderError),
        (401, LLMAuthenticationError),
        (408, LLMTimeoutError),
        (429, LLMRateLimitError),
        (503, LLMProviderError),
    ],
)
def test_llm_http_error_has_safe_remedy(
    status: int, expected_type: type[Exception]
) -> None:
    """HTTP失敗を分類し、provider本文を出さずに対策を示す。"""

    response = httpx2.Response(
        status,
        json={"error": {"message": "secret prompt text"}},
        request=httpx2.Request("POST", "http://llm/chat/completions"),
    )
    error = APIStatusError("secret prompt text", response=response, body=None)

    classified = _provider_error(error)

    assert isinstance(classified, expected_type)
    assert "対策:" in str(classified)
    assert "secret prompt text" not in str(classified)


@pytest.mark.parametrize(
    ("api_key", "expected_auth"),
    [(None, None), ("test-key", "Bearer test-key")],
)
def test_embedding_sdk_preserves_order_and_auth(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
    expected_auth: str | None,
) -> None:
    """SDKのEmbedding要求で認証を保ち、返却順をindex順へ戻す。"""

    seen: dict[str, object] = {}

    def handle(request: httpx2.Request) -> httpx2.Response:
        """Embedding要求を記録して逆順の2件を返す。"""

        seen["authorization"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "embedding-model",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [2.0]},
                    {"object": "embedding", "index": 0, "embedding": [1.0]},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
            request=request,
        )

    def make_client(**kwargs: object) -> OpenAI:
        """Embedding用SDKのHTTPだけtest transportへ置き換える。"""

        seen["max_retries"] = kwargs["max_retries"]
        return OpenAI(
            **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handle))
        )

    monkeypatch.setattr("translate.adapters.embedding.OpenAI", make_client)
    vectors = embed(
        ["one", "two"],
        Config(
            openai_base_url="http://llm",
            openai_api_key=api_key,
            openai_embedding_model="embedding-model",
        ),
    )

    assert vectors == [[1.0], [2.0]]
    assert seen["max_retries"] == 0
    assert seen["authorization"] == expected_auth
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["encoding_format"] == "float"


def test_llm_call_index_rejects_duplicate_ids() -> None:
    """集約進捗の正本となる採用Call一覧に重複を許可しない。"""

    with pytest.raises(ValidationError):
        LLMCallIndex(task="REVIEW", call_ids=["call-1", "call-1"])
