"""4つのStreamlit操作をPlaywright browserで検証する。"""

from __future__ import annotations

import os
import re
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
                uploader.get_by_text(path.name, exact=True).wait_for(
                    state="attached", timeout=10_000
                )
                break
            except PlaywrightTimeoutError:
                if attempt == 2:
                    raise
    page.get_by_role("tab", name=tab_name).click()


def _assert_appbar_alignment(page: Page) -> None:
    """Translate、Session IDおよびDeployの縦中央が揃うことを検証する。"""

    title = page.locator("#translate-session-title")
    expect(title).to_have_text("新規セッション")
    elements = [
        page.locator('[data-testid="stSidebarLogo"]'),
        title,
        page.get_by_text("Deploy", exact=True),
    ]
    boxes = [element.bounding_box() for element in elements]
    assert all(box is not None for box in boxes)
    centers = [box["y"] + box["height"] / 2 for box in boxes if box is not None]
    assert max(centers) - min(centers) <= 2


def _assert_translation_downloads_outside_progress(page: Page) -> None:
    """Translate成果物を進捗外へ横並びにし、相対画像を表示する。"""

    progress = page.locator('[data-testid="stExpander"]').filter(
        has_text="進捗と処理内容"
    )
    diff = progress.locator('[data-testid="stExpander"]').filter(has_text="差分を表示")
    diff.locator("summary").click()
    expect(diff.locator("code")).to_contain_text("-English")
    expect(diff.locator("code")).to_contain_text("+日本語")
    buttons = [
        page.get_by_role("button", name=label)
        for label in ("Markdownをdownload", "DOCXをdownload")
    ]
    for label, button in zip(
        ("Markdownをdownload", "DOCXをdownload"), buttons, strict=True
    ):
        expect(button).to_be_visible()
        assert progress.get_by_role("button", name=label).count() == 0
    page.wait_for_function(
        """labels => {
            const buttons = [...document.querySelectorAll('button')]
                .filter(button => labels.includes(button.textContent.trim()));
            if (buttons.length !== labels.length) return false;
            const [left, right] = buttons.map(button => button.getBoundingClientRect());
            return left.x < right.x
                && Math.max(left.top, right.top) < Math.min(left.bottom, right.bottom);
        }""",
        arg=["Markdownをdownload", "DOCXをdownload"],
    )
    boxes = [button.bounding_box() for button in buttons]
    assert all(box is not None for box in boxes)
    left, right = (box for box in boxes if box is not None)
    assert left["x"] < right["x"]
    assert max(left["y"], right["y"]) < min(
        left["y"] + left["height"],
        right["y"] + right["height"],
    )
    preview = page.locator('[data-testid="stExpander"]').filter(
        has_text="Markdown preview"
    )
    preview.locator("summary").click()
    image = preview.locator("img").last
    expect(image).to_be_visible()
    assert image.evaluate("element => element.naturalWidth") > 0, (
        image.get_attribute("src"),
        preview.inner_text(),
    )


def _wait_for_success(page: Page, previous_url: str) -> None:
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
    expect(page.locator("#translate-session-title")).to_have_text(processing_id)
    page.get_by_text(re.compile(r"\d+ / \d+ Task .* succeeded$")).last.wait_for(
        timeout=15_000
    )


def _open_settings(page: Page) -> None:
    """処理開始後に閉じた入力・設定領域を再度展開する。"""

    settings = page.locator('[data-testid="stExpander"]').filter(has_text="入力と設定")
    details = settings.locator("details")
    if details.get_attribute("open") is None:
        settings.locator("summary").click()


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
    page.locator('[data-testid="stSidebarLogo"]').wait_for(timeout=15_000)
    page.get_by_role("tab", name="Register").wait_for(timeout=15_000)
    _assert_appbar_alignment(page)
    assert page.get_by_role("tab").all_inner_texts() == [
        "Translate",
        "Review",
        "Upgrade",
        "Register",
    ]

    _upload(page, "Translate", ["英語PDF"], [files["source.pdf"]])
    previous_url = page.url
    page.get_by_role("button", name="翻訳を開始").click()
    expect(page.get_by_label("翻訳後 (日本語)")).to_have_value(
        "[span-1]\n日本語",
        timeout=15_000,
    )
    _wait_for_success(page, previous_url)
    _assert_translation_downloads_outside_progress(page)

    _open_settings(page)
    page.get_by_role("tab", name="Review").click()
    _upload(
        page,
        "Review",
        ["英語原文PDF", "日本語訳文PDF"],
        [files["source.pdf"], files["translation.pdf"]],
    )
    previous_url = page.url
    page.get_by_role("button", name="レビューを開始").click()
    _wait_for_success(page, previous_url)

    _open_settings(page)
    page.get_by_role("tab", name="Upgrade").click()
    _upload(
        page,
        "Upgrade",
        ["英文v1 PDF", "英文v2 PDF", "日本語v1 PDF"],
        [files["source-v1.pdf"], files["source-v2.pdf"], files["translation-v1.pdf"]],
    )
    previous_url = page.url
    page.get_by_role("button", name="Upgradeを開始").click()
    _wait_for_success(page, previous_url)

    _open_settings(page)
    page.get_by_role("tab", name="Register").click()
    _upload(page, "Register", ["参照資料"], [files["reference.txt"]])
    previous_url = page.url
    page.get_by_role("button", name="登録を開始").click()
    _wait_for_success(page, previous_url)
