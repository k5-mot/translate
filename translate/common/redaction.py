"""既知の秘密値・field名・表記を使い、Errorやmetadataの露出を抑える補助処理。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from translate.common.settings import Settings

REDACTED = "[REDACTED]"
OMITTED = "[OMITTED]"
MAX_MESSAGE_LENGTH = 512
SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)(?:$|[_-])",
    re.IGNORECASE,
)
BODY_KEY = re.compile(
    r"^(?:base64|binary|body|content|document|payload|prompt|source[_-]?text)$",
    re.IGNORECASE,
)
ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)"
    r"(\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
)
URL_CREDENTIAL = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")
DATA_IMAGE = re.compile(r"(?i)data:image/[^;,\s]+;base64,[A-Za-z0-9+/=]+")


def credential_values(settings: Settings) -> tuple[str, ...]:
    """設定から明示置換すべきCredential値だけを返す。"""

    values = (
        settings.docling_api_key,
        settings.openai_api_key,
        settings.libretranslate_api_key,
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.qdrant_api_key,
    )
    return tuple(value for value in values if value)


def redact_text(value: object, secrets: Sequence[str] = ()) -> str:
    """任意messageから既知Credentialと典型的なCredential表現を除く。"""

    if isinstance(value, (bytes, bytearray, memoryview)):
        return OMITTED
    text = str(value)
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", text
    )
    text = URL_CREDENTIAL.sub(rf"\1{REDACTED}@", text)
    text = DATA_IMAGE.sub(f"{OMITTED} image", text)
    if len(text) > MAX_MESSAGE_LENGTH:
        text = f"{text[:MAX_MESSAGE_LENGTH]}… {OMITTED}"
    return text


def redact_value(  # noqa: PLR0911
    value: Any, secrets: Sequence[str] = (), *, key: str = ""
) -> Any:
    """JSON相当値の既知の機密field・本文fieldとbinaryを置換する。任意の本文は識別しない。"""

    if SENSITIVE_KEY.search(key):
        return REDACTED
    if BODY_KEY.search(key):
        return OMITTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_value(item, secrets, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (bytes, bytearray, memoryview)):
        return OMITTED
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, Sequence):
        return [redact_value(item, secrets) for item in value]
    return value


def safe_error(error: BaseException, secrets: Sequence[str] = ()) -> str:
    """例外型と既知表記をマスクしたmessageを返す。自由文の本文除去は保証しない。"""

    message = redact_text(error, secrets)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def safe_failure_reason(error: BaseException) -> str:
    """例外messageを使わず型・HTTP status、登録失敗では許可したstageと原因型を返す。"""

    stage = getattr(error, "stage", None)
    cause_type = getattr(error, "cause_type", None)
    if (
        type(error).__name__ == "RegistrationError"
        and stage
        in {"collect", "hash", "split", "extract", "write", "verify", "replace"}
        and isinstance(cause_type, str)
        and cause_type.isidentifier()
    ):
        return f"RegistrationError stage={stage} cause={cause_type}"
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    suffix = f" status={status}" if isinstance(status, int) else ""
    return f"{type(error).__name__}{suffix}"
