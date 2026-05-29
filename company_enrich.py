import argparse
import re
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

from config import PATHS, ZHIHU_CONFIG
from crawler.zhihu_client import ZhihuClientError, ZhihuHTTPError, ZhihuSearchClient
from storage.database import Database


ZH_NEGATIVE_KEYWORDS = (
    "外包""拖欠工资", "不发工资", "克扣工资", "离职不给钱", "工资发不出来", "拖了三个月", "仲裁了才给",
    "不交社保", "不缴公积金", "试用期没社保", "社保基数最低", "不签合同", "阴阳合同", "离职证明卡你",
    "违法辞退", "试用期随便开", "不给赔偿金", "逼你主动离职", "辞退不给N+1",
    "996", "007", "大小周", "单休", "隐形加班", "下班不敢走", "周末强制加班", "节假日加班不给钱",
    "没有加班费", "加班调休也难批", "无偿加班", "凌晨下班", "通宵是常态", "猝死风险",
    "狼性文化", "末位淘汰", "PUA", "画大饼", "洗脑", "感恩教育", "早上喊口号", "跪地爬行", "扇耳光", "体罚",
    "一个人干三个人的活", "招你进来填坑", "工作量巨大", "每天都像打仗",
    "培训贷", "贷款培训", "先交钱", "押金", "服装费", "体检费", "工牌费", "资料费",
    "刷单", "打字员", "手工活", "代加工", "配音兼职", "试衣员",
    "招聘转培训", "收了简历让去培训", "面试变成推销课程",
    "虚假内推", "收费内推", "保证进大厂",
    "高薪模特", "高薪主播", "车贷骗局", "AB贷", "跑分", "洗钱", "外汇", "数字货币", "原油", "白银", "期货",
    "文员实际销售", "行政干催收", "人事做招聘指标", "运营做地推", "实习生当正式工用",
    "储备干部 = 销售", "管培生 = 打杂", "底薪+提成 = 销售岗", "无需经验高薪 = 坑",
    "面试时说一套进来做另一套", "岗位名称高大上实际是电销",
    "老板一言堂", "家族企业", "关系户多", "拍马屁文化", "办公室政治严重",
    "离职率超高", "来了就走留不住人", "每年都招同一批岗位",
    "监控员工电脑", "上厕所计时", "装摄像头", "扣钱明目多", "乐捐", "罚款",
    "扣押身份证", "扣押毕业证", "入职收原件", "不给退",
    "面试过于简单", "当场录用", "不给offer直接让入职", "HR刷KPI", "约面试凑人头",
    "岗位挂了半年还在招", "投了不回复", "已读不回", "面试官态度差",
    "面试问隐私", "问家庭情况", "问婚育计划", "歧视严重",
    "刚成立", "皮包公司", "空壳公司", "查不到", "没有官网", "注册地无人",
    "频繁改名", "法人变更频繁", "劳动仲裁一堆", "被执行人", "失信人",
    "面试地点和注册地不符", "去了发现是居民楼", "废弃写字楼",
    "面议", "薪资范围虚高", "绩效占比一半以上", "提成根本拿不到",
    "无责任底薪很低", "纯提成", "上不封顶",
    "压一个月工资", "离职扣工资", "年终奖拖到第二年还不发",
    "五险一金按最低交", "试用期不打折但试用期很长",
)

ZH_NEUTRAL_TRIGGER_KEYWORDS = (
    "怎么样",
    "用户评价",
    "公司评价",
    "评价",
    "靠谱吗",
    "值不值得去",
    "值得去吗",
    "真实体验",
    "有人了解吗",
    "怎么样啊",
)

SENTENCE_SPLIT_PATTERN = re.compile(r"[。！？；;，,\n]")


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


def _find_first_keyword(
    text: str,
    keywords: tuple[str, ...],
) -> Tuple[Optional[str], int]:
    best_keyword = None
    best_index = -1
    for keyword in keywords:
        idx = text.find(keyword)
        if idx == -1:
            continue
        if best_index == -1 or idx < best_index or (idx == best_index and len(keyword) > len(best_keyword or "")):
            best_keyword = keyword
            best_index = idx
    return best_keyword, best_index


