"""例外本文の保存だけを制限し、Checkpointの永続化と復元はLangGraphへ委譲する。"""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from typing import TYPE_CHECKING

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class CheckpointSerializer(JsonPlusSerializer):
    """直接の例外値を固定分類へ置換する。state内の本文やnested例外は対象外。"""

    def dumps_typed(self, obj: object) -> tuple[str, bytes]:
        """例外のrepr・属性・型名を保存せず、その他の値は既存形式へ委譲する。"""

        return super().dumps_typed(
            "TaskError" if isinstance(obj, BaseException) else obj
        )


@contextmanager
def open_checkpoint(path: Path) -> Iterator[SqliteSaver]:
    """既存SQLite Saverへ保存方針を注入し、成功・失敗の双方で接続を閉じる。"""

    # Graphの保存workerからも同じ接続を使う。排他とtransactionはSaverが担当する。
    with closing(sqlite3.connect(str(path), check_same_thread=False)) as connection:
        yield SqliteSaver(connection, serde=CheckpointSerializer())
