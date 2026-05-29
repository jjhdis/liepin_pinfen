import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from config import PATHS, ZHIHU_CONFIG

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - handled at runtime for missing dependency
    curl_requests = None


class ZhihuClientError(RuntimeError):
    pass


class ZhihuHTTPError(ZhihuClientError):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        debug_path: Optional[Path] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.debug_path = debug_path


REQUIRED_COOKIE_KEYS = ("z_c0", "_xsrf")
OPTIONAL_COOKIE_KEYS = ("_zap", "tst")


def _load_zhihu_cookies(path: Optional[Path] = None) -> dict[str, str]:
    cookie_path = path or PATHS["zhihu_cookies"]
    if not cookie_path.exists():
        raise ZhihuClientError(
            f"Zhihu cookies file not found: {cookie_path}. "
            "Export zhihu_cookies.json before running company_enrich.py."
        )

    with cookie_path.open("r", encoding="utf-8") as fh:
        cookies = json.load(fh)

    if not isinstance(cookies, dict):
        raise ZhihuClientError("zhihu_cookies.json must be a JSON object.")

    missing = [key for key in REQUIRED_COOKIE_KEYS if not cookies.get(key)]
    if missing:
        raise ZhihuClientError(
            f"zhihu_cookies.json is missing required keys: {', '.join(missing)}"
        )
    normalized: dict[str, str] = {}
    for key in (*REQUIRED_COOKIE_KEYS, *OPTIONAL_COOKIE_KEYS):
        value = cookies.get(key)
        if value:
            normalized[str(key)] = str(value)
    for key, value in cookies.items():
        if key not in normalized and value:
            normalized[str(key)] = str(value)
    return normalized


def _build_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" for key, value in cookies.items() if value)


def _sleep_random(delay_min: float, delay_max: float) -> float:
    import random

    delay = random.uniform(delay_min, delay_max)
    time.sleep(delay)
    return delay


class ZhihuSearchClient:
    def __init__(self) -> None:
        if curl_requests is None:
            raise ZhihuClientError(
                "curl_cffi is not installed. Install project dependencies first."
            )

        self.cookies = _load_zhihu_cookies()
        self.session = curl_requests.Session()
        self.session.headers.update(
            {
                "User-Agent": ZHIHU_CONFIG["user_agent"],
                "Accept": "*/*",
                "Accept-Language": ZHIHU_CONFIG["accept_language"],
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "x-requested-with": "fetch",
                "x-zse-93": ZHIHU_CONFIG["x_zse_93"],
                "x-zse-96": ZHIHU_CONFIG["x_zse_96"],
                "x-api-version": ZHIHU_CONFIG["x_api_version"],
                "x-app-za": ZHIHU_CONFIG["x_app_za"],
                "sec-ch-ua": ZHIHU_CONFIG["sec_ch_ua"],
                "sec-ch-ua-mobile": ZHIHU_CONFIG["sec_ch_ua_mobile"],
                "sec-ch-ua-platform": ZHIHU_CONFIG["sec_ch_ua_platform"],
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
        )
        for name, value in self.cookies.items():
            self.session.cookies.set(name, value, domain=".zhihu.com")
        self.session.headers["Cookie"] = _build_cookie_header(self.cookies)
        self.request_count = 0

    def search_company(self, company_name: str) -> list[dict[str, Any]]:
        if self.request_count >= ZHIHU_CONFIG["max_requests_per_run"]:
            raise ZhihuClientError(
                f"Max Zhihu requests per run reached: {ZHIHU_CONFIG['max_requests_per_run']}"
            )

        query = company_name.strip()
        referer = (
            f"{ZHIHU_CONFIG['base_url']}/search?q={quote(query)}&type=content"
        )
        params = dict(ZHIHU_CONFIG["search_params"])
        params["q"] = query
        response = self.session.get(
            ZHIHU_CONFIG["search_api"],
            params=params,
            headers={
                "Referer": referer,
                "Origin": ZHIHU_CONFIG["base_url"],
            },
            impersonate="chrome124",
            timeout=30,
        )
        self.request_count += 1
        self._raise_for_status(response)

        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ZhihuClientError("Zhihu search response missing data list.")

        items: list[dict[str, Any]] = []
        for item in data:
            normalized = self._normalize_search_item(item)
            if normalized:
                items.append(normalized)
            if len(items) >= ZHIHU_CONFIG["summary_top_n"]:
                break

        _sleep_random(
            ZHIHU_CONFIG["search_delay_min"],
            ZHIHU_CONFIG["search_delay_max"],
        )
        return items

    def _raise_for_status(self, response: Any) -> None:
        status_code = int(response.status_code)
        if status_code == 200:
            return
        debug_path = self._write_debug_response(response)
        if status_code == 401:
            raise ZhihuHTTPError(
                status_code,
                "Zhihu cookie expired or unauthorized.",
                debug_path=debug_path,
            )
        if status_code == 403:
            raise ZhihuHTTPError(
                status_code,
                "Zhihu rejected the request.",
                debug_path=debug_path,
            )
        if status_code == 429:
            raise ZhihuHTTPError(
                status_code,
                "Zhihu rate limit triggered.",
                debug_path=debug_path,
            )
        if status_code == 521:
            raise ZhihuHTTPError(
                status_code,
                "Zhihu requires manual verification.",
                debug_path=debug_path,
            )
        raise ZhihuHTTPError(
            status_code,
            f"Unexpected Zhihu HTTP status: {status_code}",
            debug_path=debug_path,
        )

    def _write_debug_response(self, response: Any) -> Path:
        PATHS["debug"].mkdir(parents=True, exist_ok=True)
        now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        path = PATHS["debug"] / f"zhihu_http_{response.status_code}_{now}.txt"
        request_headers = {}
        request_url = ""
        request_method = ""
        if getattr(response, "request", None) is not None:
            request_headers = dict(getattr(response.request, "headers", {}) or {})
            request_url = str(getattr(response.request, "url", "") or "")
            request_method = str(getattr(response.request, "method", "") or "")
        response_headers = dict(getattr(response, "headers", {}) or {})
        response_text = getattr(response, "text", "")
        content = {
            "request": {
                "method": request_method,
                "url": request_url,
                "headers": request_headers,
            },
            "response": {
                "status_code": int(response.status_code),
                "headers": response_headers,
                "text": response_text,
            },
        }
        path.write_text(
            json.dumps(content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _normalize_search_item(self, item: dict[str, Any]) -> Optional[dict[str, Any]]:
        item_type = item.get("type")
        obj = item.get("object") or {}
        if not isinstance(obj, dict):
            return None
        object_type = obj.get("type") if item_type == "search_result" else item_type
        if object_type not in {"answer", "article", "question"}:
            return None

        title = _clean_text(
            obj.get("title")
            or (obj.get("question") or {}).get("name")
            or obj.get("name")
            or ""
        )
        excerpt = _clean_text(obj.get("excerpt") or "")
        target_id = str(obj.get("id") or "")
        url = obj.get("url") or obj.get("url_token") or ""
        if not title and not excerpt:
            return None
        return {
            "type": str(object_type),
            "id": target_id,
            "title": title,
            "excerpt": excerpt,
            "url": str(url),
        }


def _clean_text(value: str) -> str:
    text = " ".join(str(value).split())
    return text.strip()
