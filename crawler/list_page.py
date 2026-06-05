import asyncio
import json
import re
from urllib.parse import urlencode, unquote
from pathlib import Path

from config import BROWSER_CONFIG, PATHS, SEARCH_CONFIG
from crawler.anti_detect import human_like_read_pause, human_like_scroll
from bs4 import BeautifulSoup


class ListPageBlockedError(RuntimeError):
    pass


def build_search_url(keyword: str, page_no: int) -> str:
    params = {
        "city": SEARCH_CONFIG["city_code"],
        "dq": SEARCH_CONFIG["dq_code"],
        "pubTime": SEARCH_CONFIG["pub_time"],
        "currentPage": page_no,
        "pageSize": SEARCH_CONFIG["page_size"],
        "key": keyword,
        "suggestTag": "",
        "workYearCode": SEARCH_CONFIG["work_year_code"],
        "compId": "",
        "compName": "",
        "compTag": "",
        "industry": SEARCH_CONFIG["industry"],
        "salaryCode": SEARCH_CONFIG["salary_code"],
        "jobKind": SEARCH_CONFIG["job_kind"],
        "compScale": SEARCH_CONFIG["comp_scale"],
        "compKind": SEARCH_CONFIG["comp_kind"],
        "compStage": SEARCH_CONFIG["comp_stage"],
        "eduLevel": SEARCH_CONFIG["edu_level"],
        "otherCity": SEARCH_CONFIG["other_city"],
        "sfrom": SEARCH_CONFIG["sfrom"],
        "scene": SEARCH_CONFIG["scene"],
    }
    return f"https://www.liepin.com/zhaopin/?{urlencode(params)}"


def _extract_job_ids_from_html(html: str) -> list[str]:
    patterns = [
        r"/a/(\d+)\.shtml",
        r'"jobId"\s*:\s*"(\d+)"',
        r'"jobId"\s*:\s*(\d+)',
    ]

    job_ids: list[str] = []
    for pattern in patterns:
        for job_id in re.findall(pattern, html):
            if job_id not in job_ids:
                job_ids.append(job_id)
    return job_ids


def _extract_job_ids_from_cards(html: str) -> list[str]:
    job_cards = _extract_job_cards_from_html(html)
    return [card["job_id"] for card in job_cards]


def _extract_job_cards_from_html(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    job_cards: list[dict[str, str]] = []
    seen_job_ids: set[str] = set()

    for card in soup.select("div.job-card-pc-container"):
        style = " ".join(str(card.get("style") or "").lower().split())
        if "display:none" in style or 'display: none' in style:
            continue

        anchor = card.select_one('a[data-nick="job-detail-job-info"]')
        if not anchor:
            continue

        href = (anchor.get("href") or "").strip()
        if not href:
            continue

        ext = card.attrs.get("data-tlg-ext")
        if not ext:
            continue

        decoded = unquote(ext)
        match = re.search(r'"jobId"\s*:\s*"(\d+)"', decoded)
        if match:
            job_id = match.group(1)
            if job_id not in seen_job_ids:
                seen_job_ids.add(job_id)
                job_cards.append({"job_id": job_id, "detail_url": href})
            continue

        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            job_id = str(payload.get("jobId") or "").strip()
            if job_id and job_id not in seen_job_ids:
                seen_job_ids.add(job_id)
                job_cards.append({"job_id": job_id, "detail_url": href})

    return job_cards


def _debug_path(keyword: str, page_no: int) -> Path:
    safe_keyword = re.sub(r"[^a-zA-Z0-9_%\-]", "_", keyword)
    PATHS["debug"].mkdir(parents=True, exist_ok=True)
    return PATHS["debug"] / f"list_{safe_keyword}_{page_no}.html"


async def open_search_page(page, keyword: str, page_no: int) -> str:
    url = build_search_url(keyword, page_no)
    await page.goto(
        url,
        wait_until="networkidle",
        timeout=BROWSER_CONFIG["goto_timeout_ms"],
    )
    await human_like_scroll(page)
    html = await page.content()
    page_title = await page.title()

    if "\u9a8c\u8bc1\u7801" in page_title or "\u5b89\u5168\u4e2d\u5fc3" in page_title:
        raise ListPageBlockedError("list page was replaced by captcha")

    if "\u767b\u5f55" in page_title and "/user/login" in page.url:
        raise ListPageBlockedError("list page was redirected to login")

    return html


async def scrape_list_page(page, keyword: str, page_no: int) -> list[str]:
    html = await open_search_page(page, keyword, page_no)

    card_job_ids = _extract_job_ids_from_cards(html)
    if card_job_ids:
        return card_job_ids

    html_job_ids = _extract_job_ids_from_html(html)
    if html_job_ids:
        return html_job_ids

    debug_file = _debug_path(keyword, page_no)
    debug_file.write_text(html, encoding="utf-8")
    return []


async def scrape_list_job_cards(page, keyword: str, page_no: int) -> list[dict[str, str]]:
    html = await open_search_page(page, keyword, page_no)

    job_cards = _extract_job_cards_from_html(html)
    if job_cards:
        return job_cards

    html_job_ids = _extract_job_ids_from_html(html)
    if html_job_ids:
        return [
            {
                "job_id": job_id,
                "detail_url": f"https://www.liepin.com/a/{job_id}.shtml",
            }
            for job_id in html_job_ids
        ]

    debug_file = _debug_path(keyword, page_no)
    debug_file.write_text(html, encoding="utf-8")
    return []


async def open_detail_from_search(page, job_id: str) -> bool:
    selector = f"a[href*='/a/{job_id}']"
    link = page.locator(selector).first
    if await link.count() == 0:
        return False

    await link.scroll_into_view_if_needed(timeout=BROWSER_CONFIG["goto_timeout_ms"])
    await human_like_read_pause(page, min_pause=0.5, max_pause=1.3)
    await link.hover()
    await asyncio.sleep(0.3)
    await link.click(timeout=BROWSER_CONFIG["goto_timeout_ms"])
    await page.wait_for_load_state("networkidle", timeout=BROWSER_CONFIG["goto_timeout_ms"])
    await human_like_scroll(page)
    return True
