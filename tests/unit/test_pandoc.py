"""Pandoc Adapterが文書内の表変換で機能確認結果を共有することを検証する。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from translate.adapters.pandoc import Pandoc


def test_pandoc_checks_features_once_for_multiple_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """複数の表を変換しても実行file探索と機能確認を繰り返さない。"""
    executable = MagicMock(return_value="pandoc.exe")
    run = MagicMock(
        side_effect=[
            SimpleNamespace(
                stdout="--reference-doc --list-of-figures --list-of-tables"
            ),
            SimpleNamespace(stdout="+native_numbering"),
            SimpleNamespace(stdout='{"pandoc-api-version":[1,23],"blocks":[]}'),
            SimpleNamespace(stdout="first table"),
            SimpleNamespace(stdout='{"pandoc-api-version":[1,23],"blocks":[]}'),
            SimpleNamespace(stdout="second table"),
        ]
    )
    monkeypatch.setattr("translate.adapters.pandoc.shutil.which", executable)
    monkeypatch.setattr("translate.adapters.pandoc.subprocess.run", run)
    adapter = Pandoc(timeout=7)
    assert adapter.table_to_markdown({"t": "Table", "c": []}) == "first table"
    assert adapter.table_to_markdown({"t": "Table", "c": []}) == "second table"
    executable.assert_called_once_with("pandoc")
    assert run.call_count == 6
    assert all(call.kwargs["timeout"] == 7 for call in run.call_args_list)
