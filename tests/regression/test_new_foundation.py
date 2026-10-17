"""新しいtranslateパッケージの基盤契約を検証する。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from importlib import import_module
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx2
import pytest
from openai import APIStatusError, BadRequestError, OpenAI
from pydantic import ValidationError

from translate.adapters import qdrant
from translate.adapters.artifact_store import canonical_hash, load_model, write_model
from translate.adapters.embedding import EmbeddingClient
from translate.adapters.llm import (
    LLMAuthenticationError,
    LLMClient,
    LLMInputExceededError,
    LLMInvalidResponseError,
    LLMOutputTokenExceededError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    _provider_error,
)
from translate.common.config import Config, ConfigError, load_config, validate_config
from translate.common.logger import configure_logging
from translate.models.artifacts import ArtifactFile, LLMCallIndex, LLMTaskDiagnostics
from translate.models.document import Document, Page, TextSpan, TextUnit

TranslationResponse = import_module("translate.tasks.30_translate").TranslationResponse

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


def test_config_environment_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """process環境変数が.envより優先されることを確認する。"""

    (tmp_path / ".env").write_text("PDF_SPLIT_PAGES=5\n", encoding="utf-8")

    monkeypatch.setenv("PDF_SPLIT_PAGES", "7")
    config = load_config(tmp_path)

    assert config.pdf_split_pages == 7


def test_http_timeout_allows_3000_seconds_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """長時間のHTTP応答待ちを.envで設定でき、上限超過は拒否する。"""

    monkeypatch.delenv("HTTP_REQUEST_TIMEOUT_SECONDS", raising=False)
    (tmp_path / ".env").write_text(
        "HTTP_REQUEST_TIMEOUT_SECONDS=3000\n", encoding="utf-8"
    )
    assert load_config(tmp_path).http_request_timeout_seconds == 3000
    with pytest.raises(ValidationError):
        Config(http_request_timeout_seconds=3001)


def test_adapter_log_level_comes_from_dotenv(tmp_path: Path) -> None:
    """Adapterのログlevelを.envで変更できることを確認する。"""

    (tmp_path / ".env").write_text("LOG_LEVEL=DEBUG\n", encoding="utf-8")
    assert load_config(tmp_path).log_level == "DEBUG"


def test_adapter_logging_writes_debug_to_stderr_without_changing_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """アプリケーションのDEBUGを標準エラーへ出し、root設定を変えない。"""

    adapter_logger = logging.getLogger("translate")
    old_handlers = adapter_logger.handlers[:]
    old_level = adapter_logger.level
    old_propagate = adapter_logger.propagate
    root_level = logging.getLogger().level
    try:
        adapter_logger.handlers.clear()
        configure_logging("DEBUG")
        logging.getLogger("translate.adapters.docling").debug("adapter-diagnostic")
        assert "adapter-diagnostic" in capsys.readouterr().err
        assert logging.getLogger().level == root_level
    finally:
        adapter_logger.handlers = old_handlers
        adapter_logger.setLevel(old_level)
        adapter_logger.propagate = old_propagate


def test_settings_use_process_environment_in_direct_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """直接生成でも環境変数を読み、空値だけは.envの値へfallbackする。"""

    (tmp_path / ".env").write_text("PDF_SPLIT_PAGES=5\n", encoding="utf-8")
    monkeypatch.setenv("PDF_SPLIT_PAGES", "7")
    assert load_config(tmp_path).pdf_split_pages == 7
    assert Config().pdf_split_pages == 7
    monkeypatch.setenv("PDF_SPLIT_PAGES", "")
    assert load_config(tmp_path).pdf_split_pages == 5


def test_config_rejects_context_budget_overflow() -> None:
    """Task別token予算の超過を設定名と合計付きで拒否する。"""

    with pytest.raises(
        ConfigError,
        match=r"STRUCTURE token budget 11264 exceeds LLM_CONTEXT_TOKENS=10000",
    ):
        validate_config(
            Config(
                llm_context_tokens=10000,
                structure_input_tokens=6144,
                structure_output_tokens=2048,
                llm_image_tokens=2048,
                llm_safety_tokens=1024,
            )
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
        ConfigError,
        match=r"REVIEW token budget 33216 exceeds LLM_CONTEXT_TOKENS=30208",
    ):
        validate_config(Config(review_output_tokens=24000))


def test_partial_qdrant_settings_are_rejected() -> None:
    """任意RAGの部分設定を黙って無効化しないことを確認する。"""

    config = Config(qdrant_uri="http://qdrant")

    with pytest.raises(ConfigError):
        validate_config(config)


def test_generation_endpoint_does_not_replace_embedding_endpoint() -> None:
    """生成専用URLだけでTranslateとReviewを許可し、Registerには既定URLを要求する。"""

    config = Config(
        openai_llm_base_url="http://generation",
        openai_structure_model="model",
        openai_translation_model="model",
        openai_review_model="model",
        docling_server_url="http://docling",
    )

    validate_config(config, "translate")
    validate_config(config, "review")
    validate_config(config, "upgrade")
    with pytest.raises(ConfigError, match="Required settings: OPENAI_BASE_URL"):
        validate_config(config, "register")
    with pytest.raises(ConfigError, match="Required settings: OPENAI_BASE_URL"):
        validate_config(
            config.model_copy(
                update={
                    "openai_embedding_model": "embedding",
                    "qdrant_uri": "http://qdrant",
                    "qdrant_collection": "reference",
                }
            )
        )


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
    monkeypatch.setattr("qdrant_client.QdrantClient", MagicMock(return_value=client))

    with qdrant.QdrantStore(
        Config(
            qdrant_uri="http://qdrant",
            qdrant_collection="translation",
        ),
    ) as store:
        written = store.upsert_revision(
            source_key="source/sample.pdf",
            revision="revision",
            points=points,
            vector_size=2,
        )

    assert written is True
    client.upload_points.assert_called_once()
    assert client.upload_points.call_args.kwargs["batch_size"] == 64
    assert client.upload_points.call_args.kwargs["parallel"] == 1
    assert client.upload_points.call_args.kwargs["wait"] is True
    assert len(client.upload_points.call_args.kwargs["points"]) == 65
    client.upsert.assert_not_called()
    client.close.assert_called_once()


def test_qdrant_client_does_not_start_background_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同期操作と重複するSDKの背景version確認を起動しない。"""

    background_thread = MagicMock()
    monkeypatch.setattr("qdrant_client.qdrant_remote.Thread", background_thread)
    query = MagicMock()
    query.return_value.points = []
    monkeypatch.setattr("qdrant_client.qdrant_remote.QdrantRemote.query_points", query)
    with qdrant.QdrantStore(
        Config(qdrant_uri="http://qdrant", qdrant_collection="translation")
    ) as store:
        assert store.search([0.0, 1.0]) == []
    background_thread.assert_not_called()
    query.assert_called_once()


