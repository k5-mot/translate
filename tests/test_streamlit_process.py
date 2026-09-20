"""Streamlit公開processの起動と停止を検証する。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

import main


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.mark.browser
def test_streamlit_headless_process_health_and_safe_shutdown(tmp_path: Path) -> None:
    """main.pyをheadless起動し、health応答後に子processを終了する。"""

    port = _free_port()
    environment = os.environ.copy()
    environment["TRANSLATE_RUNS_DIR"] = str(tmp_path / "runs")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(main.__file__),
            "--server.headless=true",
            f"--server.port={port}",
            "--server.address=127.0.0.1",
            "--browser.gatherUsageStats=false",
        ],
        cwd=Path(main.__file__).parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    response_body = ""
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                pytest.fail(f"Streamlit exited before health check: {output}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/_stcore/health", timeout=1
                ) as response:
                    response_body = response.read().decode("utf-8")
                    break
            except OSError:
                time.sleep(0.2)
        assert response_body == "ok"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    assert process.returncode is not None
