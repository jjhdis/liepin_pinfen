import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from config import PATHS, RUN_CONFIG, normalize_keyword
from cookie_manager import (
    mark_profile_blocked,
    mark_profile_used,
    scan_and_cleanup,
)
from storage.database import Database


BASE_DIR = Path(__file__).resolve().parent
PYTHON_EXE = BASE_DIR / ".venv" / "Scripts" / "python.exe"
DEFAULT_PLATFORM = "liepin"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rotate available Liepin cookies. "
            "Each cookie runs one detail batch, then switch to the next."
        )
    )
    parser.add_argument("--keyword", help="Optional keyword filter for detail batches.")
    parser.add_argument(
        "--per-cookie-detail",
        type=int,
        default=25,
        help="How many detail jobs to process per cookie. Default: 25",
    )
    parser.add_argument(
        "--max-cookies",
        type=int,
        default=RUN_CONFIG.get("cookie_max_per_run"),
        help="Max cookies to use. Default: config cookie_max_per_run.",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        help="Override detail min-delay passed through to main.py detail.",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        help="Override detail max-delay passed through to main.py detail.",
    )
    parser.add_argument(
        "--startup-cooldown-min",
        type=float,
        help="Override detail startup cooldown min passed through to main.py detail.",
    )
    parser.add_argument(
        "--startup-cooldown-max",
        type=float,
        help="Override detail startup cooldown max passed through to main.py detail.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Pass --interactive to each detail batch.",
    )
    parser.add_argument(
        "--auto",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Auto-trigger postprocess pipeline when enough jobs are ready. Default: use config.",
    )
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        help=f"Platform to scan cookies for. Default: {DEFAULT_PLATFORM}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print planned cookie batches without executing them.",
    )
    return parser.parse_args()


def get_python_executable() -> str:
    if PYTHON_EXE.exists():
        return str(PYTHON_EXE)
    return sys.executable


def build_detail_command(
    args: argparse.Namespace,
    cookie_file_name: str,
    cookie_profile_name: str = "",
) -> list[str]:
    command = [
        get_python_executable(),
        str(BASE_DIR / "main.py"),
        "detail",
        "--max-detail",
        str(args.per_cookie_detail),
        "--cookie-file",
        cookie_file_name,
    ]
    if cookie_profile_name:
        command.extend(["--cookie-profile-name", cookie_profile_name])
    if args.keyword:
        command.extend(["--keyword", args.keyword])
    if args.min_delay is not None:
        command.extend(["--min-delay", str(args.min_delay)])
    if args.max_delay is not None:
        command.extend(["--max-delay", str(args.max_delay)])
    if args.startup_cooldown_min is not None:
        command.extend(["--startup-cooldown-min", str(args.startup_cooldown_min)])
    if args.startup_cooldown_max is not None:
        command.extend(["--startup-cooldown-max", str(args.startup_cooldown_max)])
    if args.interactive:
        command.append("--interactive")
    return command


def pending_count(keyword: Optional[str]) -> int:
    database = Database(PATHS["database"])
    database.init()
    return database.pending_job_count(keyword=keyword)


def _maybe_trigger_postprocess(
    keyword: Optional[str],
    auto_flag: Optional[bool],
    cookie_label: str,
) -> None:
    """Run postprocess_pipeline.py if auto mode is on and enough jobs are ready."""
    auto_enabled = auto_flag if auto_flag is not None else RUN_CONFIG["auto_postprocess"]
    if not auto_enabled:
        return

    threshold = RUN_CONFIG["auto_postprocess_min_jobs"]
    database = Database(PATHS["database"])
    database.init()
    ready_count = database.ready_for_clean_count(keyword=keyword)

    print(
        f"[cookie-rotate-auto-check] ready_for_clean={ready_count} "
        f"threshold={threshold} keyword={keyword or 'ALL'}"
    )

    if ready_count < threshold:
        print(
            f"[cookie-rotate-auto-skip] not enough jobs "
            f"({ready_count} < {threshold}), skip postprocess"
        )
        return

    pipeline_script = BASE_DIR / "postprocess_pipeline.py"
    pipeline_cmd = [get_python_executable(), str(pipeline_script)]
    if keyword:
        pipeline_cmd.extend(["--keyword", keyword])

    print(
        f"[cookie-rotate-auto-trigger] ready={ready_count} >= {threshold} "
        f"command={' '.join(pipeline_cmd)} cookie={cookie_label}"
    )
    completed = subprocess.run(pipeline_cmd, cwd=BASE_DIR)
    if completed.returncode != 0:
        print(
            f"[cookie-rotate-auto-failed] postprocess exit_code={completed.returncode} "
            f"cookie={cookie_label}"
        )


def main() -> None:
    args = parse_args()
    args.keyword = normalize_keyword(args.keyword)

    # --- Step 1: scan & cleanup cookies (once before crawl) ---
    cookies = scan_and_cleanup(platform=args.platform)
    if not cookies:
        print(
            f"[cookie-rotate] no cookies available for platform={args.platform}. "
            f"Place cookie files in {PATHS['cookie_dir']}"
        )
        raise SystemExit(1)

    max_cookies = args.max_cookies
    if max_cookies and max_cookies > 0:
        cookies = cookies[:max_cookies]

    initial_pending = pending_count(args.keyword)
    print(
        f"[cookie-rotate] platform={args.platform} "
        f"keyword={args.keyword or 'ALL'} "
        f"cookies={len(cookies)} pending_total={initial_pending} "
        f"per_cookie_detail={args.per_cookie_detail}"
    )

    # --- Step 2: rotate ---
    for index, item in enumerate(cookies, start=1):
        remaining = pending_count(args.keyword)
        if remaining <= 0:
            print("[cookie-rotate] no pending jobs left, stop rotation")
            break

        cookie_path = item["path"]
        profile_name = item["profile_name"]
        tier = item["tier"]

        command = build_detail_command(args, cookie_path.name, profile_name)
        print(
            f"[cookie-rotate] batch={index}/{len(cookies)} "
            f"cookie={cookie_path.name} tier={tier} "
            f"profile={profile_name} pending_before={remaining}"
        )
        print(f"[cookie-rotate] command={' '.join(command)}")

        if args.dry_run:
            continue

        completed = subprocess.run(command, cwd=BASE_DIR)
        if completed.returncode != 0:
            print(
                f"[cookie-rotate] batch_failed cookie={cookie_path.name} "
                f"exit_code={completed.returncode}"
            )
            mark_profile_blocked(
                platform=args.platform,
                profile_name=profile_name,
                reason=f"detail exit_code={completed.returncode}",
            )
            # Continue with next cookie instead of hard-exit
            print(
                f"[cookie-rotate] switching to next cookie after failure, "
                f"profile={profile_name} marked needs_manual_verify"
            )
            continue

        # Record successful usage
        mark_profile_used(
            platform=args.platform,
            profile_name=profile_name,
        )

        # Auto postprocess check after each successful batch
        _maybe_trigger_postprocess(
            keyword=args.keyword,
            auto_flag=args.auto,
            cookie_label=cookie_path.name,
        )

    final_pending = pending_count(args.keyword)
    print(
        f"[cookie-rotate-summary] keyword={args.keyword or 'ALL'} "
        f"pending_before={initial_pending} pending_after={final_pending}"
    )


if __name__ == "__main__":
    main()
