import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup

COMPANY_CHECK_NAME_SKIP_KEYWORDS = ("某",)


def _normalize_flag_value_sql(column_name: str, true_words: tuple[str, ...]) -> str:
    true_literals = ", ".join(f"'{word}'" for word in true_words)
    return f"""
        CASE
            WHEN {column_name} IS NULL THEN 0
            WHEN CAST({column_name} AS INTEGER) = 1 THEN 1
            WHEN LOWER(TRIM(CAST({column_name} AS TEXT))) IN ({true_literals}) THEN 1
            ELSE 0
        END
    """


def _table_info(conn: sqlite3.Connection, table_name: str) -> dict[str, sqlite3.Row]:
    return {
        row[1]: row
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _needs_jobs_rebuild(columns: dict[str, sqlite3.Row]) -> bool:
    clean_status = columns.get("clean_status")
    if not clean_status:
        return False
    column_type = (clean_status[2] or "").upper()
    default_value = (clean_status[4] or "").strip("'\"")
    return column_type != "INTEGER" or default_value != "0"


def _rebuild_jobs_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE jobs__migrated (
            job_id TEXT PRIMARY KEY,
            keyword TEXT,
            detail_url TEXT,
            title TEXT,
            salary_min INTEGER,
            salary_max INTEGER,
            salary_months INTEGER,
            city TEXT,
            exp_years TEXT,
            education TEXT,
            date_posted TEXT,
            last_updated TEXT,
            days_since_update INTEGER,
            company_name TEXT,
            company_size TEXT,
            company_verified INTEGER,
            company_logo_exists INTEGER,
            publisher_type TEXT,
            jd_text TEXT,
            jd_length INTEGER,
            benefits_json TEXT,
            raw_html TEXT,
            raw_json TEXT,
            clean_status INTEGER NOT NULL DEFAULT 0,
            ai_scored INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO jobs__migrated (
            job_id, keyword, detail_url, title, salary_min, salary_max, salary_months,
            city, exp_years, education, date_posted, last_updated, days_since_update,
            company_name, company_size, company_verified, company_logo_exists,
            publisher_type, jd_text, jd_length, benefits_json, raw_html, raw_json,
            clean_status, ai_scored, created_at, updated_at
        )
        SELECT
            job_id, keyword, detail_url, title, salary_min, salary_max, salary_months,
            city, exp_years, education, date_posted, last_updated, days_since_update,
            company_name, company_size, company_verified, company_logo_exists,
            publisher_type, jd_text, jd_length, benefits_json, raw_html, raw_json,
            {_normalize_flag_value_sql('clean_status', ('1', 'success', 'cleaned', 'done', 'true', 'yes'))},
            {_normalize_flag_value_sql('ai_scored', ('1', 'success', 'scored', 'done', 'true', 'yes'))},
            created_at, updated_at
        FROM jobs
        """
    )
    conn.execute("DROP TABLE jobs")
    conn.execute("ALTER TABLE jobs__migrated RENAME TO jobs")


def _needs_jobs_cleaned_rebuild(columns: dict[str, sqlite3.Row]) -> bool:
    clean_status = columns.get("clean_status")
    score_status = columns.get("score_status")
    if not clean_status or not score_status:
        return False
    clean_type = (clean_status[2] or "").upper()
    clean_default = (clean_status[4] or "").strip("'\"")
    score_type = (score_status[2] or "").upper()
    score_default = (score_status[4] or "").strip("'\"")
    return (
        clean_type != "INTEGER"
        or clean_default != "1"
        or score_type != "INTEGER"
        or score_default != "0"
    )


def _rebuild_jobs_cleaned_table(conn: sqlite3.Connection) -> None:
    columns = _table_info(conn, "jobs_cleaned")
    has_benefits_json = "benefits_json" in columns
    benefits_column_sql = "benefits_json TEXT," if has_benefits_json else ""
    benefits_column_insert = "benefits_json," if has_benefits_json else ""
    benefits_column_select = "benefits_json," if has_benefits_json else ""
    hr_currently_online_select = (
        "COALESCE(hr_currently_online, 0)" if "hr_currently_online" in columns else "0"
    )
    company_name_norm_select = "company_name_norm" if "company_name_norm" in columns else "NULL"
    need_company_check_select = "COALESCE(need_company_check, 0)" if "need_company_check" in columns else "0"
    company_check_status_select = (
        "COALESCE(company_check_status, 'skip')" if "company_check_status" in columns else "'skip'"
    )
    company_check_reasons_select = (
        "COALESCE(company_check_reasons_json, '[]')"
        if "company_check_reasons_json" in columns
        else "'[]'"
    )

    conn.execute(
        f"""
        CREATE TABLE jobs_cleaned__migrated (
            job_id TEXT PRIMARY KEY,
            keyword TEXT,
            detail_url TEXT,
            title TEXT,
            salary_text_raw TEXT,
            salary_min INTEGER,
            salary_max INTEGER,
            salary_months INTEGER,
            salary_period TEXT,
            city TEXT,
            exp_years TEXT,
            education TEXT,
            date_posted TEXT,
            last_updated TEXT,
            days_since_update INTEGER,
            company_name TEXT,
            company_size TEXT,
            company_verified INTEGER,
            company_logo_exists INTEGER,
            hr_currently_online INTEGER NOT NULL DEFAULT 0,
            publisher_type TEXT,
            jd_text TEXT,
            jd_length INTEGER,
            company_name_norm TEXT,
            need_company_check INTEGER NOT NULL DEFAULT 0,
            company_check_status TEXT NOT NULL DEFAULT 'skip',
            company_check_reasons_json TEXT NOT NULL DEFAULT '[]',
            {benefits_column_sql}
            ai_input_json TEXT,
            quality_flags_json TEXT,
            source_updated_at TEXT,
            clean_status INTEGER NOT NULL DEFAULT 1,
            score_status INTEGER NOT NULL DEFAULT 0,
            cleaned_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO jobs_cleaned__migrated (
            job_id, keyword, detail_url, title, salary_text_raw, salary_min, salary_max,
            salary_months, salary_period, city, exp_years, education, date_posted,
            last_updated, days_since_update, company_name, company_size, company_verified,
            company_logo_exists, hr_currently_online, publisher_type, jd_text, jd_length, company_name_norm,
            need_company_check, company_check_status, company_check_reasons_json,
            {benefits_column_insert}
            ai_input_json, quality_flags_json, source_updated_at, clean_status,
            score_status, cleaned_at
        )
        SELECT
            job_id, keyword, detail_url, title, salary_text_raw, salary_min, salary_max,
            salary_months, salary_period, city, exp_years, education, date_posted,
            last_updated, days_since_update, company_name, company_size, company_verified,
            company_logo_exists, {hr_currently_online_select}, publisher_type, jd_text, jd_length,
            {company_name_norm_select},
            {need_company_check_select},
            {company_check_status_select},
            {company_check_reasons_select},
            {benefits_column_select}
            ai_input_json, quality_flags_json, source_updated_at,
            {_normalize_flag_value_sql('clean_status', ('1', 'success', 'cleaned', 'done', 'true', 'yes'))},
            {_normalize_flag_value_sql('score_status', ('1', 'success', 'scored', 'done', 'true', 'yes'))},
            cleaned_at
        FROM jobs_cleaned
        """
    )
    conn.execute("DROP TABLE jobs_cleaned")
    conn.execute("ALTER TABLE jobs_cleaned__migrated RENAME TO jobs_cleaned")


EDUCATION_KEYWORDS = (
    "学历不限",
    "大专",
    "本科",
    "统招本科",
    "硕士",
    "博士",
    "中专",
    "高中",
)

EXPERIENCE_KEYWORDS = (
    "经验不限",
    "应届",
    "在校",
    "1年以上",
    "1-3年",
    "3-5年",
    "5-10年",
    "10年以上",
)


@dataclass
class CleanedJob:
    payload: dict[str, Any]


COMPANY_CHECK_THRESHOLD = 1
JD_STRONG_RISK_KEYWORDS = (
    "带身份证",
    "毕业证原件",
    "先培训后上岗",
    "岗前培训",
    "定向培养",
    "考证补贴",
    "公司提供培训",
    "带薪培训",
    "无责任底薪",
    "纯绩效",
    "提成制",
    "底薪+提成",
    "异地招聘",
    "面试当场录用",
)

JD_MEDIUM_RISK_KEYWORDS = (
    "单休",
    "大小周",
    "偶尔加班",
    "追赶进度",
    "全情投入",
    "创业心态",
    "狼性团队",
    "挑战高薪",
    "薪资上不封顶",
    "合伙人",
    "股权激励",
    "储备干部",
    "管培生",
    "团队主管",
    "运营专员",
    "行政助理",
    "人事专员",
    "无需经验",
    "急招",
    "名额有限",
)

JD_WEAK_RISK_KEYWORDS = (
    "抗压能力强",
    "能吃苦",
    "有激情",
    "弹性工作",
    "面议",
    "创业公司",
    "快速发展中",
    "扁平化管理",
    "氛围年轻",
    "零食下午茶",
    "老板nice",
)

JD_RISK_SCORE_THRESHOLD = 3
JD_STRONG_RISK_SCORE = 3
JD_MEDIUM_RISK_SCORE = 2
JD_WEAK_RISK_SCORE = 1


def ensure_cleaned_table(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        job_columns = _table_info(conn, "jobs")
        if job_columns and "clean_status" not in job_columns:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN clean_status INTEGER NOT NULL DEFAULT 0"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs_cleaned (
                job_id TEXT PRIMARY KEY,
                keyword TEXT,
                detail_url TEXT,
                title TEXT,
                salary_text_raw TEXT,
                salary_min INTEGER,
                salary_max INTEGER,
                salary_months INTEGER,
                salary_period TEXT,
                city TEXT,
                exp_years TEXT,
                education TEXT,
                date_posted TEXT,
                last_updated TEXT,
                days_since_update INTEGER,
                company_name TEXT,
                company_size TEXT,
                company_verified INTEGER,
                company_logo_exists INTEGER,
                hr_currently_online INTEGER NOT NULL DEFAULT 0,
                publisher_type TEXT,
                jd_text TEXT,
                jd_length INTEGER,
                company_name_norm TEXT,
                need_company_check INTEGER NOT NULL DEFAULT 0,
                company_check_status TEXT NOT NULL DEFAULT 'skip',
                company_check_reasons_json TEXT NOT NULL DEFAULT '[]',
                ai_input_json TEXT,
                quality_flags_json TEXT,
                source_updated_at TEXT,
                clean_status INTEGER NOT NULL DEFAULT 1,
                score_status INTEGER NOT NULL DEFAULT 0,
                cleaned_at TEXT NOT NULL
            )
            """
        )
        existing_columns = _table_info(conn, "jobs_cleaned")
        if "clean_status" not in existing_columns:
            conn.execute(
                "ALTER TABLE jobs_cleaned ADD COLUMN clean_status INTEGER NOT NULL DEFAULT 1"
            )
        if "score_status" not in existing_columns:
            conn.execute(
                "ALTER TABLE jobs_cleaned ADD COLUMN score_status INTEGER NOT NULL DEFAULT 0"
            )
        if "hr_currently_online" not in existing_columns:
            conn.execute(
                "ALTER TABLE jobs_cleaned ADD COLUMN hr_currently_online INTEGER NOT NULL DEFAULT 0"
            )
        if "company_name_norm" not in existing_columns:
            conn.execute("ALTER TABLE jobs_cleaned ADD COLUMN company_name_norm TEXT")
        if "need_company_check" not in existing_columns:
            conn.execute(
                "ALTER TABLE jobs_cleaned ADD COLUMN need_company_check INTEGER NOT NULL DEFAULT 0"
            )
        if "company_check_status" not in existing_columns:
            conn.execute(
                "ALTER TABLE jobs_cleaned ADD COLUMN company_check_status TEXT NOT NULL DEFAULT 'skip'"
            )
        if "company_check_reasons_json" not in existing_columns:
            conn.execute(
                "ALTER TABLE jobs_cleaned ADD COLUMN company_check_reasons_json TEXT NOT NULL DEFAULT '[]'"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS company_enriched (
                company_name_norm TEXT PRIMARY KEY,
                company_name_raw TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT,
                query TEXT,
                zhihu_raw_results_json TEXT NOT NULL DEFAULT '[]',
                zhihu_filtered_results_json TEXT NOT NULL DEFAULT '[]',
                search_results_json TEXT NOT NULL DEFAULT '[]',
                negative_sentences_json TEXT NOT NULL DEFAULT '[]',
                risk_level TEXT,
                risk_reasons_json TEXT NOT NULL DEFAULT '[]',
                last_checked_at TEXT,
                expire_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        company_columns = _table_info(conn, "company_enriched")
        if "zhihu_raw_results_json" not in company_columns:
            conn.execute(
                "ALTER TABLE company_enriched ADD COLUMN zhihu_raw_results_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "zhihu_filtered_results_json" not in company_columns:
            conn.execute(
                "ALTER TABLE company_enriched ADD COLUMN zhihu_filtered_results_json TEXT NOT NULL DEFAULT '[]'"
            )
        conn.execute(
            f"""
            UPDATE jobs
            SET clean_status = {_normalize_flag_value_sql('clean_status', ('1', 'success', 'cleaned', 'done', 'true', 'yes'))}
            """
        )
        conn.execute(
            f"""
            UPDATE jobs_cleaned
            SET clean_status = {_normalize_flag_value_sql('clean_status', ('1', 'success', 'cleaned', 'done', 'true', 'yes'))},
                score_status = {_normalize_flag_value_sql('score_status', ('1', 'success', 'scored', 'done', 'true', 'yes'))}
            """
        )
        if _needs_jobs_rebuild(job_columns):
            _rebuild_jobs_table(conn)
        if _needs_jobs_cleaned_rebuild(existing_columns):
            _rebuild_jobs_cleaned_table(conn)
        conn.commit()


def run_cleaning(
    db_path: Path,
    *,
    keyword: Optional[str] = None,
    limit: Optional[int] = None,
    only_missing: bool = False,
) -> dict[str, int]:
    ensure_cleaned_table(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = _select_source_rows(conn, keyword=keyword, limit=limit, only_missing=only_missing)
        cleaned_count = 0
        for row in rows:
            cleaned = clean_job_row(dict(row))
            _upsert_cleaned_job(conn, cleaned.payload)
            _mark_job_clean_status(conn, cleaned.payload["job_id"], clean_status=1)
            cleaned_count += 1
        conn.commit()
    return {"selected": len(rows), "cleaned": cleaned_count}


def _select_source_rows(
    conn: sqlite3.Connection,
    *,
    keyword: Optional[str],
    limit: Optional[int],
    only_missing: bool,
) -> list[sqlite3.Row]:
    sql = """
        SELECT
            j.job_id,
            j.keyword,
            j.detail_url,
            j.title,
            j.salary_min,
            j.salary_max,
            j.salary_months,
            j.city,
            j.exp_years,
            j.education,
            j.date_posted,
            j.last_updated,
            j.days_since_update,
            j.company_name,
            j.company_size,
            j.company_verified,
            j.company_logo_exists,
            j.publisher_type,
            j.jd_text,
            j.jd_length,
            j.benefits_json,
            j.raw_html,
            j.raw_json,
            j.updated_at
        FROM jobs j
        WHERE j.raw_html IS NOT NULL
          AND TRIM(j.raw_html) <> ''
    """
    params: list[Any] = []

    if keyword:
        sql += " AND j.keyword = ?"
        params.append(keyword)

    if only_missing:
        sql += """
          AND NOT EXISTS (
              SELECT 1
              FROM jobs_cleaned c
              WHERE c.job_id = j.job_id
          )
        """

    sql += " ORDER BY j.updated_at DESC"

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    return conn.execute(sql, params).fetchall()


def clean_job_row(row: dict[str, Any]) -> CleanedJob:
    soup = BeautifulSoup(row.get("raw_html") or "", "lxml")
    raw_json = _load_raw_json(row.get("raw_json"))

    title = _first_non_empty(
        _clean_text(row.get("title")),
        _extract_title_from_html(soup),
    )
    salary_text = _extract_salary_text(soup)
    salary_info = _parse_salary_text(salary_text)
    properties = _extract_job_properties(soup)
    company_info = _extract_company_info(soup)
    jd_text = _first_non_empty(
        _clean_text(row.get("jd_text")),
        _extract_jd_text(soup),
    )
    jd_length = len(jd_text) if jd_text else 0

    date_posted = _normalize_date(row.get("date_posted"))
    last_updated = _normalize_date(
        _first_non_empty(row.get("last_updated"), properties.get("last_updated"))
    )
    days_since_update = _compute_days_since_update(last_updated)

    payload = {
        "job_id": row["job_id"],
        "keyword": row.get("keyword"),
        "detail_url": row.get("detail_url"),
        "title": title,
        "salary_text_raw": salary_text,
        "salary_min": _coalesce_int(row.get("salary_min"), salary_info.get("salary_min")),
        "salary_max": _coalesce_int(row.get("salary_max"), salary_info.get("salary_max")),
        "salary_months": _coalesce_int(row.get("salary_months"), salary_info.get("salary_months")),
        "salary_period": salary_info.get("salary_period"),
        "city": _first_non_empty(_clean_text(row.get("city")), properties.get("city")),
        "exp_years": _first_non_empty(_clean_text(row.get("exp_years")), properties.get("exp_years")),
        "education": _first_non_empty(_clean_text(row.get("education")), properties.get("education")),
        "date_posted": date_posted,
        "last_updated": last_updated,
        "days_since_update": days_since_update,
        "company_name": _first_non_empty(_clean_text(row.get("company_name")), company_info.get("company_name")),
        "company_size": _first_non_empty(_clean_text(row.get("company_size")), company_info.get("company_size")),
        "company_verified": int(bool(row.get("company_verified"))),
        "company_logo_exists": int(bool(row.get("company_logo_exists"))),
        "hr_currently_online": _extract_hr_currently_online(soup),
        "publisher_type": _clean_text(row.get("publisher_type")) or "unknown",
        "jd_text": jd_text,
        "jd_length": jd_length,
        "source_updated_at": row.get("updated_at"),
    }
    company_assessment = _assess_company_check_need(payload)
    payload["company_name_norm"] = company_assessment["company_name_norm"]
    payload["need_company_check"] = company_assessment["need_company_check"]
    payload["company_check_status"] = company_assessment["company_check_status"]
    payload["company_check_reasons_json"] = json.dumps(
        company_assessment["company_check_reasons"],
        ensure_ascii=False,
    )
    payload["quality_flags_json"] = json.dumps(_build_quality_flags(payload), ensure_ascii=False)
    payload["ai_input_json"] = json.dumps(_build_ai_input(payload), ensure_ascii=False)
    payload["clean_status"] = 1
    payload["score_status"] = 0
    payload["cleaned_at"] = datetime.utcnow().isoformat(timespec="seconds")
    return CleanedJob(payload=payload)


def _upsert_cleaned_job(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO jobs_cleaned (
            job_id, keyword, detail_url, title, salary_text_raw, salary_min, salary_max,
            salary_months, salary_period, city, exp_years, education, date_posted,
            last_updated, days_since_update, company_name, company_size, company_verified,
            company_logo_exists, hr_currently_online, publisher_type, jd_text, jd_length, company_name_norm,
            need_company_check, company_check_status, company_check_reasons_json,
            ai_input_json, quality_flags_json, source_updated_at, clean_status,
            score_status, cleaned_at
        ) VALUES (
            :job_id, :keyword, :detail_url, :title, :salary_text_raw, :salary_min, :salary_max,
            :salary_months, :salary_period, :city, :exp_years, :education, :date_posted,
            :last_updated, :days_since_update, :company_name, :company_size, :company_verified,
            :company_logo_exists, :hr_currently_online, :publisher_type, :jd_text, :jd_length, :company_name_norm,
            :need_company_check, :company_check_status, :company_check_reasons_json,
            :ai_input_json, :quality_flags_json, :source_updated_at, :clean_status,
            :score_status, :cleaned_at
        )
        ON CONFLICT(job_id) DO UPDATE SET
            keyword = excluded.keyword,
            detail_url = excluded.detail_url,
            title = excluded.title,
            salary_text_raw = excluded.salary_text_raw,
            salary_min = excluded.salary_min,
            salary_max = excluded.salary_max,
            salary_months = excluded.salary_months,
            salary_period = excluded.salary_period,
            city = excluded.city,
            exp_years = excluded.exp_years,
            education = excluded.education,
            date_posted = excluded.date_posted,
            last_updated = excluded.last_updated,
            days_since_update = excluded.days_since_update,
            company_name = excluded.company_name,
            company_size = excluded.company_size,
            company_verified = excluded.company_verified,
            company_logo_exists = excluded.company_logo_exists,
            hr_currently_online = excluded.hr_currently_online,
            publisher_type = excluded.publisher_type,
            jd_text = excluded.jd_text,
            jd_length = excluded.jd_length,
            company_name_norm = excluded.company_name_norm,
            need_company_check = excluded.need_company_check,
            company_check_status = excluded.company_check_status,
            company_check_reasons_json = excluded.company_check_reasons_json,
            ai_input_json = excluded.ai_input_json,
            quality_flags_json = excluded.quality_flags_json,
            source_updated_at = excluded.source_updated_at,
            clean_status = excluded.clean_status,
            score_status = excluded.score_status,
            cleaned_at = excluded.cleaned_at
        """,
        payload,
    )


def _mark_job_clean_status(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    clean_status: int,
) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET clean_status = ?,
            updated_at = ?
        WHERE job_id = ?
        """,
        (clean_status, datetime.utcnow().isoformat(timespec="seconds"), job_id),
    )


def _load_raw_json(raw_json: Any) -> dict[str, Any]:
    if not raw_json:
        return {}
    if isinstance(raw_json, dict):
        return raw_json
    try:
        return json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return {}


def _extract_title_from_html(soup: BeautifulSoup) -> Optional[str]:
    title_node = soup.select_one("h1") or soup.select_one("title")
    if not title_node:
        return None
    text = _clean_text(title_node.get_text(" ", strip=True))
    if not text:
        return None
    text = re.sub(r"\s*-\s*猎聘.*$", "", text).strip()
    text = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
    return text or None


def _extract_salary_text(soup: BeautifulSoup) -> Optional[str]:
    node = soup.select_one("span.salary")
    if not node:
        return None
    return _clean_text(node.get_text(" ", strip=True))


def _parse_salary_text(salary_text: Optional[str]) -> dict[str, Any]:
    if not salary_text:
        return {"salary_min": None, "salary_max": None, "salary_months": None, "salary_period": None}

    match = re.search(
        r"(?P<min>\d+(?:\.\d+)?)\s*-\s*(?P<max>\d+(?:\.\d+)?)\s*(?P<unit>[kKwW万])",
        salary_text,
    )
    months_match = re.search(r"(?P<months>\d{1,2})\s*薪", salary_text)

    salary_min = salary_max = None
    salary_period = None
    if match:
        min_value = float(match.group("min"))
        max_value = float(match.group("max"))
        unit = match.group("unit").lower()
        multiplier = 1000 if unit == "k" else 10000
        salary_min = int(min_value * multiplier)
        salary_max = int(max_value * multiplier)

        if "月" in salary_text or months_match:
            salary_period = "monthly"
        elif unit == "k" and max_value >= 100:
            salary_period = "annual"
        else:
            salary_period = "monthly"

    salary_months = int(months_match.group("months")) if months_match else None
    return {
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_months": salary_months,
        "salary_period": salary_period,
    }


def _extract_job_properties(soup: BeautifulSoup) -> dict[str, Optional[str]]:
    node = soup.select_one(".job-properties")
    if not node:
        return {"city": None, "exp_years": None, "education": None, "last_updated": None}

    tokens = [_clean_text(span.get_text(" ", strip=True)) for span in node.select("span")]
    tokens = [token for token in tokens if token and token != "|"]

    city = next((token for token in tokens if _looks_like_city(token)), None)
    exp_years = next((token for token in tokens if _looks_like_experience(token)), None)
    education = next((token for token in tokens if _looks_like_education(token)), None)
    last_updated = next((token for token in tokens if "更新" in token or re.search(r"\d{1,2}月\d{1,2}日", token)), None)

    if last_updated:
        last_updated = _normalize_cn_month_day(last_updated)

    return {
        "city": city,
        "exp_years": exp_years,
        "education": education,
        "last_updated": last_updated,
    }


def _extract_company_info(soup: BeautifulSoup) -> dict[str, Optional[str]]:
    box = soup.select_one(".job-detail-company-box") or soup.select_one(".job-company-info-box")
    if not box:
        return {"company_name": None, "company_size": None}

    company_name = None
    logo = box.select_one("img[alt]")
    if logo:
        company_name = _clean_text(logo.get("alt"))

    if not company_name:
        node = box.select_one(".company-name")
        if node:
            company_name = _clean_text(node.get_text(" ", strip=True))

    text = " ".join(box.get_text(" ", strip=True).split())
    size_match = re.search(r"(\d{1,5}(?:-\d{1,5})?人|10000人以上)", text)
    company_size = size_match.group(1) if size_match else None
    return {"company_name": company_name, "company_size": company_size}


def _extract_hr_currently_online(soup: BeautifulSoup) -> int:
    text = soup.get_text("\n", strip=True)
    return int("当前在线" in text)


def _extract_jd_text(soup: BeautifulSoup) -> str:
    for selector in (".job-intro-content", ".desc-box", ".content-word", ".job-description"):
        node = soup.select_one(selector)
        if node:
            return _clean_text(node.get_text("\n", strip=True))
    return ""


def _build_quality_flags(payload: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if not payload.get("salary_min") or not payload.get("salary_max"):
        flags.append("missing_salary")
    if not payload.get("salary_months"):
        flags.append("missing_salary_months")
    if not payload.get("company_size"):
        flags.append("missing_company_size")
    if not payload.get("jd_text") or payload.get("jd_length", 0) < 100:
        flags.append("short_jd")
    if not payload.get("last_updated"):
        flags.append("missing_last_updated")
    return flags


def _assess_company_check_need(payload: dict[str, Any]) -> dict[str, Any]:
    company_name = payload.get("company_name")
    company_name_norm = _normalize_company_name(payload.get("company_name"))
    if not company_name_norm:
        return {
            "company_name_norm": None,
            "need_company_check": 0,
            "company_check_status": "skip",
            "company_check_reasons": [],
        }
    if _should_skip_company_check_by_name(company_name):
        return {
            "company_name_norm": company_name_norm,
            "need_company_check": 0,
            "company_check_status": "skip",
            "company_check_reasons": [],
        }

    reasons: list[str] = []
    is_small_or_unknown = _is_small_or_unknown_company(payload.get("company_size"))
    if is_small_or_unknown:
        reasons.append("company_size_small_or_unknown")

    if _is_salary_abnormal_for_small_company(payload, is_small_or_unknown):
        reasons.append("salary_abnormal_for_small_company")

    jd_risk = _assess_jd_risk(payload.get("jd_text"))
    if jd_risk["score"] >= JD_RISK_SCORE_THRESHOLD:
        reasons.append("jd_risk_score_gte_3")

    if _is_job_posted_over_30d_and_hr_online(payload):
        reasons.append("job_posted_over_30d_and_hr_online")

    if _has_weak_company_identity(payload):
        reasons.append("weak_company_identity")

    need_company_check = int(len(reasons) >= COMPANY_CHECK_THRESHOLD)
    return {
        "company_name_norm": company_name_norm,
        "need_company_check": need_company_check,
        "company_check_status": "pending" if need_company_check else "skip",
        "company_check_reasons": reasons,
    }


def _should_skip_company_check_by_name(company_name: Any) -> bool:
    if not company_name:
        return False
    company_name_text = _clean_text(str(company_name))
    return any(keyword in company_name_text for keyword in COMPANY_CHECK_NAME_SKIP_KEYWORDS)


def _build_ai_input(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": payload.get("job_id"),
        "title": payload.get("title"),
        "salary_min": payload.get("salary_min"),
        "salary_max": payload.get("salary_max"),
        "salary_months": payload.get("salary_months"),
        "city": payload.get("city"),
        "exp_years": payload.get("exp_years"),
        "education": payload.get("education"),
        "date_posted": payload.get("date_posted"),
        "last_updated": payload.get("last_updated"),
        "days_since_update": payload.get("days_since_update"),
        "company_name": payload.get("company_name"),
        "company_size": payload.get("company_size"),
        "company_verified": bool(payload.get("company_verified")),
        "company_logo_exists": bool(payload.get("company_logo_exists")),
        "publisher_type": payload.get("publisher_type"),
        "jd_text": payload.get("jd_text"),
        "jd_length": payload.get("jd_length"),
    }


def _normalize_company_name(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    text = re.sub(r"[（(].*?[）)]", "", text)
    text = re.sub(
        r"(有限责任公司|股份有限公司|有限公司|集团有限公司|科技有限公司|信息技术有限公司)$",
        "",
        text,
    )
    text = re.sub(r"\s+", "", text).strip(" ,.-_")
    return text or None


def _is_small_or_unknown_company(company_size: Any) -> bool:
    text = _clean_text(company_size)
    if not text:
        return True
    upper_bound = _extract_company_size_upper_bound(text)
    if upper_bound is None:
        return True
    return upper_bound <= 100


def _extract_company_size_upper_bound(text: str) -> Optional[int]:
    range_match = re.search(r"(\d{1,5})\s*-\s*(\d{1,5})", text)
    if range_match:
        return int(range_match.group(2))
    plus_match = re.search(r"(\d{1,5})\s*人以上", text)
    if plus_match:
        return int(plus_match.group(1))
    single_match = re.search(r"(\d{1,5})", text)
    if single_match:
        return int(single_match.group(1))
    return None


def _estimate_annual_salary_max(payload: dict[str, Any]) -> Optional[int]:
    salary_max = _coalesce_int(payload.get("salary_max"))
    if not salary_max:
        return None
    salary_period = payload.get("salary_period")
    if salary_period == "annual":
        return salary_max
    salary_months = _coalesce_int(payload.get("salary_months")) or 12
    return salary_max * salary_months


def _is_salary_abnormal_for_small_company(
    payload: dict[str, Any],
    is_small_or_unknown: bool,
) -> bool:
    if not is_small_or_unknown:
        return False
    annual_salary_max = _estimate_annual_salary_max(payload)
    if annual_salary_max is None:
        return False
    return annual_salary_max >= 400000


def _is_job_posted_over_30d_and_hr_online(payload: dict[str, Any]) -> bool:
    if int(bool(payload.get("hr_currently_online"))) != 1:
        return False
    date_posted = payload.get("date_posted")
    if not date_posted:
        return False
    try:
        posted_days = (date.today() - date.fromisoformat(date_posted)).days
    except ValueError:
        return False
    return posted_days > 30


def _count_keyword_hits(jd_text: Any, keywords: tuple[str, ...]) -> int:
    text = _clean_text(jd_text) or ""
    return sum(1 for keyword in keywords if keyword in text)


def _assess_jd_risk(jd_text: Any) -> dict[str, int]:
    strong_hits = _count_keyword_hits(jd_text, JD_STRONG_RISK_KEYWORDS)
    medium_hits = _count_keyword_hits(jd_text, JD_MEDIUM_RISK_KEYWORDS)
    weak_hits = _count_keyword_hits(jd_text, JD_WEAK_RISK_KEYWORDS)
    score = (
        strong_hits * JD_STRONG_RISK_SCORE
        + medium_hits * JD_MEDIUM_RISK_SCORE
        + weak_hits * JD_WEAK_RISK_SCORE
    )
    return {
        "strong_hits": strong_hits,
        "medium_hits": medium_hits,
        "weak_hits": weak_hits,
        "score": score,
    }


def _has_weak_company_identity(payload: dict[str, Any]) -> bool:
    company_verified = int(bool(payload.get("company_verified")))
    company_logo_exists = int(bool(payload.get("company_logo_exists")))
    publisher_type = (payload.get("publisher_type") or "").strip().lower()
    return (
        company_verified == 0
        and company_logo_exists == 0
        and publisher_type in {"", "unknown", "other"}
    )


def _normalize_date(value: Any) -> Optional[str]:
    if not value:
        return None
    text = _clean_text(str(value))
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return text[:10]
    return None


def _normalize_cn_month_day(value: str) -> Optional[str]:
    match = re.search(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日", value)
    if not match:
        return None
    today = date.today()
    return f"{today.year:04d}-{int(match.group('month')):02d}-{int(match.group('day')):02d}"


def _compute_days_since_update(last_updated: Optional[str]) -> Optional[int]:
    if not last_updated:
        return None
    try:
        return (date.today() - date.fromisoformat(last_updated)).days
    except ValueError:
        return None


def _looks_like_city(text: str) -> bool:
    return bool(re.search(r"[市区县镇州省]-?[A-Za-z\u4e00-\u9fff]*", text))


def _looks_like_experience(text: str) -> bool:
    return any(keyword in text for keyword in EXPERIENCE_KEYWORDS) or "年" in text


def _looks_like_education(text: str) -> bool:
    return any(keyword in text for keyword in EDUCATION_KEYWORDS)


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _first_non_empty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value:
            return value
    return None


def _coalesce_int(*values: Any) -> Optional[int]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None
