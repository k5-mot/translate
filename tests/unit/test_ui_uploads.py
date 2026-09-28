"""WindowsでのUI upload確定処理を検証する。"""

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from translate.ui import _stage_uploads

if TYPE_CHECKING:
    from streamlit.runtime.uploaded_file_manager import UploadedFile


class _Upload:
    """Testに必要なUploadedFileの最小属性を提供する。"""

    name = "source.pdf"

    def getvalue(self) -> bytes:
        """固定したupload本文を返す。"""

        return b"source"


def test_stage_uploads_retries_transient_windows_access_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """directory確定時の一時的なWinError 5を再試行する。"""

    original = Path.replace
    attempts = 0

    def do_not_sleep(_seconds: float) -> None:
        """Retry待機を省略してtestを高速に保つ。"""

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
    monkeypatch.setattr("translate.ui.time.sleep", do_not_sleep)
    upload = cast("UploadedFile", _Upload())

    staged = _stage_uploads(
        "0199bde8-a610-7c89-8000-000000000001",
        [(upload, Path("translate/source.pdf"))],
        work_root=tmp_path,
    )

    assert attempts == 2
    assert staged[0].read_bytes() == b"source"
