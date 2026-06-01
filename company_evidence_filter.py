import re
from difflib import SequenceMatcher
from typing import Any, Optional


EXPERIENCE_WORDS = (
    "怎么样",
    "体验",
    "评价",
    "感受",
    "靠谱吗",
    "值不值得去",
    "值得去吗",
    "工作体验",
    "入职",
    "离职",
    "面试",
    "裁员",
)

RISK_WORDS = (
    "裁员",
    "欠薪",
    "拖欠工资",
    "加班",
    "996",
    "007",
    "单休",
    "年终奖",
    "福利",
    "外包",
    "pua",
    "不交社保",
    "试用期",
    "克扣",
    "仲裁",
)

GENERIC_TOPIC_WORDS = (
    "为什么外包",
    "外包的名声",
    "外包名声",
    "驻场",
    "甲方乙方",
    "大厂外包",
)

COMPANY_SUFFIXES = (
    "有限公司",
    "有限责任公司",
    "股份有限公司",
    "科技有限公司",
    "信息技术有限公司",
    "科技股份有限公司",
    "信息科技有限公司",
    "集团有限公司",
    "集团",
    "公司",
)

PUNCTUATION_PATTERN = re.compile(r"[\s，。！？、；：“”‘’（）()\-—…,.!?:;<>《》/\\|]+")


def normalize_text(text: str) -> str:
    return PUNCTUATION_PATTERN.sub("", str(text or "").lower()).strip()


def collapse_whitespace(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def contains_any(text: str, words: tuple[str, ...]) -> list[str]:
    haystack = str(text or "").lower()
    hits: list[str] = []
    for word in words:
        if word.lower() in haystack:
            hits.append(word)
    return hits


def build_company_aliases(company_name: str, company_name_norm: Optional[str] = None) -> list[str]:
    base_names = [collapse_whitespace(company_name), collapse_whitespace(company_name_norm or "")]
    aliases: list[str] = []
    seen: set[str] = set()

    for name in base_names:
        if not name:
            continue
        candidates = [name]
        stripped = name
        changed = True
        while changed:
            changed = False
            for suffix in COMPANY_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix) + 1:
                    stripped = stripped[: -len(suffix)].strip()
                    candidates.append(stripped)
                    changed = True
                    break
        if len(stripped) >= 2:
            candidates.append(stripped[:4])
            candidates.append(stripped[:3])
            candidates.append(stripped[:2])

        for candidate in candidates:
            candidate = candidate.strip()
            if len(candidate) < 2:
                continue
            normalized = normalize_text(candidate)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            aliases.append(candidate)
    return aliases


def score_relevance(result: dict[str, Any], company_aliases: list[str]) -> tuple[int, list[str]]:
    title = collapse_whitespace(result.get("title"))
    excerpt = collapse_whitespace(result.get("excerpt"))
    score = 0
    reasons: list[str] = []

    for alias in company_aliases:
        if not alias:
            continue
        if alias in title:
            delta = 50 if len(alias) >= 4 else 25
            score += delta
            reasons.append(f"title_alias:{alias}")
        if alias in excerpt:
            delta = 40 if len(alias) >= 4 else 20
            score += delta
            reasons.append(f"excerpt_alias:{alias}")

    return score, reasons


def score_evidence(result: dict[str, Any]) -> tuple[int, list[str]]:
    title = collapse_whitespace(result.get("title"))
    excerpt = collapse_whitespace(result.get("excerpt"))
    score = 0
    reasons: list[str] = []

    title_experience_hits = contains_any(title, EXPERIENCE_WORDS)
    excerpt_experience_hits = contains_any(excerpt, EXPERIENCE_WORDS)
    title_risk_hits = contains_any(title, RISK_WORDS)
    excerpt_risk_hits = contains_any(excerpt, RISK_WORDS)

    if title_experience_hits:
        score += 20
        reasons.append(f"title_experience:{title_experience_hits[0]}")
    if excerpt_experience_hits:
        score += 10
        reasons.append(f"excerpt_experience:{excerpt_experience_hits[0]}")
    if title_risk_hits:
        score += 25
        reasons.append(f"title_risk:{title_risk_hits[0]}")
    if excerpt_risk_hits:
        score += 20
        reasons.append(f"excerpt_risk:{excerpt_risk_hits[0]}")

    return score, reasons