def test_qdrant_store_closes_connection_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """検索失敗時にも所有する接続を閉じ、例外は呼出元へ返す。"""

    client = MagicMock()
    client.query_points.side_effect = RuntimeError
    monkeypatch.setattr("qdrant_client.QdrantClient", MagicMock(return_value=client))
    with (
        pytest.raises(RuntimeError),
        qdrant.QdrantStore(
            Config(qdrant_uri="http://qdrant", qdrant_collection="translation")
        ) as store,
    ):
        store.search([0.0, 1.0])
    client.close.assert_called_once()


def test_document_json_uses_schema_version_one() -> None:
    """Documentの永続化Schema versionとJSON互換性を確認する。"""

    document = Document(
        pages=[Page(number=1)],
        metadata={"unit": json.loads('{"kind":"sample"}')},
    )

    assert document.schema_version == 1
    assert TextUnit(id="unit", spans=[]).text() == ""


@pytest.mark.parametrize("mode", ["json_object", "json_schema", "prompt"])
def test_llm_payload_uses_non_thinking_sampling(mode: str) -> None:
    """LLM要求に現在の非推論sampling設定を指定する。"""

    client = LLMClient(
        Config(openai_base_url="http://llm", llm_structured_output_mode=mode)
    )

    payload = client._payload(  # noqa: SLF001
        model="model",
        system="system",
        user="user",
        contract="contract",
        native_schema={"type": "object"},
        output_tokens=128,
        image=None,
    )

    assert payload["messages"][0]["content"] == "system\n\ncontract"
    assert payload["reasoning_effort"] == "none"
    assert "thinking_budget_tokens" not in payload
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.8
    assert payload["extra_body"] == {
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.0,
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
    ("api_key", "llm_endpoint", "expected_auth", "expected_host"),
    [
        (None, (None, None), None, "llm"),
        ("test-key", (None, None), "Bearer test-key", "llm"),
        ("proxy-key", ("http://direct", None), None, "direct"),
        ("proxy-key", ("http://direct", "direct-key"), "Bearer direct-key", "direct"),
    ],
)
def test_llm_sdk_sends_compatible_payload_and_auth(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
    llm_endpoint: tuple[str | None, str | None],
    expected_auth: str | None,
    expected_host: str,
) -> None:
    """SDK経由の互換要求で認証headerを設定どおり送る。"""

    seen: dict[str, object] = {}

    def handle(request: httpx2.Request) -> httpx2.Response:
        """送信headerと本文を記録し、正常なChatCompletionを返す。"""

        seen["authorization"] = request.headers.get("Authorization")
        seen["host"] = request.url.host
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
    client = LLMClient(
        Config(
            openai_base_url="http://llm",
            openai_api_key=api_key,
            openai_llm_base_url=llm_endpoint[0],
            openai_llm_api_key=llm_endpoint[1],
        )
    )
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
    assert seen["host"] == expected_host
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["repetition_penalty"] == 1.01
    assert payload["max_tokens"] == 128
    assert payload["reasoning_effort"] == "none"


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


