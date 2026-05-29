import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from config import BROWSER_CONFIG, PATHS
from crawler.anti_detect import human_like_page_settle, human_like_read_pause, human_like_scroll


class DetailPageBlockedError(RuntimeError):
    pass


class DetailPageMismatchError(RuntimeError):
    pass


def _detail_debug_path(keyword: str, job_id: str, stage: str) -> Path:
    safe_keyword = re.sub(r"[^a-zA-Z0-9_%\-]", "_", keyword)
    safe_job_id = re.sub(r"[^0-9A-Za-z_\-]", "_", job_id)
    PATHS["debug"].mkdir(parents=True, exist_ok=True)
    return PATHS["debug"] / f"detail_{safe_keyword}_{safe_job_id}_{stage}.html"


def write_detail_debug_html(keyword: str, job_id: str, stage: str, html: str) -> Path:
    debug_file = _detail_debug_path(keyword, job_id, stage)
    debug_file.write_text(html, encoding="utf-8")
    return debug_file


def _iter_job_postings(payload: Any):
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_job_postings(item)
        return

    if not isinstance(payload, dict):
        return

    if payload.get("@type") == "JobPosting":
        yield payload

    graph = payload.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            yield from _iter_job_postings(item)


def _load_json_safely(raw_text: str) -> Any:
    # Some ld+json blocks contain raw newlines inside quoted strings,
    # which is invalid JSON but still semantically recoverable.
    # Some pages also include bare backslashes like "C\C++\Python",
    # which need to be escaped before json.loads().
    cleaned: list[str] = []
    in_string = False
    index = 0

    while index < len(raw_text):
        char = raw_text[index]

        if char == '"':
            if in_string:
                next_non_whitespace = index + 1
                while next_non_whitespace < len(raw_text) and raw_text[next_non_whitespace] in {" ", "\n", "\r", "\t"}:
                    next_non_whitespace += 1
                if next_non_whitespace < len(raw_text):
                    next_char = raw_text[next_non_whitespace]
                    if next_char not in {",", "}", "]", ":"}:
                        cleaned.append('\\"')
                        index += 1
                        continue
            cleaned.append(char)
            in_string = not in_string
            index += 1
            continue

        if in_string:
            if char == "\\":
                next_char = raw_text[index + 1] if index + 1 < len(raw_text) else ""
                if next_char in {'"', "\\", "/", "b", "f", "n", "r", "t"}:
                    cleaned.append(char)
                    cleaned.append(next_char)
                    index += 2
                    continue
                if next_char == "u" and index + 5 < len(raw_text):
                    cleaned.append(char)
                    cleaned.append(next_char)
                    index += 2
                    continue
                cleaned.append("\\\\")
                index += 1
                continue
            if char == "\n":
                cleaned.append("\\n")
                index += 1
                continue
            if char == "\r":
                cleaned.append("\\r")
                index += 1
                continue
            if char == "\t":
                cleaned.append("\\t")
                index += 1
                continue
            if ord(char) < 0x20:
                cleaned.append(" ")
                index += 1
                continue
            cleaned.append(char)
            index += 1
            continue

        if ord(char) < 0x20 and char not in {"\n", "\r", "\t"}:
            cleaned.append(" ")
            index += 1
            continue

        cleaned.append(char)
        index += 1

    return json.loads("".join(cleaned))


def _contains_job_posting_marker(raw_text: str) -> bool:
    return '"@type"' in raw_text and '"JobPosting"' in raw_text


def _parse_salary(text: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    if not text:
        return None, None, None

    monthly_match = re.search(r"(\d+)-(\d+)k", text, re.IGNORECASE)
    months_match = re.search(r"(\d{2})(?:\u85aa|months?)", text, re.IGNORECASE)

    salary_min = int(monthly_match.group(1)) * 1000 if monthly_match else None
    salary_max = int(monthly_match.group(2)) * 1000 if monthly_match else None
    salary_months = int(months_match.group(1)) if months_match else None
    return salary_min, salary_max, salary_months


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_normalize_text(item) for item in value if item)
    return ""


