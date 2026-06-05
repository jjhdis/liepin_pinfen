import argparse
import asyncio
import time

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from config import PATHS, RUN_CONFIG, normalize_keyword
from crawler.anti_detect import human_like_page_settle, random_delay
from crawler.browser import open_browser, resolve_cookie_path
from crawler.detail_page import (
    DetailPageBlockedError,
    DetailPageExpiredError,
    DetailPageLoginRequiredError,
    DetailPageMismatchError,
    fetch_detail_page,
)
from crawler.list_page import (
    ListPageBlockedError,
    build_search_url,
    open_search_page,
    scrape_list_job_cards,
)
from storage.database import Database


def _add_interactive_arg(parser: argparse.ArgumentParser, default: bool) -> None:
    parser.add_argument(
        "--interactive",
        action=argparse.BooleanOptionalAction,
        default=default,
        help="Ask for confirmation before or during batch processing.",
    )


def _add_cookie_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cookie-file",
        help=(
            "Cookie file to use for Liepin. Supports an absolute path, a project-relative "
            "path, or a filename under the cookies/ directory. Default: cookies.json"
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Low-frequency liepin crawler with split list/detail modes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Fetch one or more list pages only.")
    list_parser.add_argument("--keyword", required=True, help="Search keyword, e.g. python")
    list_parser.add_argument("--page", type=int, default=RUN_CONFIG["list"]["page"], help="Start page number, 0-based.")
    list_parser.add_argument("--pages", type=int, default=RUN_CONFIG["list"]["pages"], help="How many pages to fetch.")
    list_parser.add_argument("--min-delay", type=float, default=RUN_CONFIG["list"]["min_delay"])
    list_parser.add_argument("--max-delay", type=float, default=RUN_CONFIG["list"]["max_delay"])
    list_parser.add_argument(
        "--store-top-n",
        type=int,
        default=RUN_CONFIG["list"]["store_top_n"],
        help="Only keep the first N list cards from each search page. Default: %(default)s",
    )
    _add_interactive_arg(list_parser, RUN_CONFIG["list"]["interactive"])
    _add_cookie_arg(list_parser)

    detail_parser = subparsers.add_parser("detail", help="Fetch a small batch of pending detail pages.")
    detail_parser.add_argument("--keyword", help="Optional keyword filter.")
    detail_parser.add_argument("--max-detail", type=int, default=RUN_CONFIG["detail"]["max_detail"])
    detail_parser.add_argument("--min-delay", type=float, default=RUN_CONFIG["detail"]["min_delay"])
    detail_parser.add_argument("--max-delay", type=float, default=RUN_CONFIG["detail"]["max_delay"])
    _add_interactive_arg(detail_parser, RUN_CONFIG["detail"]["interactive"])
    _add_cookie_arg(detail_parser)
    detail_parser.add_argument("--cookie-profile-name", help="Cookie profile name for crawl_log tracing.")
    detail_parser.add_argument("--startup-cooldown-min", type=float, default=RUN_CONFIG["detail"]["startup_cooldown_min"])
    detail_parser.add_argument("--startup-cooldown-max", type=float, default=RUN_CONFIG["detail"]["startup_cooldown_max"])
    detail_parser.add_argument("--confirm-every", type=int, default=RUN_CONFIG["detail"]["confirm_every"])
    detail_parser.add_argument("--cooldown-every", type=int, default=RUN_CONFIG["detail"]["cooldown_every"])
    detail_parser.add_argument("--cooldown-min", type=float, default=RUN_CONFIG["detail"]["cooldown_min"])
    detail_parser.add_argument("--cooldown-max", type=float, default=RUN_CONFIG["detail"]["cooldown_max"])

    return parser.parse_args()


def _confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


async def run_list_mode(args: argparse.Namespace, database: Database) -> None:
    cookie_path = resolve_cookie_path(args.cookie_file)
    if args.cookie_file and not cookie_path.exists():
        raise FileNotFoundError(f"Cookie file not found: {cookie_path}")

    print(f"[cookie-selected] file={cookie_path}")

    async with open_browser(args.cookie_file) as (_, context):
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
                job_cards = await scrape_list_job_cards(page, args.keyword, page_no)
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
                print(f"[list-stop] keyword={args.keyword} page={page_no} reason=blocked error={exc}")
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

            print(
                f"[list-success] keyword={args.keyword} page={page_no} "
                f"job_ids={len(job_cards)}"
            )

            if not job_cards:
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
                print(
                    f"[list-failed] keyword={args.keyword} page={page_no} "
                    f"error=no job ids extracted; saved debug html"
                )
                return

            selected_job_cards = job_cards[: args.store_top_n] if args.store_top_n > 0 else job_cards
            dropped_count = max(0, len(job_cards) - len(selected_job_cards))

            for item in selected_job_cards:
                database.insert_job_stub(
                    job_id=item["job_id"],
                    keyword=args.keyword,
                    detail_url=item["detail_url"],
                )

            print(
                f"[list-success] keyword={args.keyword} page={page_no} "
                f"stored={len(selected_job_cards)} dropped_tail={dropped_count} "
                f"pending_total={database.pending_job_count(keyword=args.keyword)} action=stored"
            )

            if args.interactive and page_offset != args.pages - 1:
                if not _confirm("Continue to next list page?"):
                    print("[list-paused] user stopped after current page")
                    return

            if page_offset != args.pages - 1:
                await random_delay(args.min_delay, args.max_delay)


async def run_detail_mode(args: argparse.Namespace, database: Database) -> None:
    cookie_path = resolve_cookie_path(args.cookie_file)
    if args.cookie_file and not cookie_path.exists():
        raise FileNotFoundError(f"Cookie file not found: {cookie_path}")

    pending_jobs = database.get_pending_jobs(keyword=args.keyword, limit=args.max_detail)
    if not pending_jobs:
        print("[detail] no pending jobs found")
        return

    print(
        f"[detail-plan] keyword={args.keyword or 'ALL'} "
        f"batch={len(pending_jobs)} pending_total={database.pending_job_count(keyword=args.keyword)} "
        f"cookie={cookie_path.name}"
    )

    if args.interactive and not _confirm("Start fetching the pending detail batch?"):
        print("[detail-cancelled] user declined before start")
        return

    startup_cooldown_seconds = await random_delay(
        args.startup_cooldown_min,
        args.startup_cooldown_max,
    )
    print(f"[detail-startup-cooldown] sleep_seconds={startup_cooldown_seconds:.1f}")

    print(f"[cookie-selected] file={cookie_path}")

    async with open_browser(args.cookie_file) as (_, context):
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
                database.update_detail_status(job_id, status="pending", error_message=None)
                await open_search_page(page, keyword, 0)
                await human_like_page_settle(page)
                job = await fetch_detail_page(
                    page,
                    job_id,
                    keyword,
                    detail_url,
                    referer=page.url,
                )
                path = "search_warmup_then_direct_goto"
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
                    error_message=None,
                    cookie_profile_name=args.cookie_profile_name,
                )
                print(
                    f"[detail-success] job_id={job_id} title={job.get('title')} "
                    f"status=success path={path}"
                )
            except (DetailPageBlockedError, DetailPageLoginRequiredError) as exc:
                status = "blocked" if isinstance(exc, DetailPageBlockedError) else "login_required"
                database.update_detail_status(job_id, status=status, error_message=str(exc))
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
                    cookie_profile_name=args.cookie_profile_name,
                )
                print(f"[detail-stop] job_id={job_id} status={status} error={exc}")
                return
            except ListPageBlockedError as exc:
                database.update_detail_status(job_id, status="blocked", error_message=str(exc))
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
                    cookie_profile_name=args.cookie_profile_name,
                )
                print(f"[detail-stop] job_id={job_id} status=blocked error={exc}")
                return
            except (DetailPageMismatchError, DetailPageExpiredError) as exc:
                status = "wrong_page" if isinstance(exc, DetailPageMismatchError) else "expired"
                database.update_detail_status(job_id, status=status, error_message=str(exc))
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
                    cookie_profile_name=args.cookie_profile_name,
                )
                database.delete_raw_job(job_id)
                print(
                    f"[detail-stop] job_id={job_id} status={status} "
                    f"action=delete_and_stop error={exc}"
                )
                return
            except PlaywrightTimeoutError as exc:
                database.update_detail_status(job_id, status="parse_failed", error_message=str(exc))
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
                    cookie_profile_name=args.cookie_profile_name,
                )
                database.delete_raw_job(job_id)
                print(
                    f"[detail-skip] job_id={job_id} status=timeout "
                    f"action=delete_and_continue error={exc}"
                )
            except Exception as exc:
                database.update_detail_status(job_id, status="parse_failed", error_message=str(exc))
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
                    cookie_profile_name=args.cookie_profile_name,
                )
                print(f"[detail-failed] job_id={job_id} status=parse_failed error={exc}")

            processed += 1
            if processed == len(pending_jobs):
                continue

            if args.cooldown_every > 0 and processed % args.cooldown_every == 0:
                cooldown_seconds = await random_delay(args.cooldown_min, args.cooldown_max)
                print(
                    f"[detail-cooldown] processed={processed} "
                    f"sleep_seconds={cooldown_seconds:.1f}"
                )
                continue

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
    if hasattr(args, "keyword"):
        args.keyword = normalize_keyword(args.keyword)
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
