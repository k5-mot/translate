"""共通fixtureと外部service test doubleを提供する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from translate_v1.common.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class FakeHttpResponse:
    """Adapter testで使う最小のHTTP response double。"""

    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: object | None = None,
        content: bytes = b"",
    ) -> None:
        """通信を行わないHTTP応答doubleへstatus・JSON値・binary本文を設定する。"""

        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self) -> object | None:
        """設定済みJSON payloadを返す。"""

        return self._payload

    def raise_for_status(self) -> None:
        """400以上ならstatusを含むRuntimeErrorを投げる。httpxの例外型は再現しない。"""

        if self.status_code >= 400:
            msg = f"HTTP {self.status_code}"
            raise RuntimeError(msg)


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    """Templateの保存先をTestごとに分け、任意の設定を上書きできるfactoryを返す。"""

    def create(**updates: object) -> Settings:
        """
        Test専用Template保存先を既定値に、ケース固有の設定を上書きしたSettingsを作る。
        """

        values: dict[str, object] = {"templates_dir": tmp_path / "templates"}
        values.update(updates)
        return Settings(**values)

    return create
