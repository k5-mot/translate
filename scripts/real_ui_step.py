"""実Streamlit画面から1工程を開始し、処理IDを表示する検証補助。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pypdfium2 as pdfium
from playwright.sync_api import Page, expect, sync_playwright


def resume(page: Page, operation: str, processing_id: str) -> None:
    """Resumeのクリック後、既存の失敗記録が更新されるまで待つ。"""

    record_name = {"register": "registration", "translate": "translation"}.get(
        operation, operation
    )
    record_paths = list(Path("outputs").glob(f"*/{processing_id}/{record_name}.json"))
    if len(record_paths) != 1:
        message = f"Resume対象の記録を一意に特定できません: {processing_id}"
        raise RuntimeError(message)
    record_path = record_paths[0]
    previous_update = json.loads(record_path.read_text(encoding="utf-8"))["updated_at"]
    page.get_by_text(
        "完了済みTaskとLLM Callを再利用し、未完了箇所から再開する",
        exact=True,
    ).click(timeout=20_000)
    page.get_by_role("button", name="Resume", exact=True).click()
    deadline = time.monotonic() + 30
    while (
        json.loads(record_path.read_text(encoding="utf-8"))["updated_at"]
        == previous_update
    ):
        if time.monotonic() >= deadline:
            alerts = page.locator('[data-testid="stAlert"]').all_text_contents()
            message = f"Resumeが開始されませんでした: {alerts}"
            raise RuntimeError(message)
        page.wait_for_timeout(250)


def prepare_versions() -> None:
    """検証用の英文新版を原本から作り、最後の1ページを削除した変更を記録する。"""
    destination = Path(".tmp/versions")
    destination.mkdir(parents=True, exist_ok=True)
    for stem in ("sample", "sample2", "sample3"):
        source = Path("inputs") / f"{stem}.pdf"
        target = destination / source.name
        with pdfium.PdfDocument(source) as document:
            if len(document) < 2:
                message = "Upgrade fixture needs at least two source pages"
                raise ValueError(message)
            removed_page = len(document)
            del document[removed_page - 1]
            document.save(target)
        target.with_suffix(".json").write_text(
            json.dumps(
                {
                    "source": str(source),
                    "operation": "remove_last_page",
                    "removed_page": removed_page,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def inspect_result(page: Page, operation: str, processing_id: str) -> None:
    """完了画面に対象IDと成果物downloadがあり、UI例外がないことを確認する。"""
    labels = {
        "register": "Register記録をdownload",
        "translate": "DOCXをdownload",
        "review": "Review結果JSONをdownload",
        "upgrade": "Upgrade結果JSONをdownload",
    }
    expect(page.locator("#translate-session-title")).to_have_text(
        processing_id, timeout=30_000
    )
    expect(
        page.get_by_role("button", name=labels[operation], exact=True)
    ).to_be_visible(timeout=30_000)
    expect(page.locator('[data-testid="stException"]')).to_have_count(0)


def main() -> None:  # noqa: C901, PLR0915 — 1工程のbrowser操作を順序どおり記述する。
    """指定された実ファイルをuploadしてUI処理を開始する。"""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("register", "translate", "review", "upgrade")
    )
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--resume")
    parser.add_argument("--inspect")
    parser.add_argument("--screenshot", type=Path)
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
    if (
        not args.resume
        and not args.inspect
        and (
            not args.files
            or (
                args.operation != "register"
                and len(args.files) != len(labels[args.operation])
            )
        )
    ):
        parser.error("operationとfile数が一致しません")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        identifier = args.resume or args.inspect
        page.goto(f"{args.url}/?processing={identifier}" if identifier else args.url)
        if args.inspect:
            inspect_result(page, args.operation, args.inspect)
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.screenshot), full_page=True)
            browser.close()
            return
        if args.resume:
            resume(page, args.operation, args.resume)
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
