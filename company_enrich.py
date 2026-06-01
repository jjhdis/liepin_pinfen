import argparse
from datetime import datetime, timedelta
from typing import Any

from company_evidence_filter import filter_search_results
from config import PATHS, ZHIHU_CONFIG
from crawler.zhihu_client import ZhihuClientError, ZhihuHTTPError, ZhihuSearchClient
from storage.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich risky companies with Zhihu search summaries."
    )
    parser.add_argument("--keyword", help="Optional keyword filter.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum companies to process.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore unexpired company_enriched cache and fetch again.",
    )
    return parser.parse_args()


def _is_cache_valid(record: dict[str, Any]) -> bool:
    expire_at = record.get("expire_at")
    if not expire_at:
        return False
    try:
        return datetime.fromisoformat(expire_at) > datetime.utcnow()
    except ValueError:
        return False


def _build_risk_summary(evidence_items: list[dict[str, Any]]) -> tuple[str, list[str]]:
    reasons = sorted(
        {
            str(reason).strip()
            for item in evidence_items
            for reason in item.get("filter_reasons", [])
            if str(reason).strip()
        }
    )
    if not evidence_items:
        return "none", reasons
    if any(
        any(
            str(reason).startswith(("title_risk:", "excerpt_risk:"))
            for reason in item.get("filter_reasons", [])
        )
        for item in evidence_items
    ):
        return "medium", reasons
    return "low", reasons


def main() -> None:
    args = parse_args()
    database = Database(PATHS["database"])
    database.init()

    companies = database.get_companies_ready_for_enrichment(
        keyword=args.keyword,
        limit=args.limit,
    )
    if not companies:
        print("[company-enrich] no companies ready for enrichment")
        return

    client = ZhihuSearchClient()
    processed = 0
    cached = 0
    done = 0
    done_empty = 0
    failed = 0

    for item in companies:
        company_name_norm = item["company_name_norm"]
        company_name_raw = item.get("company_name_raw") or company_name_norm

        existing = database.get_company_enriched(company_name_norm)
        if existing and not args.refresh and _is_cache_valid(existing):
            cached_status = existing.get("status") or "done"
            database.update_company_check_status(company_name_norm, status=cached_status)
            cached += 1
            print(
                f"[company-enrich-cache-hit] company={company_name_raw} "
                f"status={cached_status}"
            )
            continue

        try:
            raw_search_results = client.search_company(company_name_raw)
        except ZhihuHTTPError as exc:
            database.update_company_check_status(company_name_norm, status="failed")
            failed += 1
            print(
                f"[company-enrich-stop] company={company_name_raw} "
                f"status_code={exc.status_code} error={exc} "
                f"debug={exc.debug_path or 'N/A'}"
            )
            break
        except ZhihuClientError as exc:
            database.update_company_check_status(company_name_norm, status="failed")
            failed += 1
            print(f"[company-enrich-stop] company={company_name_raw} error={exc}")
            break

        for raw_item in raw_search_results:
            print(
                f"[zhihu-result-{int(raw_item.get('rank', 0) or 0)}] "
                f"title={raw_item.get('title', '')}"
            )
        search_results = raw_search_results
        evidence_items = filter_search_results(
            raw_search_results,
            company_name=company_name_raw,
            company_name_norm=company_name_norm,
            limit=ZHIHU_CONFIG["filtered_top_n"],
        )
        risk_level, risk_reasons = _build_risk_summary(evidence_items)
        result_status = "done" if evidence_items else "done_empty"
        expire_at = datetime.utcnow() + timedelta(hours=ZHIHU_CONFIG["cache_ttl_hours"])
        database.upsert_company_enriched(
            {
                "company_name_norm": company_name_norm,
                "company_name_raw": company_name_raw,
                "status": result_status,
                "source": ZHIHU_CONFIG["source"],
                "query": company_name_raw,
                "zhihu_raw_results": search_results,
                "zhihu_filtered_results": evidence_items,
                "search_results": search_results,
                "negative_sentences": evidence_items,
                "risk_level": risk_level,
                "risk_reasons": risk_reasons,
                "last_checked_at": datetime.utcnow().isoformat(timespec="seconds"),
                "expire_at": expire_at.isoformat(timespec="seconds"),
            }
        )
        database.update_company_check_status(company_name_norm, status=result_status)
        processed += 1
        if result_status == "done":
            done += 1
        else:
            done_empty += 1
        print(
            f"[company-enrich] company={company_name_raw} "
            f"evidence={len(evidence_items)} status={result_status} "
            f"risk_level={risk_level}"
        )

    print(
        f"[company-enrich-summary] selected={len(companies)} "
        f"processed={processed} done={done} done_empty={done_empty} "
        f"failed={failed} cached={cached}"
    )


if __name__ == "__main__":
    main()
