"""Translate、Review、RegisterのTask順序と再開制御。"""

from uuid import UUID

from uuid_utils import uuid7


class InputError(ValueError):
    """CLIで終了code 2とする入力またはResume指定の不備。"""


def resolve_processing_id(processing_id: str | None, resume_id: str | None) -> str:
    """UI指定ID、Resume IDまたは新規UUIDv7を一意に決定する。

    Args:
        processing_id (str | None): 新規処理またはResume対象の処理ID。
        resume_id (str | None): Resume対象として指定された処理ID。

    Returns:
        str: UI指定ID、Resume IDまたは新規UUIDv7を一意に決定する。

    Raises:
        InputError: `processing ID and resume ID cannot be used together`、`processing ID
            must be a canonical UUIDv7`のいずれかと判定した場合。
    """

    if processing_id is not None and resume_id is not None:
        raise InputError("processing ID and resume ID cannot be used together")
    value = processing_id or resume_id
    if value is None:
        return str(uuid7())
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise InputError("processing ID must be a canonical UUIDv7") from error
    if parsed.version != 7 or str(parsed) != value.casefold():
        raise InputError("processing ID must be a canonical UUIDv7")
    return value