def _normalize_job_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return title

    match = re.search(r"^\u3010\S+\s+(.+?)\u62db\u8058\u3011", title)
    if match:
        return match.group(1).strip()

    cleaned = re.sub(r"\s*-\s*\u730e\u8058.*$", "", title).strip()
    cleaned = re.sub(r"^\u3010[^\u3011]*\u3011", "", cleaned).strip()
    return cleaned or title


def _extract_job_properties_last_updated(soup: BeautifulSoup) -> Optional[str]:
    node = soup.select_one(".job-properties")
    if not node:
        return None

    text = node.get_text(" ", strip=True)
    month_day_match = re.search(r"(\d{1,2})月(\d{1,2})日更新", text)
    if not month_day_match:
        return None

    today = date.today()
    month = int(month_day_match.group(1))
    day = int(month_day_match.group(2))
    return f"{today.year:04d}-{month:02d}-{day:02d}"


def _expected_detail_url(job_id: str) -> str:
    return f"https://www.liepin.com/a/{job_id}.shtml"


def _normalized_url_path(url: Optional[str]) -> str:
    if not url:
        return ""
    return urlsplit(url).path.rstrip("/")


def _is_expected_detail_url(url: Optional[str], expected_detail_url: str) -> bool:
    if not url or not expected_detail_url:
        return False
    return _normalized_url_path(url) == _normalized_url_path(expected_detail_url)


def extract_from_ld_json(data: dict[str, Any]) -> dict[str, Any]:
    description = _normalize_text(data.get("description"))
    salary = data.get("baseSalary", {})
    salary_text = None

    if isinstance(salary, dict):
        salary_value = salary.get("value")
        if isinstance(salary_value, dict):
            salary_text = salary_value.get("name")
        else:
            salary_text = salary.get("name")

    hiring_org = data.get("hiringOrganization") or {}
    job_location = data.get("jobLocation") or {}
    address = {}

    if isinstance(job_location, dict):
        address = job_location.get("address") or {}
    elif isinstance(job_location, list) and job_location:
        first_location = job_location[0]
        if isinstance(first_location, dict):
            address = first_location.get("address") or {}

    salary_min, salary_max, salary_months = _parse_salary(salary_text)

    return {
        "title": _normalize_job_title(data.get("title")),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_months": salary_months,
        "city": address.get("addressLocality"),
        "exp_years": data.get("experienceRequirements"),
        "education": data.get("educationRequirements"),
        "date_posted": data.get("datePosted"),
        "last_updated": data.get("validThrough") or data.get("datePosted"),
        "company_name": hiring_org.get("name"),
        "company_verified": bool(hiring_org.get("sameAs")),
        "company_logo_exists": bool(hiring_org.get("logo")),
        "publisher_type": "unknown",
        "jd_text": description,
        "jd_length": len(description),
        "benefits": data.get("jobBenefits") or [],
    }


def extract_from_generic_ld_json(data: dict[str, Any]) -> dict[str, Any]:
    description = _normalize_text(data.get("description"))
    title = data.get("title")
    date_posted = data.get("pubDate")
    last_updated = data.get("upDate")

    if isinstance(date_posted, str):
        date_posted = date_posted[:10]
    if isinstance(last_updated, str):
        last_updated = last_updated[:10]

    salary_min = salary_max = None
    salary_match = re.search(r"\u85aa\u8d44(\d+)-(\d+)k", description, re.IGNORECASE)
    if salary_match:
        salary_min = int(salary_match.group(1)) * 1000
        salary_max = int(salary_match.group(2)) * 1000

    return {
        "title": _normalize_job_title(title),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_months": None,
        "date_posted": date_posted,
        "last_updated": last_updated,
        "jd_text": description,
        "jd_length": len(description),
    }