def score_generic_penalty(result: dict[str, Any], company_aliases: list[str]) -> tuple[int, list[str]]:
    title = collapse_whitespace(result.get("title"))
    excerpt = collapse_whitespace(result.get("excerpt"))
    score = 0
    reasons: list[str] = []
    generic_hits = contains_any(title, GENERIC_TOPIC_WORDS)
    if generic_hits:
        score += 20
        reasons.append(f"title_generic:{generic_hits[0]}")
        if any(alias in excerpt for alias in company_aliases):
            score -= 10
            reasons.append("generic_recovered_by_excerpt_alias")
    return score, reasons


def is_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    title_a = normalize_text(a.get("title"))
    title_b = normalize_text(b.get("title"))
    excerpt_a = normalize_text(a.get("excerpt"))
    excerpt_b = normalize_text(b.get("excerpt"))

    if title_a and title_a == title_b:
        if SequenceMatcher(None, excerpt_a[:120], excerpt_b[:120]).ratio() >= 0.72:
            return True

    merged_a = (title_a + excerpt_a)[:240]
    merged_b = (title_b + excerpt_b)[:240]
    return SequenceMatcher(None, merged_a, merged_b).ratio() >= 0.82


def build_description(result: dict[str, Any]) -> str:
    excerpt = collapse_whitespace(result.get("excerpt"))
    title = collapse_whitespace(result.get("title"))
    text = excerpt or title
    if len(text) <= 120:
        return text
    return text[:119].rstrip() + "…"


def filter_search_results(
    results: list[dict[str, Any]],
    *,
    company_name: str,
    company_name_norm: Optional[str] = None,
    limit: int = 3,
    min_score: int = 40,
) -> list[dict[str, Any]]:
    aliases = build_company_aliases(company_name, company_name_norm)
    scored: list[dict[str, Any]] = []

    for result in results:
        relevance_score, relevance_reasons = score_relevance(result, aliases)
        if relevance_score <= 0:
            continue

        evidence_score, evidence_reasons = score_evidence(result)
        generic_penalty, generic_reasons = score_generic_penalty(result, aliases)
        final_score = relevance_score + evidence_score - generic_penalty
        if final_score < min_score:
            continue

        scored.append(
            {
                **result,
                "description": build_description(result),
                "relevance_score": relevance_score,
                "evidence_score": evidence_score,
                "generic_penalty": generic_penalty,
                "final_score": final_score,
                "filter_reasons": relevance_reasons + evidence_reasons + generic_reasons,
            }
        )

    scored.sort(
        key=lambda item: (
            int(item.get("final_score", 0)),
            -int(item.get("rank", 999)),
        ),
        reverse=True,
    )

    deduped: list[dict[str, Any]] = []
    for item in scored:
        if any(is_duplicate(item, kept) for kept in deduped):
            continue
        deduped.append(item)
        if len(deduped) >= limit:
            break

    filtered: list[dict[str, Any]] = []
    for item in deduped:
        filtered.append(
            {
                "schema_version": "zhihu_company_evidence_v2",
                "content_type": str(item.get("content_type") or item.get("type") or ""),
                "content_id": str(item.get("content_id") or item.get("id") or ""),
                "url": str(item.get("url") or ""),
                "title": collapse_whitespace(item.get("title")),
                "description": item.get("description") or "",
                "rank": int(item.get("rank", 0) or 0),
                "relevance_score": int(item.get("relevance_score", 0) or 0),
                "evidence_score": int(item.get("evidence_score", 0) or 0),
                "generic_penalty": int(item.get("generic_penalty", 0) or 0),
                "final_score": int(item.get("final_score", 0) or 0),
                "filter_reasons": list(item.get("filter_reasons") or []),
            }
        )
    return filtered
