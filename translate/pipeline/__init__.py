"""Translate、Review、RegisterのTask順序と再開制御。"""


class InputError(ValueError):
    """CLIで終了code 2とする入力またはResume指定の不備。"""
