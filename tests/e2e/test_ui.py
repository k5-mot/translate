"""4つのStreamlit操作をPlaywright browserで検証する。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page


def _free_port() -> int:
    """loopbackへ一時bindして空きport候補を返す。"""

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def streamlit_url(tmp_path: Path) -> Iterator[str]:
    """E2E driverを実Streamlit processとして起動する。"""

    project = Path(__file__).resolve().parents[2]
    port = _free_port()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(project / "tests/e2e/streamlit_driver.py"),
            "--server.headless=true",
            f"--server.port={port}",
            "--server.address=127.0.0.1",
            "--browser.gatherUsageStats=false",
        ],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                pytest.fail(f"Streamlit exited before health check: {output}")
            try:
                with urllib.request.urlopen(  # noqa: S310 - loopback HTTP health check.
                    f"{url}/_stcore/health", timeout=1
                ) as response:
                    if response.read() == b"ok":
                        break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("Streamlit health check timed out")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _upload(page: Page, indexes: list[int], paths: list[Path]) -> None:
    """指定順のStreamlit uploaderへfileを設定する。"""

    uploaders = page.locator('[data-testid="stFileUploader"] input[type="file"]')
    for index, path in zip(indexes, paths, strict=True):
        uploaders.nth(index).set_input_files(path)


def _wait_for_success(page: Page) -> None:
    """選択した処理の成功表示まで待つ。"""

    page.get_by_text("状態: succeeded", exact=True).last.wait_for(timeout=15_000)
    assert "processing=" in page.url


@pytest.mark.e2e
@pytest.mark.browser
def test_streamlit_runs_translate_review_upgrade_and_register(
    page: Page, streamlit_url: str, tmp_path: Path
) -> None:
    """指定tab順を確認し、4操作を実browserから開始する。"""

    files = {
        name: tmp_path / name
        for name in (
            "source.pdf",
            "translation.pdf",
            "source-v1.pdf",
            "source-v2.pdf",
            "translation-v1.pdf",
            "reference.txt",
        )
    }
    for path in files.values():
        path.write_bytes(b"e2e")
    page.goto(streamlit_url)
    page.get_by_text("🌐 Translate", exact=True).wait_for(timeout=15_000)
    page.get_by_role("tab", name="Register").wait_for(timeout=15_000)
    assert page.get_by_role("tab").all_inner_texts() == [
        "Translate",
        "Review",
        "Upgrade",
        "Register",
    ]

    _upload(page, [0], [files["source.pdf"]])
    page.get_by_role("button", name="翻訳を開始").click()
    _wait_for_success(page)

    page.get_by_role("tab", name="Review").click()
    _upload(page, [1, 2], [files["source.pdf"], files["translation.pdf"]])
    page.get_by_role("button", name="レビューを開始").click()
    _wait_for_success(page)

    page.get_by_role("tab", name="Upgrade").click()
    _upload(
        page,
        [3, 4, 5],
        [files["source-v1.pdf"], files["source-v2.pdf"], files["translation-v1.pdf"]],
    )
    page.get_by_role("button", name="Upgradeを開始").click()
    _wait_for_success(page)

    page.get_by_role("tab", name="Register").click()
    _upload(page, [6], [files["reference.txt"]])
    page.get_by_role("button", name="登録を開始").click()
    _wait_for_success(page)
