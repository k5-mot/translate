"""用語集CSVを保持し、英語原文に該当する行をLLM入力へ選択する。"""

import csv
import io
from functools import lru_cache


class Glossary:
    """parse済みの用語集と検索対象列を保持する。"""

    def __init__(self, contents: str) -> None:
        """CSVを読み、英語表記の列を確定する。

        Args:
            contents: 用語集CSVの全文。
        """
        self.rows = _rows(contents) if contents.strip() else ()
        self.header = self.rows[0] if self.rows else ()
        self.indexes = [
            index
            for index, name in enumerate(self.header)
            if name.strip().casefold() in {"english-short", "english-long"}
        ]

    def select(self, source: str, maximum_bytes: int | None = None) -> str:
        """原文に現れる用語を完全なCSV行単位で入力枠へ収める。

        Args:
            source: 用語を検索する英語原文。
            maximum_bytes: UTF-8 byte上限。省略時は制限しない。

        Returns:
            str: Headerと該当行。該当行がない場合は空文字。
        """
        if not source.strip() or not self.indexes:
            return ""
        header = _csv_row(self.header)
        size = len(header.encode("utf-8"))
        selected: list[str] = []
        folded_source = source.casefold()
        for row in self.rows[1:]:
            if not any(
                index < len(row) and _contains_term(folded_source, row[index])
                for index in self.indexes
            ):
                continue
            text = _csv_row(row)
            row_size = len(text.encode("utf-8"))
            if maximum_bytes is None or size + row_size <= maximum_bytes:
                selected.append(text)
                size += row_size
        return header + "".join(selected) if selected else ""


def _csv_row(row: tuple[str, ...]) -> str:
    """一つのCSV行を標準csv規則で直列化する。

    Args:
        row (tuple[str, ...]): CSV形式へ直列化する一行分のField列。

    Returns:
        str: 一つのCSV行を標準csv規則で直列化する。
    """

    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerow(row)
    return output.getvalue()


@lru_cache(maxsize=2)
def _rows(glossary: str) -> tuple[tuple[str, ...], ...]:
    """同じ用語集をCallごとに再parseせず、変更時だけ読直す。

    Args:
        glossary (str): 対象文書へ適用するCSV形式の用語集。

    Returns:
        tuple[tuple[str, ...], ...]: 同じ用語集をCallごとに再parseせず、変更時だけ読直す。
    """

    return tuple(
        tuple(row) for row in csv.reader(io.StringIO(glossary.lstrip("\ufeff")))
    )


def _contains_term(folded_source: str, term: str) -> bool:
    """ASCII英数字の語境界を保ちながら大小文字を無視して検索する。

    Args:
        folded_source (str): 大小文字を正規化した検索対象Text。
        term (str): 用語集から検索する見出し語。

    Returns:
        bool: ASCII英数字の語境界を保ちながら大小文字を無視して検索する。
    """

    value = term.strip().casefold()
    if not value:
        return False
    start = folded_source.find(value)
    while start >= 0:
        end = start + len(value)
        left_ok = not value[0].isascii() or not value[0].isalnum()
        right_ok = not value[-1].isascii() or not value[-1].isalnum()
        if not left_ok:
            left_ok = start == 0 or not _ascii_alnum(folded_source[start - 1])
        if not right_ok:
            right_ok = end == len(folded_source) or not _ascii_alnum(folded_source[end])
        if left_ok and right_ok:
            return True
        start = folded_source.find(value, start + 1)
    return False


def _ascii_alnum(value: str) -> bool:
    """一文字がASCII英数字かを返す。

    Args:
        value (str): ASCII英数字か判定する一文字。

    Returns:
        bool: 一文字がASCII英数字かを返す。
    """

    return value.isascii() and value.isalnum()
