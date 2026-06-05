import argparse
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PYTHON_EXE = BASE_DIR / ".venv" / "Scripts" / "python.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run post-processing pipeline: clean -> company enrich -> score."
    )
    parser.add_argument("--keyword", help="Optional keyword filter shared by all stages.")

    parser.add_argument("--clean-limit", type=int, default=50, help="Maximum source rows to clean. Default: 50.")
    parser.add_argument(
        "--clean-only-missing",
        action="store_true",
        help="Only clean rows that do not yet exist in jobs_cleaned.",
    )

    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=None,
        help="Maximum companies to enrich in one run. Default: all pending.",
    )
    parser.add_argument(
        "--enrich-refresh",
        action="store_true",
        help="Ignore unexpired company_enriched cache and fetch again.",
    )

    parser.add_argument(
        "--score-limit",
        type=int,
        help="Maximum jobs to score in one run. Default uses AI_CONFIG batch_size.",
    )
    parser.add_argument(
        "--score-dry-run",
        action="store_true",
        help="Preview score prompt payload without calling the AI API.",
    )

    parser.add_argument("--skip-clean", action="store_true", help="Skip clean stage.")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip company enrich stage.")
    parser.add_argument("--skip-score", action="store_true", help="Skip score stage.")
    return parser.parse_args()


def get_python_executable() -> str:
    if PYTHON_EXE.exists():
        return str(PYTHON_EXE)
    return sys.executable


def build_command(script_name: str, args: list[str]) -> list[str]:
    return [get_python_executable(), str(BASE_DIR / script_name), *args]


def run_stage(stage_name: str, command: list[str]) -> None:
    print(f"[pipeline] start {stage_name}: {' '.join(command)}")
    subprocess.run(command, cwd=BASE_DIR, check=True)
    print(f"[pipeline] done {stage_name}")


def main() -> None:
    args = parse_args()

    clean_args: list[str] = []
    if args.keyword:
        clean_args.extend(["--keyword", args.keyword])
    if args.clean_limit is not None:
        clean_args.extend(["--limit", str(args.clean_limit)])
    if args.clean_only_missing:
        clean_args.append("--only-missing")

    enrich_args: list[str] = []
    if args.keyword:
        enrich_args.extend(["--keyword", args.keyword])
    if args.enrich_limit is not None:
        enrich_args.extend(["--limit", str(args.enrich_limit)])
    if args.enrich_refresh:
        enrich_args.append("--refresh")

    score_args: list[str] = []
    if args.keyword:
        score_args.extend(["--keyword", args.keyword])
    if args.score_limit is not None:
        score_args.extend(["--limit", str(args.score_limit)])
    if args.score_dry_run:
        score_args.append("--dry-run")

    try:
        if not args.skip_clean:
            run_stage("clean", build_command("clean_jobs.py", clean_args))
        if not args.skip_enrich:
            run_stage("company_enrich", build_command("company_enrich.py", enrich_args))
        if not args.skip_score:
            run_stage("score", build_command("score_jobs.py", score_args))
    except subprocess.CalledProcessError as exc:
        print(f"[pipeline] failed stage exit_code={exc.returncode}")
        raise SystemExit(exc.returncode) from exc

    print("[pipeline] completed")


if __name__ == "__main__":
    main()
