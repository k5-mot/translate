"""4つのStreamlit操作をPlaywright browserで検証する。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

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


def _upload(page: Page, tab_name: str, labels: list[str], paths: list[Path]) -> None:
    """可視labelで指定したStreamlit uploaderへfileを設定する。"""

    for label, path in zip(labels, paths, strict=True):
        for attempt in range(3):
            page.get_by_role("tab", name=tab_name).click()
            uploader = page.locator('[data-testid="stFileUploader"]').filter(
                has_text=label
            )
            uploader.locator('input[type="file"]').set_input_files(path)
            try:
                uploader.get_by_role(
                    "button", name=f"Remove {path.name}", exact=True
                ).wait_for(state="attached", timeout=30_000)
                break
            except PlaywrightTimeoutError:
                if attempt == 2:
                    raise
    page.get_by_role("tab", name=tab_name).click()


def _wait_for_success(
    page: Page, previous_url: str, outputs: Path, operation: str
) -> None:
    """開始したPipelineのSession IDと成功ProgressBarへの更新を待つ。"""

    page.wait_for_function(
        """previous => location.href !== previous
        && new URL(location.href).searchParams.has('processing')""",
        arg=previous_url,
        timeout=15_000,
    )
    processing_id = page.evaluate(
        "new URL(location.href).searchParams.get('processing')"
    )
    expect(
        page.get_by_role("heading", name="Translate", exact=True).last
    ).to_be_visible()
    state_file = {
        "Translate": "state-translation.json",
        "Review": "state-review.json",
        "Upgrade": "state-upgrade.json",
        "Register": "state-registration.json",
    }[operation]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for state_path in outputs.glob(f"*/{processing_id}/{state_file}"):
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state["status"] == "succeeded":
                return
            if state["status"] in {"failed", "cancelled"}:
                pytest.fail(f"{operation} ended with status {state['status']}")
        time.sleep(0.1)
    pytest.fail(f"{operation} did not reach succeeded")


def _open_settings(page: Page) -> None:
    """処理開始後に閉じた入力・設定領域を再度展開する。"""

    settings = page.locator('[data-testid="stExpander"]').filter(has_text="入力と設定")
    details = settings.locator("details")
    if details.get_attribute("open") is None:
        settings.locator("summary").click()


@pytest.mark.e2e
@pytest.mark.browser
@pytest.mark.parametrize("operation", ["Translate", "Review", "Upgrade", "Register"])
def test_streamlit_operation_reaches_success(
    operation: str, page: Page, streamlit_url: str, tmp_path: Path
) -> None:
    """4つの操作を画面から開始し、成功状態になるまでを確認する。"""
    page.goto(streamlit_url)
    if operation == "Translate":
        files = [tmp_path / "source.pdf"]
        labels = ["英語PDF"]
    elif operation == "Review":
        files = [tmp_path / "source.pdf", tmp_path / "translation.pdf"]
        labels = ["英語原文PDF", "日本語訳文PDF"]
    elif operation == "Upgrade":
        files = [
            tmp_path / "source-v1.pdf",
            tmp_path / "source-v2.pdf",
            tmp_path / "translation-v1.pdf",
        ]
        labels = ["英文v1 PDF", "英文v2 PDF", "日本語v1 PDF"]
    else:
        files = [tmp_path / "reference.pdf"]
        labels = ["参照資料"]
    for path in files:
        path.write_bytes(b"e2e")
    _upload(page, operation, labels, files)
    previous_url = page.url
    page.get_by_role("button", name=f"Start {operation}").click()
    _wait_for_success(page, previous_url, tmp_path / "outputs", operation)
    if operation == "Translate":
        page.get_by_role("button", name="新規処理").click()
        page.wait_for_function("!new URL(location.href).searchParams.has('processing')")
        expect(
            page.get_by_role("heading", name="Translate", exact=True).last
        ).to_be_visible()
