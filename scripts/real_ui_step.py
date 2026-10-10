"""実Streamlit画面から1工程を開始し、処理IDを表示する検証補助。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


def main() -> None:
    """指定された実ファイルをuploadしてUI処理を開始する。"""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("register", "translate", "review", "upgrade")
    )
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--resume")
    parser.add_argument("--url", default="http://127.0.0.1:8502")
    args = parser.parse_args()
    labels = {
        "register": ["参照資料"],
        "translate": ["英語PDF"],
        "review": ["英語原文PDF", "日本語訳文PDF"],
        "upgrade": ["英文v1 PDF", "英文v2 PDF", "日本語v1 PDF"],
    }
    buttons = {
        "register": "登録を開始",
        "translate": "翻訳を開始",
        "review": "レビューを開始",
        "upgrade": "Upgradeを開始",
    }
    if not args.resume and (
        not args.files
        or (
            args.operation != "register"
            and len(args.files) != len(labels[args.operation])
        )
    ):
        parser.error("operationとfile数が一致しません")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{args.url}/?processing={args.resume}" if args.resume else args.url)
        if args.resume:
            page.get_by_role(
                "checkbox",
                name="完了済みTaskとLLM Callを再利用し、未完了箇所から再開する",
            ).check(timeout=20_000)
            page.get_by_role("button", name="Resume", exact=True).click()
            page.locator("#translate-session-title").get_by_text(args.resume).wait_for(
                timeout=15_000
            )
            sys.stdout.write(f"processing_id={args.resume}\n")
            sys.stdout.flush()
            return
        tab = page.get_by_role("tab", name=args.operation.capitalize())
        tab.wait_for(timeout=15_000)
        for label, path in zip(labels[args.operation], args.files, strict=False):
            for attempt in range(3):
                tab.click()
                uploader = page.locator('[data-testid="stFileUploader"]').filter(
                    has_text=label
                )
                uploader.locator('input[type="file"]').set_input_files(path.resolve())
                try:
                    uploader.get_by_text(path.name, exact=True).wait_for(
                        state="attached", timeout=10_000
                    )
                    break
                except Exception:
                    if attempt == 2:
                        raise
        tab.click()
        page.get_by_role("button", name=buttons[args.operation]).click()
        page.wait_for_function(
            "new URL(location.href).searchParams.has('processing')", timeout=20_000
        )
        processing_id = parse_qs(urlparse(page.url).query)["processing"][0]
        page.locator("#translate-session-title").get_by_text(processing_id).wait_for(
            timeout=15_000
        )
        sys.stdout.write(f"processing_id={processing_id}\n")
        sys.stdout.flush()
        browser.close()


if __name__ == "__main__":
    main()
