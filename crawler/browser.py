import json
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright

from config import BROWSER_CONFIG, PATHS
from crawler.anti_detect import get_user_agent


STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined
});

Object.defineProperty(navigator, 'languages', {
  get: () => ['zh-CN', 'zh', 'en-US', 'en']
});

Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5]
});

window.chrome = window.chrome || {
  runtime: {}
};
"""


def _load_cookies() -> list[dict]:
    if not PATHS["cookies"].exists():
        return []

    with PATHS["cookies"].open("r", encoding="utf-8") as fh:
        cookies = json.load(fh)

    if not isinstance(cookies, list):
        raise ValueError("cookies.json must be a list of cookie dicts.")

    return cookies


@asynccontextmanager
async def open_browser():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=BROWSER_CONFIG["headless"]
        )
        context = await browser.new_context(
            user_agent=get_user_agent(),
            locale=BROWSER_CONFIG["locale"],
            timezone_id=BROWSER_CONFIG["timezone_id"],
            viewport=BROWSER_CONFIG["viewport"],
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)

        cookies = _load_cookies()
        if cookies:
            await context.add_cookies(cookies)

        try:
            yield browser, context
        finally:
            await context.close()
            await browser.close()
