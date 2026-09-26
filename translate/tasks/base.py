"""Task固有処理と状態管理から独立した経過時間の計測。"""

from __future__ import annotations

import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator


class BaseTask:
    """具体Taskが共有する計測だけを提供し、実行状態は保持しない。"""

    name: ClassVar[str]

    @contextmanager
    def measure(self) -> Iterator[None]:
        """経過時間を標準出力へ通知し、stream障害で本体結果を置き換えない。"""

        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            # 表示だけの障害を省略し、本体・時計・必須保存の失敗は抑制しない。
            with suppress(OSError, ValueError):
                print(f"[TIME] {self.name} page=- group=-: {elapsed:.3f} s")  # noqa: T201
