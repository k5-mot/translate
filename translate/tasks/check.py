"""CHECK: 用語集と翻訳の決定的品質検査。"""

from __future__ import annotations

import csv
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel

from translate.common.workspace import atomic_directory, atomic_write_json
from translate.document import Document, Finding, block_text_units
from translate.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

GLOSSARY_FIELDS = (
    "english-short",
    "english-long",
    "japanese-short",
    "japanese-long",
    "kind",
    "description",
    "note",
    "reference",
)
LITERAL_REFERENCE_RE = re.compile(
    r"""https?://[^\s<>()\[\]{}"'。、]+"""
    r"""|www\.[^\s<>()\[\]{}"'。、]+"""
    r"|(?<![\w.])[A-Za-z0-9_][A-Za-z0-9_.-]*\."
    r"(?:pdf|docx|xlsx|pptx|txt|md|csv|json|yaml|yml)(?![\w])",
    re.IGNORECASE,
)
NUMBER_UNIT_RE = re.compile(
    r"(?<!\w)[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:\s?(?:%|ms|s|MB|GB|KB|V|A|Hz|°C))?(?![A-Za-z])"
)
EN_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|without|mustn['’]t|cannot|can't)\b",  # noqa: RUF001
    re.IGNORECASE,
)
JA_NEGATION_RE = re.compile(r"(?:ない|ません|不可|禁止|ず|なし|ないで|できない)")
EN_CONDITION_RE = re.compile(
    r"\b(?:if|unless|when|provided that|in case)\b", re.IGNORECASE
)
JA_CONDITION_RE = re.compile(r"(?:場合|とき|なら|限り|条件|際)")
EN_COMPARISON_RE = re.compile(
    r"\b(?:more|less|than|at least|at most|greater|smaller|higher|lower)\b",
    re.IGNORECASE,
)
JA_COMPARISON_RE = re.compile(r"(?:以上|以下|より|超|未満|多|少|高|低)")


class GlossaryEntry(BaseModel):
    """原語と指定訳の一組を表す。"""

    source: str
    target: str
    notes: str = ""


def read_glossary(path: Path | None) -> list[GlossaryEntry]:
    """8列schemaのUTF-8 CSV用語集を検証してshort/long用語へ展開する。

    Args:
        path: 用語集path。Noneなら用語集なし。

    Returns:
        原語が重複しないshort/long用語entry列。

    Raises:
        ValueError: 必須列、値、原語の一意性が不正な場合。
    """

    if path is None:
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or [])
        if not set(GLOSSARY_FIELDS) <= fields:
            raise ValueError("glossary requires columns: " + ", ".join(GLOSSARY_FIELDS))
        values: list[GlossaryEntry] = []
        for number, row in enumerate(reader, start=2):
            metadata = "; ".join(
                f"{field}: {value}"
                for field in ("kind", "description", "note", "reference")
                if (value := (row.get(field) or "").strip())
            )
            pairs = [
                (
                    (row.get("english-short") or "").strip(),
                    (row.get("japanese-short") or "").strip(),
                ),
                (
                    (row.get("english-long") or "").strip(),
                    (row.get("japanese-long") or "").strip(),
                ),
            ]
            if not any(source or target for source, target in pairs):
                msg = f"glossary row {number} has no term"
                raise ValueError(msg)
            for source, target in pairs:
                if bool(source) != bool(target):
                    msg = f"glossary row {number} source and target must be paired"
                    raise ValueError(msg)
                if source:
                    values.append(
                        GlossaryEntry(source=source, target=target, notes=metadata)
                    )
    sources = [item.source.casefold() for item in values]
    if len(sources) != len(set(sources)):
        msg = "glossary source values must be unique"
        raise ValueError(msg)
    return values


def matching_glossary(text: str, glossary: list[GlossaryEntry]) -> list[GlossaryEntry]:
    """本文に原語が現れる用語だけを入力順で返す。

    Args:
        text: 用語を検索する英語本文。
        glossary: 全用語entry列。

    Returns:
        大小文字と連続空白を正規化して本文へ一致したentry列。
    """

    folded = text.casefold()
    result: list[GlossaryEntry] = []
    for entry in glossary:
        parts = entry.source.casefold().split()
        pattern = r"\s+".join(re.escape(part) for part in parts)
        if entry.source[0].isalnum():
            pattern = rf"(?<!\w){pattern}"
        if entry.source[-1].isalnum():
            pattern = rf"{pattern}(?!\w)"
        if re.search(pattern, folded):
            result.append(entry)
    return result


def literal_references(text: str) -> list[str]:
    """明示URLと既知拡張子のファイル名だけを警告候補として抽出する。

    Args:
        text: 原文。

    Returns:
        末尾の句読点を除いた出現順の参照文字列。
    """

    return [
        match.group(0).rstrip(".,;:!?") for match in LITERAL_REFERENCE_RE.finditer(text)
    ]


