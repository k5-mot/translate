"""翻訳単位とchunk境界に使う文分割。"""

import re

import pysbd

# 日本語の終止記号と改行はpysbdへ渡す前に分け、英語の省略記号の判定だけを委ねる。
_HARD_BOUNDARY = re.compile(r"(?<=[\u3002\uff01\uff1f])\s*|\n+")
_SEGMENTER = pysbd.Segmenter(language="en", clean=False)


def split_sentences(value: str) -> list[str]:
    """空白と改行を保持したまま、略語や小数の途中で切らず文へ分ける。

    Args:
        value: 分割する文字列。

    Returns:
        連結すると入力と一致する文の列。空文字列では空の列。
    """
    pieces: list[str] = []
    start = 0
    for boundary in _HARD_BOUNDARY.finditer(value):
        if boundary.end() > start:
            pieces.append(value[start : boundary.end()])
            start = boundary.end()
    if start < len(value):
        pieces.append(value[start:])
    result: list[str] = []
    for piece in pieces:
        parts = _SEGMENTER.segment(piece)
        # pysbdが文字を整形した場合は欠落させず、その断片を分割しない。
        result.extend(parts if "".join(parts) == piece else [piece])
    return result
