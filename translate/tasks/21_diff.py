"""Agentが選択した英文二版と旧訳を比較するDIFF Task。"""

from pathlib import Path

from translate.adapters.llm import LLMClient
from translate.models.document import TextUnit
from translate.models.upgrade import DiffResponse
from translate.tasks import saved_request


def diff(
    units: dict[str, list[TextUnit]],
    directory: Path,
    client: LLMClient,
    rules: str,
    glossary: str,
    operation: str,
    round_number: int,
) -> tuple[str, DiffResponse]:
    """選択された範囲の版間対応・変更分類・修正提案を作り検証する。

    Args:
        units: source_v1、source_v2、translation_v1の選択本文。
        directory: DIFF成果物の保存場所。
        client: Agent内で共有するLLM接続。
        rules: 比較と提案の判断規則。
        glossary: 原文に関連する用語を抽出するCSV。
        operation: match、evaluateまたはrecheck。
        round_number: Agent操作の連番。

    Returns:
        成功Call IDと、未変更も含む検証済みの比較結果。

    Raises:
        ValueError: ID・対応関係・確認範囲が不正な場合。
        LLMError: LLMまたは参照資料の検索が失敗した場合。
    """
    expected = {role: [unit.id for unit in values] for role, values in units.items()}

    def validate(response: DiffResponse) -> None:
        """変更項目と確認済みIDが選択範囲に一致することを検証する。

        Args:
            response: Schema検証済みの変更候補。

        Raises:
            ValueError: 不明ID、確認漏れ、重複、変更種別の矛盾がある場合。
        """
        for role in ("source_v1", "source_v2"):
            found = [
                key
                for change in response.changes
                for key in getattr(change, f"{role}_ids")
            ]
            if sorted(found) != sorted(expected[role]) or sorted(
                getattr(response, f"reviewed_{role}_ids")
            ) != sorted(expected[role]):
                raise ValueError(
                    "DIFF must account for every selected source ID exactly once"
                )
        translation_ids = []
        for change in response.changes:
            if not change.summary.strip():
                raise ValueError("DIFF requires a summary or reason")
            old, new = bool(change.source_v1_ids), bool(change.source_v2_ids)
            if (
                not (old or new)
                or (change.kind == "added" and (old or not new))
                or (change.kind == "deleted" and (new or not old))
            ):
                raise ValueError("DIFF kind contradicts its source IDs")
            if change.kind in {"unchanged", "moved", "modified"} and not (old and new):
                raise ValueError("Paired changes require old and new source IDs")
            translation_ids.extend(change.translation_v1_ids)
        if len(translation_ids) != len(set(translation_ids)) or not set(
            translation_ids
        ).issubset(expected["translation_v1"]):
            raise ValueError("Invalid or duplicated previous translation reference")

    payload: dict[str, object] = {
        role: [{"id": unit.id, "text": unit.text("source")} for unit in values]
        for role, values in units.items()
    }
    return saved_request(
        client,
        "DIFF",
        operation,
        round_number,
        [f"{role}:{key}" for role, keys in expected.items() for key in keys],
        payload,
        directory,
        rules,
        glossary,
        "\n".join(
            unit.text("source")
            for role in ("source_v1", "source_v2")
            for unit in units[role]
        ),
        DiffResponse,
        '{"changes":[{"kind":"unchanged|moved|modified|added|deleted",'
        '"source_v1_ids":["id"],"source_v2_ids":["id"],"translation_v1_ids":["id"],'
        '"summary":"change and proposed action or uncertainty","suggested_translation":null}],'
        '"reviewed_source_v1_ids":["id"],"reviewed_source_v2_ids":["id"]}. '
        "Cover every selected English ID exactly once. Propose Japanese edits for added/modified text. "
        "Keep unchanged only for coverage. Do not create a complete document.",
        validate,
    )
