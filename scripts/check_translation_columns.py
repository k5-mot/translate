"""訳者のコラムがReview・Upgradeで対象外として扱われたかを検査する。

`add_translation_columns.py`で訳文へ追加したコラムのunitを訳文のLOAD結果から探し、
Reviewでは訳文のみの要素として記録され、指摘・修正提案の対象外であることを確かめる。
Upgradeでは旧訳の対応に含まれず、修正提案がコラムの本文を含まないことを確かめる。
"""

import argparse
import json
import sys
from pathlib import Path

from translate.models.artifacts import ReviewResult
from translate.models.document import Document
from translate.models.upgrade import UpgradePlan


def _compact(text: str) -> str:
    """抽出時の改行や空白の差を除いて比較する。"""
    return "".join(text.split())


def _column_texts(stem: str) -> list[str]:
    """コラムの見出しと本文を、空白を除いた形で返す。"""
    specification = Path(__file__).with_name("translation_columns.json")
    columns = json.loads(specification.read_text(encoding="utf-8"))[stem]
    return [
        _compact(text)
        for column in columns
        for text in [column["title"], *column["paragraphs"]]
    ]


def column_units(document: Document, stem: str) -> dict[str, str]:
    """コラムの見出しまたは本文を含む訳文unitを返す。

    Args:
        document: 訳文のLOAD結果。
        stem: コラム定義の文書名。

    Returns:
        dict[str, str]: unit IDと本文。
    """
    texts = _column_texts(stem)
    return {
        unit.id: unit.text("source")
        for _, unit in document.text_units()
        if (body := _compact(unit.text("source")))
        and any(text in body or body in text for text in texts if len(body) >= 8)
    }


def _mixed(body: str, texts: list[str]) -> list[str]:
    """コラムと本文が一つのunitへ結合された場合に、含まれるコラムの文を返す。

    PDFからの抽出でコラムの直後の本文行が同じunitへ結合されることがある。
    この場合は本文側で対応付けてよく、コラムの文が修正で変わらないことを確かめる。
    """
    compact = _compact(body)
    remainder = compact
    contained = [text for text in texts if text in compact]
    for text in contained:
        remainder = remainder.replace(text, "")
    return contained if len(remainder) >= 8 else []


def check_review(root: Path, stem: str) -> list[str]:
    """Reviewの結果でコラムが対象外として扱われたかを検査する。"""
    document = Document.model_validate_json(
        (root / "tasks/12-load/translation/document.json").read_text(encoding="utf-8")
    )
    result = ReviewResult.model_validate_json(
        (root / "tasks/41-review/review.json").read_text(encoding="utf-8")
    )
    columns = column_units(document, stem)
    texts = _column_texts(stem)
    mixed = {key: _mixed(body, texts) for key, body in columns.items()}
    problems = [] if columns else ["column units were not found in the translation"]
    only = {
        key
        for group in result.groups
        if group.kind == "translation_only"
        for key in group.translation_ids
    }
    problems.extend(
        f"column {key} was matched instead of translation_only"
        for key in columns
        if key not in only and not mixed[key]
    )
    problems.extend(
        f"finding {finding.id} targets column {key}"
        for finding in result.findings
        for key in finding.target_ids
        if key in columns and not mixed[key]
    )
    spans = {
        unit.id: {span.id: span.text("source") for span in unit.spans}
        for _, unit in document.text_units()
    }
    for revision in result.revisions:
        key = revision.target_id
        if key not in columns:
            continue
        if not mixed[key]:
            problems.append(f"revision {revision.id} edits column {key}")
            continue
        revised = dict(spans[key])
        revised.update({edit.span_id: edit.text for edit in revision.edits})
        body = _compact("".join(revised.values()))
        problems.extend(
            f"revision {revision.id} changes column text in {key}"
            for text in mixed[key]
            if text not in body
        )
    return problems


def check_upgrade(root: Path, stem: str) -> list[str]:
    """Upgradeの結果でコラムが旧訳の対応と修正提案に含まれないかを検査する。"""
    document = Document.model_validate_json(
        (root / "tasks/12-load/translation-v1/document.json").read_text(
            encoding="utf-8"
        )
    )
    plan = UpgradePlan.model_validate_json(
        (root / "tasks/21-diff/plan.json").read_text(encoding="utf-8")
    )
    columns = column_units(document, stem)
    problems = [] if columns else ["column units were not found in the translation"]
    problems.extend(
        f"change {change.id} references column {key}"
        for change in plan.changes
        for key in change.translation_v1_ids
        if key in columns
    )
    problems.extend(
        f"change {change.id} suggests column text"
        for change in plan.changes
        if change.suggested_translation
        and any(
            _compact(text) in _compact(change.suggested_translation)
            for text in columns.values()
        )
    )
    return problems


def main() -> None:
    """検査結果を表示し、問題があれば終了コード1で終える。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["review", "upgrade"])
    parser.add_argument("stem", help="inputs配下のPDF名。例: sample5")
    parser.add_argument("root", type=Path, help="処理IDの出力directory")
    arguments = parser.parse_args()
    check = check_review if arguments.operation == "review" else check_upgrade
    problems = check(arguments.root, arguments.stem)
    label = f"{arguments.stem}/{arguments.operation}"
    for problem in problems:
        sys.stdout.write(f"COLUMN FAIL {label}: {problem}\n")
    if problems:
        sys.exit(1)
    sys.stdout.write(f"COLUMN PASS {label}\n")


if __name__ == "__main__":
    main()
