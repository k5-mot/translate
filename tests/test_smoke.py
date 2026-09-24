"""公開entry pointとtest基盤の最小smoke test。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli import app
from main import main

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.settings import Settings


def test_public_entry_points_import() -> None:
    """製品として保証する二つのentry pointをimportできる。"""

    assert app is not None
    assert callable(main)


def test_settings_factory(settings_factory: Callable[..., Settings]) -> None:
    """settings factoryでDoclingの接続先をTest用URLへ上書きできる。"""

    settings = settings_factory(docling_url="https://docling.invalid")

    assert settings.docling_url == "https://docling.invalid"
