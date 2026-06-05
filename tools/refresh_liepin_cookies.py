import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import LIEPIN_MESSAGE_CONFIG

DEFAULT_OUTPUT_DIR = BASE_DIR / "cookies"
DEFAULT_HOME_URL = "https://www.liepin.com/"
DEFAULT_MESSAGE_HOME_URL = "https://c.liepin.com/"
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
        description="Semi-automatic Liepin login helper that exports a named Liepin cookie JSON file."
    )
    parser.add_argument(
        "--output",
        help="Output cookie file path. Overrides the auto-generated filename.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory used for auto-generated cookie files. Default: project_root/cookies",
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
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-detect login completion instead of waiting for terminal Enter.",
    )
    return parser.parse_args()


def _sanitize_phone_for_filename(phone: Optional[str]) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits or "unknown"


def _build_default_output_path(output_dir: str, phone: Optional[str]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    phone_tag = _sanitize_phone_for_filename(phone)
    filename = f"cookie_{timestamp}_{phone_tag}_liepin.json"
    return Path(output_dir) / filename


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


def _build_message_context_path(cookie_path: Path) -> Path:
    return cookie_path.with_name(f"{cookie_path.stem}_message_context.json")


def _build_message_context(page, *, cookie_path: Path) -> dict:
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    current_url = page.url or DEFAULT_MESSAGE_HOME_URL
    try:
        navigator_info = page.evaluate(
            """() => ({
                userAgent: navigator.userAgent || '',
                languages: Array.isArray(navigator.languages) ? navigator.languages : [],
                platform: navigator.platform || '',
                brands: navigator.userAgentData?.brands || [],
                mobile: navigator.userAgentData?.mobile ?? false,
            })"""
        )
    except Exception:
        navigator_info = {}

    accept_language = LIEPIN_MESSAGE_CONFIG["accept_language"]
    languages = navigator_info.get("languages") or []
    if languages:
        primary = str(languages[0]).strip()
        if primary:
            accept_language = primary

    sec_ch_ua = LIEPIN_MESSAGE_CONFIG["sec_ch_ua"]
    brands = navigator_info.get("brands") or []
    if isinstance(brands, list) and brands:
        sec_ch_ua = ", ".join(
            f'"{str(item.get("brand") or "").replace(chr(34), "")}";v="{str(item.get("version") or "")}"'
            for item in brands
            if str(item.get("brand") or "").strip()
        ) or sec_ch_ua

    sec_ch_ua_mobile = "?1" if navigator_info.get("mobile") else "?0"
    platform = str(navigator_info.get("platform") or "").strip()
    sec_ch_ua_platform = f'"{platform}"' if platform else LIEPIN_MESSAGE_CONFIG["sec_ch_ua_platform"]

    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "cookie_file": cookie_path.name,
        "origin": LIEPIN_MESSAGE_CONFIG["origin"],
        "referer": LIEPIN_MESSAGE_CONFIG["referer"],
        "accept": LIEPIN_MESSAGE_CONFIG["accept"],
        "accept_language": accept_language,
        "content_type": LIEPIN_MESSAGE_CONFIG["content_type"],
        "user_agent": str(navigator_info.get("userAgent") or LIEPIN_MESSAGE_CONFIG["user_agent"]),
        "sec_ch_ua": sec_ch_ua,
        "sec_ch_ua_mobile": sec_ch_ua_mobile,
        "sec_ch_ua_platform": sec_ch_ua_platform,
        "sec_fetch_dest": LIEPIN_MESSAGE_CONFIG["sec_fetch_dest"],
        "sec_fetch_mode": LIEPIN_MESSAGE_CONFIG["sec_fetch_mode"],
        "sec_fetch_site": LIEPIN_MESSAGE_CONFIG["sec_fetch_site"],
        "x_client_type": LIEPIN_MESSAGE_CONFIG["x_client_type"],
        "x_fscp_fe_version": LIEPIN_MESSAGE_CONFIG["x_fscp_fe_version"],
        "x_fscp_std_info": LIEPIN_MESSAGE_CONFIG["x_fscp_std_info"],
        "x_fscp_version": LIEPIN_MESSAGE_CONFIG["x_fscp_version"],
        "x_fscp_trace_id_example": str(uuid.uuid4()),
        "x_fscp_bi_stat_location": f"{current_url.split('#', 1)[0].split('?', 1)[0]}?time={now_ms}",
    }


def _save_message_context(context_path: Path, payload: dict) -> None:
    context_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# Cookie names that only appear after successful login
_AUTH_COOKIE_NAMES = {"user_name", "lt_auth", "c_flag", "user_photo"}


def _has_auth_cookies(context) -> bool:
    """Check if any auth-indicating cookies are present."""
    names = {c.get("name", "") for c in context.cookies()}
    found = names & _AUTH_COOKIE_NAMES
    return bool(found)


def _wait_for_login(context, max_wait: int = 300) -> bool:
    """Wait for auth cookies to appear after the user completes login."""
    print(
        "[cookie-refresh-auto] browser opened — complete login in the browser"
    )
    print(
        f"[cookie-refresh-auto] waiting for auth cookies "
        f"(polling every 3s, max {max_wait}s)..."
    )
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(3)
        if _has_auth_cookies(context):
            print("[cookie-refresh-auto] auth cookies detected, login ok")
            return True
        print("[cookie-refresh-auto] no auth cookies yet...")
    print("[cookie-refresh-auto] timeout waiting for login")
    return False


def main() -> None:
    args = parse_args()
    output_path = Path(args.output) if args.output else _build_default_output_path(args.output_dir, args.phone)
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

        if args.auto:
            if not _wait_for_login(context):
                print("[cookie-refresh] timeout, closing browser")
                browser.close()
                raise SystemExit(1)
        else:
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

        message_page = context.new_page()
        message_page.set_default_timeout(args.timeout_ms)
        message_context_path = _build_message_context_path(output_path)
        try:
            message_page.goto(DEFAULT_MESSAGE_HOME_URL, wait_until="domcontentloaded")
            message_context = _build_message_context(message_page, cookie_path=output_path)
            _save_message_context(message_context_path, message_context)
            print(f"[cookie-refresh] wrote message context to {message_context_path}")
        except Exception as exc:
            print(f"[cookie-refresh] message_context_failed error={exc}")
        finally:
            try:
                message_page.close()
            except Exception:
                pass

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
