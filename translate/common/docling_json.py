"""Docling JSON内の参照解決。"""

from typing import Any


def resolve_ref(document: dict[str, Any], ref: str) -> Any:
    """`#/collection/index`形式の内部参照を値へ解決する。

    Args:
        document: 参照元のDocling JSON。
        ref: JSON Pointer形式の内部参照。

    Returns:
        参照先の値。

    Raises:
        KeyError: 辞書のkeyが存在しない場合。
        IndexError: 配列のindexが範囲外の場合。
        TypeError: 途中の値が辞書または配列でない場合。
        ValueError: 配列のindexが整数でない場合。
    """
    value: Any = document
    for part in ref.removeprefix("#/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value
