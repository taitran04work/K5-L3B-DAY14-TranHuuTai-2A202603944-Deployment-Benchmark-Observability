"""Capture real observability UIs in an isolated, always-closed browser."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("url")
parser.add_argument("filename")
parser.add_argument("--wait", type=int, default=8000)
parser.add_argument("--expand", action="store_true")
args = parser.parse_args()
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        context = browser.new_context(viewport={"width": 2560, "height": 1440}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait)
        if args.expand:
            for text in ["chat mock-llm-small", "Details", "Logs", "Events"]:
                locator = page.get_by_text(text, exact=True)
                if locator.count():
                    locator.first.click()
                    page.wait_for_timeout(800)
        print("URL:", page.url)
        print("BODY:", page.locator("body").inner_text()[:6500])
        print("BUTTONS:", json.dumps(page.locator("button").all_text_contents(), ensure_ascii=False)[:4000])
        out = ROOT / "screenshots" / args.filename
        out.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(out), full_page=True)
        print("SCREENSHOT:", out)
        page.set_viewport_size({"width": 1280, "height": 1000})
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out.with_name(out.stem + "-1280.png")), full_page=True)
        (ROOT / "reports" / (out.stem + "-browser.json")).write_text(json.dumps({"url": page.url, "page_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("PAGE_ERRORS:", errors)
        context.close()
    finally:
        browser.close()
