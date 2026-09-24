"""公開CLIの非対話およびPTYによるRun選択を検証する。"""

from __future__ import annotations

import errno
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import cli


def _command(source: Path, output: Path) -> list[str]:
    """Test中のPythonから公開CLIのconvertを起動する引数列を作る。"""

    return [
        sys.executable,
        str(cli.__file__),
        "convert",
        str(source),
        "--output",
        str(output),
    ]


def _environment(runs: Path) -> dict[str, str]:
    """親環境を保持しつつRun保存先だけをTestの隔離領域へ変更する。"""

    environment = os.environ.copy()
    environment["TRANSLATE_RUNS_DIR"] = str(runs)
    return environment


def _run_noninteractive(
    source: Path, output: Path, runs: Path
) -> subprocess.CompletedProcess[str]:
    """標準入出力をcaptureした実CLIを有限時間で実行し、非対話時の選択規則を調べる。"""

    return subprocess.run(
        _command(source, output),
        cwd=Path(cli.__file__).parent,
        env=_environment(runs),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _run_ids(output: str) -> list[str]:
    """CLI出力に表示されたRun IDを、最初の出現順を保って重複なく取り出す。"""

    return list(dict.fromkeys(re.findall(r"run_id=([0-9a-f-]{36})", output)))


def test_noninteractive_cli_always_creates_new_run_for_same_input(
    tmp_path: Path,
) -> None:
    """stdin/stdoutがTTYでなければ候補があっても確認せず新規Runにする。"""

    source = tmp_path / "source.md"
    source.write_text("# title\n\nbody\n", encoding="utf-8")
    runs = tmp_path / "runs"
    first = _run_noninteractive(source, tmp_path / "first.docx", runs)
    second = _run_noninteractive(source, tmp_path / "second.docx", runs)
    combined = first.stdout + first.stderr + second.stdout + second.stderr

    assert first.returncode == second.returncode == 0, combined
    ids = _run_ids(first.stdout) + _run_ids(second.stdout)
    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert first.stdout.count("mode=new") == 1
    assert second.stdout.count("mode=new") == 1
    assert "同じ入力の既存Run" not in combined


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX PTY contract; Windows is covered by the non-interactive process test",
)
def test_posix_pty_selects_candidate_then_answers_yes_or_no(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    """複数候補を表示し、yはResume、nは新規Runを選ぶ。"""

    import pty  # noqa: PLC0415
    import select  # noqa: PLC0415

    source = tmp_path / "source.md"
    source.write_text("# title\n\nbody\n", encoding="utf-8")
    runs = tmp_path / "runs"
    first = _run_noninteractive(source, tmp_path / "first.docx", runs)
    second = _run_noninteractive(source, tmp_path / "second.docx", runs)
    assert first.returncode == second.returncode == 0
    existing_ids = _run_ids(first.stdout) + _run_ids(second.stdout)

    def interact(answer: bytes, output: Path) -> str:
        """
        PTYで候補選択とy/n回答を送り、CLI終了と残存childの後片付けまで行って出力を返す。
        """

        master, slave = pty.openpty()
        process = subprocess.Popen(
            _command(source, output),
            cwd=Path(cli.__file__).parent,
            env=_environment(runs),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        captured = bytearray()
        prompts = [(b"run ID", b"\n"), (b"[y/N]", answer + b"\n")]
        try:
            for marker, response in prompts:
                while marker not in captured:
                    ready, _, _ = select.select([master], [], [], 30)
                    assert ready, captured.decode(errors="replace")
                    captured.extend(os.read(master, 4096))
                os.write(master, response)
            while process.poll() is None:
                ready, _, _ = select.select([master], [], [], 30)
                assert ready, captured.decode(errors="replace")
                try:
                    captured.extend(os.read(master, 4096))
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    process.wait(timeout=10)
                    break
        finally:
            os.close(master)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        assert process.returncode == 0, captured.decode(errors="replace")
        return captured.decode(errors="replace")

    accepted = interact(b"y", tmp_path / "accepted.docx")
    assert all(run_id in accepted for run_id in existing_ids)
    assert "mode=resume" in accepted

    declined = interact(b"n", tmp_path / "declined.docx")
    assert "mode=new" in declined
    declined_ids = _run_ids(declined)
    assert declined_ids
    assert declined_ids[-1] not in existing_ids