def parse_detail_page(
    html: str,
    job_id: str,
    detail_url: str,
    keyword: str,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    page_title = soup.title.get_text(strip=True) if soup.title else ""
    found_job_posting = False
    found_job_posting_marker = False

    if "\u9a8c\u8bc1\u7801" in page_title or "\u5b89\u5168\u4e2d\u5fc3" in page_title:
        raise DetailPageBlockedError("detail page was replaced by captcha")

    job: dict[str, Any] = {
        "job_id": job_id,
        "detail_url": detail_url,
        "keyword": keyword,
        "raw_html": html,
    }

    for tag in soup.find_all("script", type="application/ld+json"):
        raw_ld_json = tag.get_text()
        if _contains_job_posting_marker(raw_ld_json):
            found_job_posting_marker = True
        try:
            payload = _load_json_safely(raw_ld_json)
        except (json.JSONDecodeError, TypeError):
            continue

        for posting in _iter_job_postings(payload):
            found_job_posting = True
            job.update(extract_from_ld_json(posting))
            break

        if job.get("title"):
            break

    # Prefer the inline job-properties update date because it more closely
    # matches the visible listing freshness signal than the generic page-level
    # time-factor block.
    properties_last_updated = _extract_job_properties_last_updated(soup)
    if properties_last_updated:
        job["last_updated"] = properties_last_updated

    time_factor = soup.select_one(".time-factor-wrap")
    if time_factor and not job.get("last_updated"):
        match = re.search(r"\d{4}-\d{2}-\d{2}", time_factor.get_text(" ", strip=True))
        if match:
            job["last_updated"] = match.group()

    if not job.get("title") and page_title:
        clean_title = _normalize_job_title(page_title)
        if clean_title:
            job["title"] = clean_title

    publisher_text = soup.get_text(" ", strip=True).lower()
    if "\u730e\u5934" in publisher_text or "headhunter" in publisher_text:
        job["publisher_type"] = "headhunter"
    elif "hr" in publisher_text:
        job["publisher_type"] = "hr_direct"

    if job.get("last_updated"):
        delta = date.today() - date.fromisoformat(job["last_updated"])
        job["days_since_update"] = delta.days

    if not job.get("jd_length") and job.get("jd_text"):
        job["jd_length"] = len(job["jd_text"])

    if not found_job_posting:
        if found_job_posting_marker:
            raise ValueError("detail page contains JobPosting ld+json but it could not be parsed")
        raise DetailPageMismatchError("detail page is not a job posting page")

    if not job.get("title"):
        raise ValueError("detail page parsed but title is still missing")

    return job


async def parse_current_detail_page(
    page,
    job_id: str,
    keyword: str,
    detail_url: str,
) -> dict[str, Any]:
    await human_like_page_settle(page)
    await human_like_read_pause(page)
    await human_like_scroll(page)
    html = await page.content()
    if not _is_expected_detail_url(page.url, detail_url):
        write_detail_debug_html(keyword, job_id, "wrong_page", html)
        raise DetailPageMismatchError(
            f"detail page landed on unexpected url: {page.url}"
        )
    try:
        return parse_detail_page(
            html=html,
            job_id=job_id,
            detail_url=detail_url,
            keyword=keyword,
        )
    except DetailPageBlockedError:
        write_detail_debug_html(keyword, job_id, "blocked", html)
        raise
    except Exception:
        write_detail_debug_html(keyword, job_id, "parse_failed", html)
        raise


async def fetch_detail_page(
    page,
    job_id: str,
    keyword: str,
    detail_url: str,
    *,
    referer: Optional[str] = None,
) -> dict[str, Any]:
    goto_kwargs = {
        "wait_until": "networkidle",
        "timeout": BROWSER_CONFIG["goto_timeout_ms"],
    }
    if referer:
        goto_kwargs["referer"] = referer

    await page.goto(detail_url, **goto_kwargs)
    return await parse_current_detail_page(page, job_id, keyword, detail_url)
