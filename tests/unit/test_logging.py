"""処理IDごとのログ分離とhandlerの寿命を検証する。"""

import logging
from collections.abc import Iterator
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import pytest

from translate.common.logger import configure_logging, processing_logging


@pytest.fixture
def application_logger() -> Iterator[logging.Logger]:
    """実行前の設定を保存し、追加したhandlerを閉じる。

    Yields:
        logging.Logger: 設定を隔離したアプリケーションLogger。
    """
    logger = logging.getLogger("translate")
    original = logger.handlers[:], logger.level, logger.propagate
    logger.handlers = []
    try:
        yield logger
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers, logger.level, logger.propagate = original


def test_logging_appends_and_separates_processing_ids(
    tmp_path: Path,
    application_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Resumeでは追記し、別処理へログを混在させず日次7世代を設定する。"""
    configure_logging("INFO")
    configure_logging("DEBUG")
    handlers = application_logger.handlers[:]
    assert sum(handler.name == "translate.stderr" for handler in handlers) == 1
    first, second = tmp_path / "first", tmp_path / "second"
    for directory, message in (
        (first, "first-run"),
        (first, "resumed"),
        (second, "second-run"),
    ):
        with processing_logging(directory, "INFO"):
            logging.getLogger("translate.adapters.pdf").info(message)
            file_handler = application_logger.handlers[-1]
            assert isinstance(file_handler, TimedRotatingFileHandler)
            assert file_handler.when == "MIDNIGHT"
            assert file_handler.backupCount == 7
        assert file_handler.stream is None
        assert application_logger.handlers == handlers
    first_text = (first / "app.log").read_text(encoding="utf-8")
    second_text = (second / "app.log").read_text(encoding="utf-8")
    assert first_text.count("first-run") == first_text.count("resumed") == 1
    assert "second-run" not in first_text
    assert "first-run" not in second_text
    assert "resumed" not in second_text
    assert second_text.count("second-run") == 1
    assert capsys.readouterr().err.count("second-run") == 1


def test_logging_closes_on_failure_without_exception_payload(
    tmp_path: Path,
    application_logger: logging.Logger,
) -> None:
    """失敗時もhandlerを解放し、例外に含まれる本文や認証情報を記録しない。"""
    message = "secret-payload"
    configure_logging("DEBUG")
    handlers = application_logger.handlers[:]
    with (  # noqa: PT012 - handlerの解放を例外経路で検証する。
        pytest.raises(ValueError, match=message),
        processing_logging(tmp_path, "DEBUG"),
    ):
        file_handler = application_logger.handlers[-1]
        raise ValueError(message)
    assert isinstance(file_handler, TimedRotatingFileHandler)
    assert file_handler.stream is None
    assert application_logger.handlers == handlers
    output = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "ValueError" in output
    assert "secret-payload" not in output