def _extract_snippet_by_keyword(text: str, keyword: str) -> str:
    if not text or not keyword:
        return ""
    idx = text.find(keyword)
    if idx == -1:
        return ""
    left = 0
    for match in SENTENCE_SPLIT_PATTERN.finditer(text[:idx]):
        left = match.end()
    right = len(text)
    right_match = SENTENCE_SPLIT_PATTERN.search(text[idx:])
    if right_match:
        right = idx + right_match.start()
    snippet = text[left:right].strip()
    return snippet or keyword


def _analyze_search_results(
    search_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []

    for index, item in enumerate(search_results[:3], start=1):
        title = str(item.get("title") or "")
        excerpt = str(item.get("excerpt") or "")
        title_negative_keyword, _ = _find_first_keyword(title, ZH_NEGATIVE_KEYWORDS)
        title_neutral_keyword, _ = _find_first_keyword(title, ZH_NEUTRAL_TRIGGER_KEYWORDS)
        excerpt_negative_keyword, _ = _find_first_keyword(excerpt, ZH_NEGATIVE_KEYWORDS)

        hit_parts: list[str] = []
        if title_negative_keyword:
            hit_parts.append(f"title_negative={title_negative_keyword}")
        if title_neutral_keyword:
            hit_parts.append(f"title_neutral={title_neutral_keyword}")
        if excerpt_negative_keyword:
            hit_parts.append(f"excerpt_negative={excerpt_negative_keyword}")
        hit_suffix = f" hit={' | '.join(hit_parts)}" if hit_parts else ""
        print(f"[zhihu-result-{index}] title={title}{hit_suffix}")

        title_hit = bool(title_negative_keyword or title_neutral_keyword)
        excerpt_hit = bool(excerpt_negative_keyword)
        if not title_hit and not excerpt_hit:
            continue

        matched_in = "excerpt" if excerpt_hit else "title"
        matched_keyword = excerpt_negative_keyword or title_negative_keyword or title_neutral_keyword or ""
        matched_snippet = (
            _extract_snippet_by_keyword(excerpt, excerpt_negative_keyword)
            if excerpt_negative_keyword
            else _extract_snippet_by_keyword(title, matched_keyword)
        )
        need_expand_fulltext = int(title_hit and not excerpt_hit)
        evidence_reason = "excerpt_negative_match" if excerpt_hit else (
            "title_negative_match" if title_negative_keyword else "title_neutral_trigger"
        )

        evidence_items.append(
            {
                "type": item.get("type"),
                "id": item.get("id"),
                "url": item.get("url"),
                "title": title,
                "excerpt": excerpt,
                "matched_in": matched_in,
                "matched_keyword": matched_keyword,
                "matched_snippet": matched_snippet,
                "reason": evidence_reason,
                "need_expand_fulltext": need_expand_fulltext,
            }
        )

    return evidence_items


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

        evidence_items = _analyze_search_results(
            raw_search_results
        )
        result_status = "done" if evidence_items else "done_empty"
        expire_at = datetime.utcnow() + timedelta(hours=ZHIHU_CONFIG["cache_ttl_hours"])
        database.upsert_company_enriched(
            {
                "company_name_norm": company_name_norm,
                "company_name_raw": company_name_raw,
                "status": result_status,
                "source": ZHIHU_CONFIG["source"],
                "query": company_name_raw,
                "search_results": [],
                "negative_sentences": evidence_items,
                "risk_level": None,
                "risk_reasons": [],
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
            f"need_expand={sum(int(x.get('need_expand_fulltext', 0)) for x in evidence_items)}"
        )

    print(
        f"[company-enrich-summary] selected={len(companies)} "
        f"processed={processed} done={done} done_empty={done_empty} "
        f"failed={failed} cached={cached}"
    )


if __name__ == "__main__":
    main()
