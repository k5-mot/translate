"""処理ごとのファイルと標準エラーへ標準loggingで出力する。"""

import logging
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(funcName)s: %(message)s"


def configure_logging(level: str) -> None:
    """アプリケーションの標準エラー出力をprocess内で一度だけ設定する。

    Args:
        level: 標準loggingのlevel名。
    """
    logger = logging.getLogger("translate")
    logger.setLevel(level)
    if not any(handler.name == "translate.stderr" for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.name = "translate.stderr"
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    logger.propagate = False


@contextmanager
def processing_logging(
    directory: Path, level: str, filename: str = "translation.log"
) -> Iterator[None]:
    """処理の間だけapp.logへ追記し、終了時にfile handlerを閉じる。

    単一workerで処理ごとに使用し、日次ログは同じdirectoryに7世代保持する。

    Args:
        directory: Pipelineが確定した処理IDの成果物directory。
        level: ファイルと標準エラーへ適用するログlevel。

    Yields:
        None: ログ出力を設定した処理の実行区間。

    Raises:
        OSError: directory作成またはログファイルを開けない場合。
    """
    configure_logging(level)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("translate")
    handler = TimedRotatingFileHandler(
        directory / filename, when="midnight", backupCount=7, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    try:
        logger.info("Processing started")
        yield
    except BaseException as error:
        # 例外本文やsource行には機密情報が入り得るため、種別と発生位置だけを残す。
        frame = traceback.extract_tb(error.__traceback__, limit=-1)[0]
        logger.error(  # noqa: TRY400
            "Processing failed type=%s location=%s:%d:%s",
            type(error).__name__,
            Path(frame.filename).name,
            frame.lineno,
            frame.name,
        )
        raise
    else:
        logger.info("Processing completed")
    finally:
        logger.removeHandler(handler)
        handler.close()
