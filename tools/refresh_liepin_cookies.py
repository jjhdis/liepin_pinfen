import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BASE_DIR / "cookies.json"
DEFAULT_HOME_URL = "https://www.liepin.com/"
DEFAULT_VERIFY_URL = (
    "https://www.liepin.com/zhaopin/"
    "?city=020&dq=020&currentPage=0&pageSize=40&key=python"
    "&workYearCode=0&sfrom=search_job_pc&scene=input"
)

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Semi-automatic Liepin login helper that exports cookies.json."
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output cookie file path. Default: project_root/cookies.json",
    )
    parser.add_argument(
        "--home-url",
        default=DEFAULT_HOME_URL,
        help="Entry page to open before manual login.",
    )
    parser.add_argument(
        "--verify-url",
        default=DEFAULT_VERIFY_URL,
        help="Page used for best-effort post-login verification.",
    )
    parser.add_argument(
        "--phone",
        help="Optional phone number. The script will try a best-effort auto-fill.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Navigation timeout in milliseconds. Default: 30000",
    )
    return parser.parse_args()


def _try_click_login_entry(page) -> None:
    selectors = [
        'a[href*="login"]',
        'button:has-text("登录")',
        'a:has-text("登录")',
        'button:has-text("注册")',
        'a:has-text("注册")',
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.click(timeout=2000)
            return
        except Exception:
            continue


def _try_fill_phone(page, phone: str) -> bool:
    selectors = [
        'input[type="tel"]',
        'input[name*="phone"]',
        'input[placeholder*="手机号"]',
        'input[placeholder*="手机号码"]',
        'input[data-nick*="phone"]',
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.fill(phone, timeout=2000)
            return True
        except Exception:
            continue
    return False


def _looks_like_login_intercept(url: str, title: str, body_text: str) -> bool:
    lowered_url = (url or "").lower()
    lowered_title = (title or "").lower()
    if "login" in lowered_url or "passport" in lowered_url:
        return True
    if "登录" in title or "注册" in title:
        return True
    return any(
        marker in body_text
        for marker in (
            "立即登录",
            "请先登录",
            "登录后查看",
            "验证码登录",
        )
    )


def _filter_liepin_cookies(cookies: list[dict]) -> list[dict]:
    return [
        item
        for item in cookies
        if "liepin.com" in str(item.get("domain", ""))
    ]


def _save_cookies(output_path: Path, cookies: list[dict]) -> None:
    output_path.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 900},
        )
        context.add_init_script(STEALTH_INIT_SCRIPT)
        page = context.new_page()
        page.set_default_timeout(args.timeout_ms)

        try:
            page.goto(args.home_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            print(f"[cookie-refresh] open entry timeout: {args.home_url}")

        _try_click_login_entry(page)
        if args.phone:
            filled = _try_fill_phone(page, args.phone)
            print(f"[cookie-refresh] phone_autofill={'ok' if filled else 'skip'}")

        print("[cookie-refresh] browser opened for manual login")
        print("[cookie-refresh] complete login in the browser, then return here and press Enter")
        input()

        cookies = _filter_liepin_cookies(context.cookies())
        if not cookies:
            print("[cookie-refresh] no liepin cookies found, nothing was written")
            browser.close()
            raise SystemExit(1)

        _save_cookies(output_path, cookies)
        print(f"[cookie-refresh] wrote {len(cookies)} cookies to {output_path}")

        verify_page = context.new_page()
        verify_page.set_default_timeout(args.timeout_ms)
        verify_url = args.verify_url
        title = ""
        current_url = ""
        body_text = ""
        try:
            verify_page.goto(verify_url, wait_until="domcontentloaded")
            current_url = verify_page.url
            title = verify_page.title()
            body_text = verify_page.locator("body").inner_text(timeout=2000)
        except Exception as exc:
            print(f"[cookie-refresh] verify_open_failed error={exc}")
        finally:
            try:
                verify_page.close()
            except Exception:
                pass

        intercepted = _looks_like_login_intercept(current_url, title, body_text)
        print(
            f"[cookie-refresh-verify] intercepted={int(intercepted)} "
            f"url={current_url or verify_url} title={title or 'N/A'}"
        )
        print("[cookie-refresh] done")
        browser.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
