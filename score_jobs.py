import argparse
import json

from ai.prompts import PROMPT_VERSION, build_user_prompt
from config import AI_CONFIG, PATHS
from storage.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score cleaned jobs with AI.")
    parser.add_argument("--keyword", help="Optional keyword filter.")
    parser.add_argument("--limit", type=int, default=AI_CONFIG["batch_size"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the prompt payload without calling the AI API.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database = Database(PATHS["database"])
    database.init()

    jobs = database.get_jobs_ready_for_scoring(
        keyword=args.keyword,
        limit=args.limit,
        max_days_since_update=AI_CONFIG["max_days_since_update"],
    )
    if not jobs:
        print(
            f"[score] no cleaned jobs ready for scoring "
            f"(last_updated <= {AI_CONFIG['max_days_since_update']} days)"
        )
        return

    if args.dry_run:
        sample = jobs[0]
        job_input = json.loads(sample["ai_input_json"])
        prompt = build_user_prompt(json.dumps(job_input, ensure_ascii=False, indent=2))
        print(
            f"[score-dry-run] selected={len(jobs)} keyword={args.keyword or 'ALL'} "
            f"prompt_version={PROMPT_VERSION} "
            f"max_days_since_update={AI_CONFIG['max_days_since_update']}"
        )
        print(job_input)
        print(prompt[:2000])
        return

    from ai.scorer import JobScorer

    scorer = JobScorer()
    success_count = 0
    for item in jobs:
        job_input = json.loads(item["ai_input_json"])
        score = scorer.score_job(job_input)
        score["job_id"] = item["job_id"]
        database.upsert_score(score)
        success_count += 1
        print(
            f"[score] job_id={item['job_id']} total={score['total']} "
            f"verdict={score['verdict']}"
        )

    print(
        f"[score-summary] selected={len(jobs)} scored={success_count} "
        f"remaining={database.ready_for_scoring_count(keyword=args.keyword, max_days_since_update=AI_CONFIG['max_days_since_update'])}"
    )


if __name__ == "__main__":
    main()
