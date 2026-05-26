import argparse
import asyncio
import time
from typing import Optional

from config import PATHS, SEARCH_CONFIG
from crawler.anti_detect import random_delay
from crawler.browser import open_browser
from crawler.detail_page import DetailPageBlockedError, fetch_detail_page
from crawler.list_page import ListPageBlockedError, build_search_url, scrape_list_page
from storage.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Low-frequency liepin crawler with split list/detail modes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Fetch one or more list pages only.")
    list_parser.add_argument("--keyword", required=True, help="Search keyword, e.g. python")
    list_parser.add_argument("--page", type=int, default=0, help="Start page number, 0-based.")
    list_parser.add_argument("--pages", type=int, default=1, help="How many pages to fetch.")
    list_parser.add_argument("--min-delay", type=float, default=120.0)
    list_parser.add_argument("--max-delay", type=float, default=300.0)
    list_parser.add_argument("--interactive", action="store_true")

    detail_parser = subparsers.add_parser("detail", help="Fetch a small batch of pending detail pages.")
    detail_parser.add_argument("--keyword", help="Optional keyword filter.")
    detail_parser.add_argument("--max-detail", type=int, default=3)
    detail_parser.add_argument("--min-delay", type=float, default=20.0)
    detail_parser.add_argument("--max-delay", type=float, default=60.0)
    detail_parser.add_argument("--interactive", action="store_true")
    detail_parser.add_argument("--confirm-every", type=int, default=1)

    return parser.parse_args()


def _confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


async def run_list_mode(args: argparse.Namespace, database: Database) -> None:
    async with open_browser() as (_, context):
        page = await context.new_page()

        if args.interactive and not _confirm(
            f"About to fetch {args.pages} list page(s) for keyword={args.keyword} starting at page={args.page}."
        ):
            print("[list-cancelled] user declined before start")
            return

        for page_offset in range(args.pages):
            page_no = args.page + page_offset
            list_url = build_search_url(args.keyword, page_no)
            list_started = time.perf_counter()

            try:
                job_ids = await scrape_list_page(page, args.keyword, page_no)
                list_latency = time.perf_counter() - list_started
                database.log_crawl(
                    url=list_url,
                    keyword=args.keyword,
                    page_no=page_no,
                    job_id=None,
                    status_code=200,
                    latency_seconds=list_latency,
                    retry_count=0,
                    success=True,
                )
            except ListPageBlockedError as exc:
                database.log_crawl(
                    url=list_url,
                    keyword=args.keyword,
                    page_no=page_no,
                    job_id=None,
                    status_code=None,
                    latency_seconds=time.perf_counter() - list_started,
                    retry_count=0,
                    success=False,
                    error_message=str(exc),
                )
                print(f"[list-blocked] keyword={args.keyword} page={page_no} error={exc}")
                return
            except Exception as exc:
                database.log_crawl(
                    url=list_url,
                    keyword=args.keyword,
                    page_no=page_no,
                    job_id=None,
                    status_code=None,
                    latency_seconds=time.perf_counter() - list_started,
                    retry_count=0,
                    success=False,
                    error_message=str(exc),
                )
                print(f"[list-failed] keyword={args.keyword} page={page_no} error={exc}")
                return

            print(f"[list] keyword={args.keyword} page={page_no} job_ids={len(job_ids)}")

            if not job_ids:
                database.log_crawl(
                    url=list_url,
                    keyword=args.keyword,
                    page_no=page_no,
                    job_id=None,
                    status_code=None,
                    latency_seconds=None,
                    retry_count=0,
                    success=False,
                    error_message="no job ids extracted; saved debug html",
                )
                return

            for job_id in job_ids:
                database.insert_job_stub(
                    job_id=job_id,
                    keyword=args.keyword,
                    detail_url=f"https://www.liepin.com/a/{job_id}.shtml",
                )

            print(
                f"[list-stored] keyword={args.keyword} page={page_no} "
                f"pending_total={database.pending_job_count(keyword=args.keyword)}"
            )

            if args.interactive and page_offset != args.pages - 1:
                if not _confirm("Continue to next list page?"):
                    print("[list-paused] user stopped after current page")
                    return

            if page_offset != args.pages - 1:
                await random_delay(args.min_delay, args.max_delay)


async def run_detail_mode(args: argparse.Namespace, database: Database) -> None:
    pending_jobs = database.get_pending_jobs(keyword=args.keyword, limit=args.max_detail)
    if not pending_jobs:
        print("[detail] no pending jobs found")
        return

    print(
        f"[detail-plan] keyword={args.keyword or 'ALL'} "
        f"batch={len(pending_jobs)} pending_total={database.pending_job_count(keyword=args.keyword)}"
    )

    if args.interactive and not _confirm("Start fetching the pending detail batch?"):
        print("[detail-cancelled] user declined before start")
        return

    async with open_browser() as (_, context):
        page = await context.new_page()
        processed = 0

        for item in pending_jobs:
            job_id = item["job_id"]
            keyword = item["keyword"]
            detail_url = item["detail_url"]
            detail_started = time.perf_counter()

            if args.interactive and processed > 0 and processed % args.confirm_every == 0:
                if not _confirm("Continue to next detail page?"):
                    print("[detail-paused] user stopped batch")
                    return

            try:
                job = await fetch_detail_page(page, job_id, keyword)
                database.upsert_job(job)
                database.log_crawl(
                    url=detail_url,
                    keyword=keyword,
                    page_no=None,
                    job_id=job_id,
                    status_code=200,
                    latency_seconds=time.perf_counter() - detail_started,
                    retry_count=0,
                    success=True,
                )
                print(f"[detail] job_id={job_id} title={job.get('title')}")
            except DetailPageBlockedError as exc:
                database.log_crawl(
                    url=detail_url,
                    keyword=keyword,
                    page_no=None,
                    job_id=job_id,
                    status_code=None,
                    latency_seconds=time.perf_counter() - detail_started,
                    retry_count=0,
                    success=False,
                    error_message=str(exc),
                )
                print(f"[detail-blocked] job_id={job_id} error={exc}")
                return
            except Exception as exc:
                database.log_crawl(
                    url=detail_url,
                    keyword=keyword,
                    page_no=None,
                    job_id=job_id,
                    status_code=None,
                    latency_seconds=time.perf_counter() - detail_started,
                    retry_count=0,
                    success=False,
                    error_message=str(exc),
                )
                print(f"[detail-failed] job_id={job_id} error={exc}")

            processed += 1
            if processed != len(pending_jobs):
                await random_delay(args.min_delay, args.max_delay)


async def async_main(args: argparse.Namespace) -> None:
    database = Database(PATHS["database"])
    database.init()

    if args.command == "list":
        await run_list_mode(args, database)
        return

    if args.command == "detail":
        await run_detail_mode(args, database)
        return

    raise ValueError(f"Unsupported command: {args.command}")


def main() -> None:
    args = parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
