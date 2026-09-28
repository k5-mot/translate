"""sample3.pdfをStreamlit UIから翻訳するPlaywright受入検証。"""

from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

_LOGGER = logging.getLogger(__name__)


def _wait_for_translation(page: Page, timeout_seconds: float) -> None:
    """UIをpollし、Translate成功または失敗を判定する。"""

    deadline = time.monotonic() + timeout_seconds
    previous_status = ""
    while time.monotonic() < deadline:
        body = page.locator("body").inner_text()
        status = next(
            (line for line in body.splitlines() if line.startswith("状態:")),
            "準備中",
        )
        if status != previous_status:
            _LOGGER.info("UI status: %s", status)
            previous_status = status
        if "状態: succeeded" in body:
            return
        if "状態: failed" in body or "処理に失敗しました" in body:
            message = f"Streamlit translation failed:\n{body[-4000:]}"
            raise AssertionError(message)
        page.wait_for_timeout(1000)
    message = f"Streamlit translation exceeded {timeout_seconds} seconds"
    raise AssertionError(message)


def _download(page: Page, label: str, suffix: str) -> None:
    """指定labelのbuttonから成果物をdownloadできることを検証する。"""

    with page.expect_download(timeout=60_000) as download_info:
        page.get_by_role("button", name=label).click()
    download = download_info.value
    assert download.suggested_filename.endswith(suffix)
    assert download.failure() is None


def verify(url: str, source: Path, timeout_seconds: float) -> None:
    """実browserでupload、開始、進捗、完了とdownloadを通して検証する。"""

    assert source.is_file()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        expect(page.get_by_role("heading", name="🌐 Translate")).to_be_visible()
        page.locator('input[type="file"]').first.set_input_files(str(source))
        start = page.get_by_role("button", name="翻訳を開始")
        expect(start).to_be_enabled(timeout=30_000)
        start.click()
        page.wait_for_url(re.compile(r"[?&]processing=[0-9a-f-]{36}"), timeout=60_000)
        _wait_for_translation(page, timeout_seconds)
        _download(page, "Markdownをdownload", ".md")
        _download(page, "DOCXをdownload", ".docx")
        evidence = Path("test-results/streamlit-sample3-success.png")
        evidence.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(evidence), full_page=True)
        browser.close()


def main() -> None:
    """CLI引数を読みPlaywright受入検証を開始する。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8501")
    parser.add_argument("--source", type=Path, default=Path("inputs/sample3.pdf"))
    parser.add_argument("--timeout", type=float, default=21_600)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    verify(arguments.url, arguments.source.resolve(), arguments.timeout)


if __name__ == "__main__":
    main()
