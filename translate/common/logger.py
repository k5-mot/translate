"""CLIとStreamlitで共有する標準logging設定。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from translate.common.redaction import OMITTED, redact_text

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class RedactionFilter(logging.Filter):
    """取り付け先Handlerのmessageを既知の規則でマスクし、exc_infoを型名へ置き換える。"""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        """後続のLogRecordから除去する、今回の実行で既知の秘密値を保持する。"""

        super().__init__()
        self.secrets = tuple(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        """既知秘密値を置換し、binary引数と例外本文を省く。自由文やstack_infoは残り得る。"""

        # Preserve numeric values for logging placeholders such as `%d`. Converting
        # every argument to text makes standard HTTP client logs raise TypeError.
        if isinstance(record.args, tuple):
            record.args = tuple(
                OMITTED
                if isinstance(item, (bytes, bytearray, memoryview))
                else redact_text(item, self.secrets)
                if isinstance(item, str)
                else item
                for item in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: OMITTED
                if isinstance(item, (bytes, bytearray, memoryview))
                else redact_text(item, self.secrets)
                if isinstance(item, str)
                else item
                for key, item in record.args.items()
            }
        message = redact_text(record.getMessage(), self.secrets)
        if record.exc_info is not None:
            error_type = record.exc_info[0]
            if error_type is not None:
                message = f"{message} ({error_type.__name__})"
        record.msg = message
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def configure_logging(
    log_file: Path | None = None, secrets: Sequence[str] = ()
) -> None:
    """consoleと任意fileへINFO以上のlogを出す。"""

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    redaction = RedactionFilter(secrets)
    for handler in handlers:
        handler.addFilter(redaction)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
    # HTTP client INFO records include endpoint URLs but add no actionable Run state.
    for name in ("httpx", "httpx2", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
