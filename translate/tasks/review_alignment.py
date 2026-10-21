"""REVIEW候補の原文・訳文対応付け。"""

from translate.adapters.llm import LLMClient
from translate.models.document import TextUnit
from translate.models.review import AlignmentResponse
from translate.tasks import SavedLLMCalls


def match_documents(
    calls: SavedLLMCalls,
    units: dict[str, list[TextUnit]],
    client: LLMClient,
    round_number: int,
) -> tuple[str, AlignmentResponse]:
    """Agentが選んだ原文と訳文の対応候補を取得し、参照と網羅性を検証する。

    Args:
        units: sourceとtranslationの候補TextUnit。
        client: LLM接続。
        round_number: Agent操作の連番。

    Returns:
        成功Call IDと対応付け応答。

    Raises:
        ValueError: 選択対象と対応groupのID・種別・網羅性が矛盾する場合。
        LLMError: LLM要求が失敗した場合。
    """
    expected = {role: [unit.id for unit in values] for role, values in units.items()}

    def validate(response: AlignmentResponse) -> None:
        """選択した各IDが一つのgroupに属し、未対応には理由があることを確認する。

        Args:
            response: 対応付け応答。

        Raises:
            ValueError: 対応関係が不正、または範囲外の結果を含む場合。
        """
        for role in ("source", "translation"):
            found = [
                key
                for group in response.groups
                for key in getattr(group, f"{role}_ids")
            ]
            if sorted(found) != sorted(expected[role]):
                raise ValueError(
                    "Correspondence must cover the selected IDs exactly once. "
                    f"{role}: missing={sorted(set(expected[role]) - set(found))}; "
                    f"duplicate={sorted({key for key in found if found.count(key) > 1})}; "
                    f"unknown={sorted(set(found) - set(expected[role]))}"
                )
        for group in response.groups:
            correct = (
                "matched"
                if group.source_ids and group.translation_ids
                else "source_only"
                if group.source_ids
                else "translation_only"
            )
            if group.kind != correct or not (group.source_ids or group.translation_ids):
                raise ValueError("Invalid correspondence kind")
            if group.kind != "matched" and not (group.reason or "").strip():
                raise ValueError("Unmatched correspondence requires a reason")

    payload: dict[str, object] = {
        role: [{"id": unit.id, "text": unit.text("source")} for unit in values]
        for role, values in units.items()
    }
    return calls.request(
        client,
        "match",
        round_number,
        [f"{role}:{key}" for role, keys in expected.items() for key in keys],
        payload,
        "\n".join(unit.text("source") for unit in units["source"]),
        AlignmentResponse,
        '{"groups":[{"reason":"brief content comparison",'
        '"kind":"matched|source_only|translation_only",'
        '"source_ids":["id"],"translation_ids":["id"]}]}. '
        "Every source ID and every translation ID must appear exactly once, including unmatched IDs. "
        "The source and translation arrays are independent candidate pools, not parallel rows. "
        "For each source, search ALL translation candidates for the same content; "
        "never pair by array position or similar IDs. "
        "Match only the same content, not related topics. "
        "When two texts do not correspond, return two groups: source_only and translation_only, "
        "each with its own IDs and reason. "
        "For every group, first name the actual source text and corresponding translation text in reason, "
        "or briefly state which content has no counterpart. "
        "Then select the kind and the IDs that belong to those texts. "
        "Do not use generic reasons such as matched content. "
        "Keep separate table cells separate: an identifier, its description, and its value are distinct content, even in the same row. "
        "A group with multiple units is valid only when those units are split fragments of the SAME content expressed on the other side. "
        "Account for the content of EVERY selected unit on BOTH sides; do not absorb an unmatched unit into a related match. "
        "If the identifier itself has no counterpart in this candidate pool, leave it source_only or translation_only.",
        validate,
    )
