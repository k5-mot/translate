"""logging level名だけへTTY対応ANSI色を付ける。"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

_COLORS = {
    logging.DEBUG: "\x1b[36m",
    logging.INFO: "\x1b[32m",
    logging.WARNING: "\x1b[33m",
    logging.ERROR: "\x1b[31m",
    logging.CRITICAL: "\x1b[1;31m",
}
_RESET = "\x1b[0m"


def configure_adapter_logging(level: str) -> None:
    """Adapterのログだけを指定levelで標準エラー出力へ送る。

    Args:
        level (str): 標準loggingのlevel名。
    """

    logger = logging.getLogger("translate.adapters")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            ColoredLevelFormatter(
                sys.stderr, "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
        )
        logger.addHandler(handler)
    logger.propagate = False


class ColoredLevelFormatter(logging.Formatter):
    """TTY出力時だけLogRecordのlevelnameへ色を付けるFormatter。"""

    def __init__(self, stream: TextIO, fmt: str | None = None) -> None:
        """出力先のTTY判定に使うstreamと標準Formatter設定を保持する。

        Args:
            stream (TextIO): 色付きLogの出力先Text Stream。
            fmt (str | None): Log MessageのFormat文字列。
        """

        super().__init__(fmt)
        self.stream = stream

    def format(self, record: logging.LogRecord) -> str:
        """元のLogRecordを変更せず、level名だけを一時的に色付けする。

        Args:
            record (logging.LogRecord): Level名を色付けするLog Record。

        Returns:
            str: 元のLogRecordを変更せず、level名だけを一時的に色付けする。
        """

        if not self.stream.isatty() or record.levelno not in _COLORS:
            return super().format(record)
        copied = logging.makeLogRecord(record.__dict__)
        copied.levelname = f"{_COLORS[record.levelno]}{record.levelname}{_RESET}"
        return super().format(copied)
