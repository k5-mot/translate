"""WindowsでのUI upload確定処理を検証する。"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from translate.artifact_store import atomic_write_bytes
from translate.ui import _stage_uploads

if TYPE_CHECKING:
    from streamlit.runtime.uploaded_file_manager import UploadedFile

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="WinError 5の例外属性はWindowsでのみ再現できるため。",
)


class _Upload:
    """Testに必要なUploadedFileの最小属性を提供する。"""

    name = "source.pdf"

    def getvalue(self) -> bytes:
        """固定したupload本文を返す。"""

        return b"source"


def _skip_sleep(_seconds: float) -> None:
    """再試行の待機だけを省略してtestを高速に保つ。"""


def test_stage_uploads_retries_transient_windows_access_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """directory確定時の一時的なWinError 5を再試行する。"""

    original = Path.replace
    attempts = 0

    def replace(path: Path, target: Path) -> Path:
        """最初のdirectory renameだけWindowsのアクセス拒否を再現する。"""

        nonlocal attempts
        if path.is_dir():
            attempts += 1
            if attempts == 1:
                raise PermissionError(
                    13,
                    "Access is denied",
                    str(path),
                    5,
                    str(target),
                )
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr("translate.artifact_store.time.sleep", _skip_sleep)
    upload = cast("UploadedFile", _Upload())

    staged = _stage_uploads(
        "0199bde8-a610-7c89-8000-000000000001",
        [(upload, Path("translate/source.pdf"))],
        work_root=tmp_path,
    )

    assert attempts == 2
    assert staged[0].read_bytes() == b"source"


def test_atomic_write_retries_transient_windows_access_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """処理記録のfile確定時にも一時的なWinError 5を再試行する。"""

    target = tmp_path / "translation.json"
    target.write_bytes(b"old")
    original = Path.replace
    attempts = 0

    def replace(path: Path, destination: Path) -> Path:
        """最初のfile replaceだけWindowsのアクセス拒否を再現する。"""

        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(
                13,
                "Access is denied",
                str(path),
                5,
                str(destination),
            )
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr("translate.artifact_store.time.sleep", _skip_sleep)

    atomic_write_bytes(target, b"new")

    assert attempts == 2
    assert target.read_bytes() == b"new"
