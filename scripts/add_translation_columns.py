"""訳者が補足したコラムを訳文DOCXへ追加し、Review・Upgradeの検証入力を作る。

コラムは英文のどの版にも対応がない訳文だけの内容とする。Review・Upgradeは
この内容を指摘・修正せず、英文に対応する訳文だけを扱うことを検証する。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

# 見出しより本文段落の後ろへ置くため、この文字数以上の段落を優先する。
_BODY_MIN_CHARS = 40


class Column(TypedDict):
    """訳文へ追加する一つのコラム。"""

    after: str
    title: str
    paragraphs: list[str]


def _boxed(paragraph: Paragraph) -> None:
    """段落へ枠線と網掛けを付け、本文と区別できるコラムの体裁にする。"""
    properties = paragraph.paragraph_format.element.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{side}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "6")
        border.set(qn("w:space"), "4")
        border.set(qn("w:color"), "808080")
        borders.append(border)
    properties.append(borders)
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), "F2F2F2")
    properties.append(shading)


def add_columns(source: Path, target: Path, columns: list[Column]) -> None:
    """指定段落の直後へコラムを追加して保存する。

    Args:
        source: Translateが生成した訳文DOCX。
        target: コラムを追加したDOCXの保存先。
        columns: 直前段落に含まれる語句`after`、`title`、`paragraphs`の一覧。
            `after`は`|`区切りで候補を優先順に列挙できる。

    """
    document = docx.Document(str(source))
    for number, column in enumerate(columns):
        paragraphs = document.paragraphs
        texts = [" ".join(paragraph.text.split()) for paragraph in paragraphs]
        # 訳文は実行ごとに表現が変わるため、`|`区切りの語句を順に探す。
        matches = next(
            (
                found
                for anchor in column["after"].split("|")
                if (found := [n for n, text in enumerate(texts) if anchor in text])
            ),
            [],
        )
        if not matches:
            # 語句が訳文にない場合も検証を止めず、文書内の決まった位置の段落を使う。
            position = (number + 1) / (len(columns) + 1)
            matches = [round(position * (len(paragraphs) - 1))]
            sys.stdout.write(
                f"Column anchor not found: {column['after']}; "
                f"inserted after paragraph {matches[0]}\n"
            )
        # 見出しより本文段落の後ろへ置く。
        index = next(
            (
                number
                for number in matches
                if len(paragraphs[number].text.strip()) >= _BODY_MIN_CHARS
            ),
            matches[0],
        )
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else None
        # 次の段落の直前へ順に挿入し、コラム内の段落を指定順に並べる。
        for text in [column["title"], *column["paragraphs"]]:
            paragraph = (
                following.insert_paragraph_before()
                if following is not None
                else document.add_paragraph()
            )
            paragraph.add_run(text).bold = text == column["title"]
            _boxed(paragraph)
    document.save(str(target))


def main() -> None:
    """コマンドライン引数から文書名を受け取り、対応するコラムを追加する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stem", help="inputs配下のPDF名。例: sample5")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    arguments = parser.parse_args()
    specification = Path(__file__).with_name("translation_columns.json")
    columns = json.loads(specification.read_text(encoding="utf-8"))[arguments.stem]
    add_columns(arguments.source, arguments.target, columns)


if __name__ == "__main__":
    main()
