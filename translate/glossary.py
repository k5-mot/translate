"""LLMへ渡す用語集を英語原文に現れる項目だけへ絞る。"""

from __future__ import annotations

import csv
import io
from functools import lru_cache


def relevant_glossary(
    glossary: str, source: str, maximum_bytes: int | None = None
) -> str:
    """英語名が原文に現れ、入力枠へ収まる完全なCSV行だけを返す。"""

    rows = _rows(glossary) if glossary.strip() and source.strip() else ()
    if not rows:
        return ""
    header = rows[0]
    normalized = [value.strip().casefold() for value in header]
    indexes = [
        index
        for index, name in enumerate(normalized)
        if name in {"english-short", "english-long"}
    ]
    if not indexes:
        return ""
    folded_source = source.casefold()
    selected = [
        row
        for row in rows[1:]
        if any(
            index < len(row) and _contains_term(folded_source, row[index])
            for index in indexes
        )
    ]
    if not selected:
        return ""
    if maximum_bytes is not None:
        return _bounded_csv(header, selected, maximum_bytes)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows([header, *selected])
    return output.getvalue()


def _bounded_csv(
    header: tuple[str, ...], rows: list[tuple[str, ...]], maximum_bytes: int
) -> str:
    """CSVの行境界を壊さず、先に定義された用語からbyte上限へ収める。"""

    if maximum_bytes <= 0:
        return ""
    header_text = _csv_row(header)
    size = len(header_text.encode("utf-8"))
    selected: list[str] = []
    for row in rows:
        row_text = _csv_row(row)
        row_size = len(row_text.encode("utf-8"))
        if size + row_size <= maximum_bytes:
            selected.append(row_text)
            size += row_size
    return f"{header_text}{''.join(selected)}" if selected else ""


def _csv_row(row: tuple[str, ...]) -> str:
    """一つのCSV行を標準csv規則で直列化する。"""

    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerow(row)
    return output.getvalue()


@lru_cache(maxsize=2)
def _rows(glossary: str) -> tuple[tuple[str, ...], ...]:
    """同じ用語集をCallごとに再parseせず、変更時だけ読直す。"""

    return tuple(
        tuple(row) for row in csv.reader(io.StringIO(glossary.lstrip("\ufeff")))
    )


def _contains_term(folded_source: str, term: str) -> bool:
    """ASCII英数字の語境界を保ちながら大小文字を無視して検索する。"""

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
    """一文字がASCII英数字かを返す。"""

    return value.isascii() and value.isalnum()
