import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

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


def resolve_cookie_path(cookie_file: Optional[str] = None) -> Path:
    if not cookie_file:
        return PATHS["cookies"]

    raw_path = Path(cookie_file)
    candidates: list[Path] = []

    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.extend(
            [
                raw_path,
                PATHS["cookie_dir"] / raw_path.name,
                PATHS["cookies"].parent / raw_path,
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate

    if raw_path.is_absolute():
        return raw_path

    if raw_path.parent == Path("."):
        return PATHS["cookie_dir"] / raw_path.name

    return PATHS["cookies"].parent / raw_path


def _load_cookies(cookie_path: Path) -> list[dict]:
    if not cookie_path.exists():
        return []

    with cookie_path.open("r", encoding="utf-8") as fh:
        cookies = json.load(fh)

    if not isinstance(cookies, list):
        raise ValueError(f"{cookie_path.name} must be a list of cookie dicts.")

    return cookies


@asynccontextmanager
async def open_browser(cookie_file: Optional[str] = None):
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

        cookie_path = resolve_cookie_path(cookie_file)
        cookies = _load_cookies(cookie_path)
        if cookies:
            await context.add_cookies(cookies)

        try:
            yield browser, context
        finally:
            await context.close()
            await browser.close()