def _missing_literal_findings(source: str, target: str) -> list[Finding]:
    """数値・単位の欠落とURL・ファイル名の変更を検出する。

    Args:
        source: 原文。
        target: 訳文。

    Returns:
        欠落finding列。
    """

    findings = [
        Finding(
            kind="number-unit",
            severity="error",
            message=f"数値または単位が欠落: {value}",
            evidence=value,
        )
        for value in NUMBER_UNIT_RE.findall(source)
        if value not in target
    ]
    findings.extend(
        Finding(
            kind="literal-reference",
            severity="warning",
            message=f"URLまたはファイル名が欠落または変更: {value}",
            evidence=value,
        )
        for value in literal_references(source)
        if value not in target
    )
    return findings


def _length_findings(source: str, target: str) -> list[Finding]:
    """空訳・未翻訳と極端な長さ差を検出する。

    Args:
        source: 原文。
        target: 訳文。

    Returns:
        長さに関するfinding列。
    """

    source_text, target_text = source.strip(), target.strip()
    if source_text and not target_text:
        return [Finding(kind="omission", severity="error", message="訳文が空である")]
    if (
        source_text == target_text
        and len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", source)) >= 3
    ):
        return [
            Finding(
                kind="untranslated",
                severity="warning",
                message="複数語の英語原文が翻訳されていない",
            )
        ]
    if len(source_text) >= 80 and len(target_text) < len(source_text) * 0.15:
        return [
            Finding(
                kind="omission",
                severity="warning",
                message="訳文が原文に比べて極端に短い",
            )
        ]
    if len(target_text) >= 100 and len(target_text) > max(1, len(source_text)) * 5:
        return [
            Finding(
                kind="addition",
                severity="warning",
                message="訳文が原文に比べて極端に長い",
            )
        ]
    return []


def deterministic_findings(
    source: str, target: str, glossary: list[GlossaryEntry]
) -> list[Finding]:
    """原文と訳文を決定的な規則で比較し、欠落や誤訳の候補を返す。

    Args:
        source: 英語原文。
        target: 日本語訳文。
        glossary: 適用する用語集。

    Returns:
        検出したerror/warningのFinding列。語句の照合にはheuristicを含む。
    """

    # heuristicは自動修正せずfindingだけを返し、最終判断をReview graphへ委ねる。
    findings = _missing_literal_findings(source, target)
    if EN_NEGATION_RE.search(source) and not JA_NEGATION_RE.search(target):
        findings.append(
            Finding(
                kind="negation",
                severity="error",
                message="原文の否定表現を訳文で確認できない",
            )
        )
    if EN_CONDITION_RE.search(source) and not JA_CONDITION_RE.search(target):
        findings.append(
            Finding(
                kind="condition",
                severity="error",
                message="原文の条件表現を訳文で確認できない",
            )
        )
    if EN_COMPARISON_RE.search(source) and not JA_COMPARISON_RE.search(target):
        findings.append(
            Finding(
                kind="comparison",
                severity="error",
                message="原文の比較表現を訳文で確認できない",
            )
        )
    # 短い断片で誤検知しないよう、長さ比検査には最低文字数を設ける。
    findings.extend(_length_findings(source, target))
    for entry in glossary:
        if entry.source.casefold() in source.casefold() and entry.target not in target:
            findings.append(
                Finding(
                    kind="glossary",
                    severity="error",
                    message=f"指定訳が使われていない: {entry.source} → {entry.target}",
                    evidence=entry.source,
                    suggestion=entry.target,
                )
            )
    return findings


class CheckTask(BaseTask):
    """Execute CHECK while sharing elapsed-time measurement only."""

    name = "CHECK"

    def run(
        self, document: Document, glossary_path: Path | None, output_dir: Path
    ) -> dict[int, list[Finding]]:
        """文書全体を決定的に検査し、page別Findingを保存する。"""

        with self.measure():
            glossary = read_glossary(glossary_path)
            results: dict[int, list[Finding]] = {}
            for page in document.pages:
                page_findings: list[Finding] = []
                for block in page.blocks:
                    for unit in block_text_units(block):
                        findings = deterministic_findings(
                            unit.text("source"), unit.text("translated"), glossary
                        )
                        for finding in findings:
                            finding.target_ids = [unit.id]
                        page_findings.extend(findings)
                results[page.number] = page_findings
            with atomic_directory(output_dir) as temporary:
                for number, page_findings in results.items():
                    atomic_write_json(
                        temporary / f"page-{number:04d}.json",
                        [item.model_dump() for item in page_findings],
                    )
            return results


def run(
    document: Document, glossary_path: Path | None, output_dir: Path
) -> dict[int, list[Finding]]:
    """Existing function delegates to the typed CheckTask operation."""

    return CheckTask().run(document, glossary_path, output_dir)
