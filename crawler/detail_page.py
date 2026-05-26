import json
import re
from datetime import date
from typing import Any, Optional, Tuple

from bs4 import BeautifulSoup

from config import BROWSER_CONFIG


class DetailPageBlockedError(RuntimeError):
    pass


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
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw_text)
    return json.loads(cleaned)


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

    if "\u9a8c\u8bc1\u7801" in page_title or "\u5b89\u5168\u4e2d\u5fc3" in page_title:
        raise DetailPageBlockedError("detail page was replaced by captcha")

    job: dict[str, Any] = {
        "job_id": job_id,
        "detail_url": detail_url,
        "keyword": keyword,
        "raw_html": html,
    }

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            payload = _load_json_safely(tag.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        for posting in _iter_job_postings(payload):
            job.update(extract_from_ld_json(posting))
            break

        if job.get("title"):
            break

        if isinstance(payload, dict) and payload.get("title"):
            job.update(extract_from_generic_ld_json(payload))

    time_factor = soup.select_one(".time-factor-wrap")
    if time_factor:
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

    if not job.get("title"):
        raise ValueError("detail page parsed but title is still missing")

    return job


async def fetch_detail_page(page, job_id: str, keyword: str) -> dict[str, Any]:
    detail_url = f"https://www.liepin.com/a/{job_id}.shtml"
    await page.goto(
        detail_url,
        wait_until="networkidle",
        timeout=BROWSER_CONFIG["goto_timeout_ms"],
    )
    html = await page.content()
    return parse_detail_page(
        html=html,
        job_id=job_id,
        detail_url=detail_url,
        keyword=keyword,
    )