@pytest.mark.parametrize("invalid_count", [1, 2, 3])
def test_llm_retries_invalid_json_until_configured_attempt_limit(
    monkeypatch: pytest.MonkeyPatch,
    invalid_count: int,
) -> None:
    """JSON不正も設定された総試行回数まで再試行する。"""

    client = LLMClient(
        Config(
            openai_base_url="http://llm",
            llm_structured_output_mode="prompt",
            llm_retry_attempts=3,
        )
    )
    completion = MagicMock()
    completion.choices = [MagicMock(finish_reason="stop")]
    completion.usage = None
    completion.choices[0].message.content = (
        '{"translations":[{"span_id":"#/texts/967/content/span-0001",'
        '"text":"意図的に空白"}]}'
    )
    invalid = MagicMock()
    invalid.choices = [MagicMock(finish_reason="stop")]
    invalid.usage = None
    invalid.choices[0].message.content = "not JSON"
    create = MagicMock(side_effect=[*[invalid] * invalid_count, completion])
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    monkeypatch.setattr("translate.adapters.llm.time.sleep", MagicMock())

    if invalid_count == 3:
        with pytest.raises(LLMInvalidResponseError) as failure:
            client.structured(
                task="TRANSLATE",
                model="model",
                response_type=TranslationResponse,
                system="system",
                user="user",
                contract="contract",
                native_schema=TranslationResponse.model_json_schema(),
                output_tokens=128,
            )
        assert failure.value.attempts == create.call_count == 3
    else:
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
        assert result.attempts == create.call_count == invalid_count + 1
        assert result.response.translations[0].text == "意図的に空白"


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
    vectors = EmbeddingClient(
        Config(
            openai_base_url="http://llm",
            openai_api_key=api_key,
            openai_embedding_model="embedding-model",
        ),
    ).embed(["one", "two"])

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


def test_native_schema_budget_includes_operation_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """native Schemaでも操作説明を入力予算へ含め、超過時はHTTP送信しない。"""
    client = LLMClient(
        Config(openai_base_url="http://llm", llm_structured_output_mode="json_schema")
    )
    create = MagicMock(side_effect=AssertionError("oversized request must not be sent"))
    monkeypatch.setattr(client.client.chat.completions, "create", create)
    try:
        with pytest.raises(LLMInputExceededError, match="task limit"):
            client.structured(
                task="REVIEW",
                model="model",
                response_type=TranslationResponse,
                system="system",
                user="user",
                contract="contract " * 400,
                native_schema=TranslationResponse.model_json_schema(),
                input_tokens=1024,
                output_tokens=128,
            )
        create.assert_not_called()
    finally:
        client.client.close()
