import argparse

from config import PATHS
from cleaning.job_cleaner import run_cleaning


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean crawled jobs into AI-ready rows.")
    parser.add_argument("--keyword", help="Optional keyword filter.")
    parser.add_argument("--limit", type=int, help="Maximum source rows to clean.")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only clean rows that do not yet exist in jobs_cleaned.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_cleaning(
        PATHS["database"],
        keyword=args.keyword,
        limit=args.limit,
        only_missing=args.only_missing,
    )
    print(
        f"[clean] selected={result['selected']} cleaned={result['cleaned']} "
        f"keyword={args.keyword or 'ALL'} only_missing={args.only_missing}"
    )


if __name__ == "__main__":
    main()
