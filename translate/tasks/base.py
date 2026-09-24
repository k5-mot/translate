"""Task固有処理と状態管理から独立した経過時間の計測。"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator


class BaseTask:
    """具体Taskが共有する計測だけを提供し、実行状態は保持しない。"""

    name: ClassVar[str]

    @contextmanager
    def measure(self) -> Iterator[None]:
        """成功・失敗にかかわらず一度計測し、処理中の例外はそのまま伝播する。"""

        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            # 時間の通知は成功通知ではなく、成果物やCheckpointを更新しない。
            print(f"[TIME] {self.name} page=- group=-: {elapsed:.3f} s")  # noqa: T201
