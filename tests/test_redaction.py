"""Error、log、Run metadataおよびtraceのredactionを検証する。"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from translate.adapters import langfuse
from translate.common.logger import configure_logging
from translate.common.redaction import OMITTED, REDACTED, safe_error
from translate.common.runs import RunRepository

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from translate.common.settings import Settings


class _Observation:
    def update(self, **_kwargs: object) -> None:
        pass


class _Manager:
    def __enter__(self) -> _Observation:
        return _Observation()

    def __exit__(self, *_args: object) -> None:
        pass


def test_log_and_error_redact_credentials_bodies_and_binary(
    tmp_path: Path,
) -> None:
    """既知Credential、base64画像、binaryおよび例外messageを公開しない。"""

    credential_value = "credential-value-123"
    log_file = tmp_path / "run.log"
    configure_logging(log_file, (credential_value,))
    logger = logging.getLogger("redaction-test")
    try:
        message = f"request failed api_key={credential_value}"
        raise OSError(message)  # noqa: TRY301
    except OSError:
        logger.exception(
            "payload=%s image=%s",
            b"PNG-BINARY-SENTINEL",
            "data:image/png;base64,SU1BR0UtQklOQVJZ",
        )

    raw = log_file.read_text(encoding="utf-8")
    assert credential_value not in raw
    assert "PNG-BINARY-SENTINEL" not in raw
    assert "SU1BR0UtQklOQVJZ" not in raw
    assert OMITTED in raw
    assert "Traceback" not in raw

    displayed = safe_error(
        RuntimeError(f"authorization=Bearer {credential_value}"),
        (credential_value,),
    )
    assert credential_value not in displayed
    assert REDACTED in displayed


def test_run_metadata_redacts_sensitive_and_body_fields(tmp_path: Path) -> None:
    """run.jsonへCredential、本文全文または画像binaryを保存しない。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"safe input copy")
    repository = RunRepository(tmp_path / "runs")
    record = repository.create(
        "translate",
        {"source": source},
        {
            "backend": "llm",
            "openai_api_key": "RUN-METADATA-CREDENTIAL",
            "prompt": "FULL-DOCUMENT-BODY-SENTINEL",
            "image": b"IMAGE-BINARY-SENTINEL",
        },
        "fingerprint",
    )

    raw = repository.paths(record.run_id).metadata.read_text(encoding="utf-8")
    metadata = json.loads(raw)
    assert "RUN-METADATA-CREDENTIAL" not in raw
    assert "FULL-DOCUMENT-BODY-SENTINEL" not in raw
    assert "IMAGE-BINARY-SENTINEL" not in raw
    assert metadata["settings_snapshot"]["openai_api_key"] == REDACTED
    assert metadata["settings_snapshot"]["prompt"] == OMITTED
    assert metadata["settings_snapshot"]["image"] == OMITTED


def test_trace_metadata_is_redacted_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """Trace属性にもCredential、本文およびbinaryを渡さない。"""

    captured: dict[str, Any] = {}
    credential_value = "trace-credential-value"

    class Client:
        def start_as_current_observation(self, **kwargs: object) -> _Manager:
            captured.update(kwargs)
            return _Manager()

    monkeypatch.setattr(langfuse, "_get_client", lambda _settings: Client())
    settings = settings_factory(
        langfuse_public_key="public",
        langfuse_secret_key=credential_value,
    )

    with langfuse.observe(
        settings,
        "task.test",
        metadata={
            "token": credential_value,
            "prompt": "FULL-TRACE-BODY-SENTINEL",
            "image": "data:image/png;base64,VEhJUy1JUy1BTi1JTUFHRQ==",
        },
    ):
        pass

    serialized = repr(captured)
    assert credential_value not in serialized
    assert "FULL-TRACE-BODY-SENTINEL" not in serialized
    assert "VEhJUy1JUy1BTi1JTUFHRQ" not in serialized
    assert REDACTED in serialized
    assert OMITTED in serialized
