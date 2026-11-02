"""文分割が略語で切れず、原文を欠落させないことを検証する。"""

import pytest

from translate.common.sentences import split_sentences


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("See Fig. 3 for details. Next.", ["See Fig. 3 for details. ", "Next."]),
        ("e.g. this works, i.e. fine.", ["e.g. this works, i.e. fine."]),
        ("Line one\nLine two", ["Line one\n", "Line two"]),
        ("これは文です。次の文", ["これは文です。", "次の文"]),
        ("", []),
    ],
)
def test_split_sentences_keeps_abbreviations_and_text(
    value: str, expected: list[str]
) -> None:
    """代表的な略語と境界を分け、連結すると入力へ戻る。"""
    result = split_sentences(value)
    assert result == expected
    assert "".join(result) == value
