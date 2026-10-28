from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp('http://127.0.0.1:9227')
        pages = [page for context in browser.contexts for page in context.pages if 'amap.com' in page.url]
        if not pages:
            raise SystemExit('no Amap page is open')
        page = pages[0]
        body_text = page.locator('body').inner_text(timeout=10_000)
        selectors = (
            '[class*="search-list"]',
            '[class*="detail"]',
            '[class*="phone"]',
            '[class*="tel"]',
            '[data-spm*="phone"]',
        )
        selector_text: dict[str, list[str]] = {}
        for selector in selectors:
            values = [
                text.strip()
                for text in page.locator(selector).all_inner_texts()
                if text.strip()
            ]
            if values:
                selector_text[selector] = values[:20]
        print(json.dumps({
            'title': page.title(),
            'url': page.url,
            'body_text': body_text[:12_000],
            'selector_text': selector_text,
        }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
