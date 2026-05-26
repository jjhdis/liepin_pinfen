import re
from pathlib import Path

from config import BROWSER_CONFIG, PATHS, SEARCH_CONFIG
from crawler.anti_detect import human_like_scroll


class ListPageBlockedError(RuntimeError):
    pass


def build_search_url(keyword: str, page_no: int) -> str:
    return (
        "https://www.liepin.com/zhaopin/"
        f"?key={keyword}&city={SEARCH_CONFIG['city_code']}&pageNo={page_no}"
    )


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


def _debug_path(keyword: str, page_no: int) -> Path:
    safe_keyword = re.sub(r"[^a-zA-Z0-9_%\-]", "_", keyword)
    PATHS["debug"].mkdir(parents=True, exist_ok=True)
    return PATHS["debug"] / f"list_{safe_keyword}_{page_no}.html"


async def scrape_list_page(page, keyword: str, page_no: int) -> list[str]:
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

    links = await page.query_selector_all("a[href*='/a/']")
    job_ids: list[str] = []

    for link in links:
        href = await link.get_attribute("href")
        if not href:
            continue

        match = re.search(r"/a/(\d+)", href)
        if match:
            job_ids.append(match.group(1))

    deduped = list(dict.fromkeys(job_ids))
    if deduped:
        return deduped

    html_job_ids = _extract_job_ids_from_html(html)
    if html_job_ids:
        return html_job_ids

    debug_file = _debug_path(keyword, page_no)
    debug_file.write_text(html, encoding="utf-8")
    return []
