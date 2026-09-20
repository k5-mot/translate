"""CLIとStreamlitで共有する標準logging設定。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from translate.common.redaction import redact_text

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class RedactionFilter(logging.Filter):
    """全Handlerへ渡る前にCredential、binaryおよび例外messageを除去する。"""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self.secrets = tuple(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        """LogRecordを安全な完成messageへ置換する。"""

        if isinstance(record.args, tuple):
            record.args = tuple(redact_text(item, self.secrets) for item in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_text(item, self.secrets)
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
