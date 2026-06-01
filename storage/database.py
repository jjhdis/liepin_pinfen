import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


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


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        with closing(self.connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
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
                """
                CREATE TABLE IF NOT EXISTS crawl_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    keyword TEXT,
                    page_no INTEGER,
                    job_id TEXT,
                    status_code INTEGER,
                    latency_seconds REAL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scores (
                    job_id TEXT PRIMARY KEY,
                    score_activity INTEGER NOT NULL,
                    score_jd INTEGER NOT NULL,
                    score_company INTEGER NOT NULL,
                    score_salary INTEGER NOT NULL,
                    score_other INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    verdict TEXT NOT NULL,
                    red_flags_json TEXT NOT NULL,
                    reasoning TEXT NOT NULL,
                    score_source TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    score_status TEXT NOT NULL,
                    raw_response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    scored_at TEXT NOT NULL
                )
                """
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
            job_columns = _table_info(conn, "jobs")
            if "clean_status" not in job_columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN clean_status INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                f"""
                UPDATE jobs
                SET clean_status = {_normalize_flag_value_sql('clean_status', ('1', 'success', 'cleaned', 'done', 'true', 'yes'))}
                """
            )
            if "ai_scored" in job_columns:
                conn.execute(
                    f"""
                    UPDATE jobs
                    SET ai_scored = {_normalize_flag_value_sql('ai_scored', ('1', 'success', 'scored', 'done', 'true', 'yes'))}
                    """
                )
            if _needs_jobs_rebuild(job_columns):
                _rebuild_jobs_table(conn)

            cleaned_columns = _table_info(conn, "jobs_cleaned")
            if cleaned_columns:
                if "clean_status" not in cleaned_columns:
                    conn.execute(
                        "ALTER TABLE jobs_cleaned ADD COLUMN clean_status INTEGER NOT NULL DEFAULT 1"
                    )
                if "score_status" not in cleaned_columns:
                    conn.execute(
                        "ALTER TABLE jobs_cleaned ADD COLUMN score_status INTEGER NOT NULL DEFAULT 0"
                    )
                if "hr_currently_online" not in cleaned_columns:
                    conn.execute(
                        "ALTER TABLE jobs_cleaned ADD COLUMN hr_currently_online INTEGER NOT NULL DEFAULT 0"
                    )
                if "company_name_norm" not in cleaned_columns:
                    conn.execute("ALTER TABLE jobs_cleaned ADD COLUMN company_name_norm TEXT")
                if "need_company_check" not in cleaned_columns:
                    conn.execute(
                        "ALTER TABLE jobs_cleaned ADD COLUMN need_company_check INTEGER NOT NULL DEFAULT 0"
                    )
                if "company_check_status" not in cleaned_columns:
                    conn.execute(
                        "ALTER TABLE jobs_cleaned ADD COLUMN company_check_status TEXT NOT NULL DEFAULT 'skip'"
                    )
                if "company_check_reasons_json" not in cleaned_columns:
                    conn.execute(
                        "ALTER TABLE jobs_cleaned ADD COLUMN company_check_reasons_json TEXT NOT NULL DEFAULT '[]'"
                    )
                conn.execute(
                    f"""
                    UPDATE jobs_cleaned
                    SET clean_status = {_normalize_flag_value_sql('clean_status', ('1', 'success', 'cleaned', 'done', 'true', 'yes'))},
                        score_status = {_normalize_flag_value_sql('score_status', ('1', 'success', 'scored', 'done', 'true', 'yes'))}
                    """
                )
                if _needs_jobs_cleaned_rebuild(cleaned_columns):
                    _rebuild_jobs_cleaned_table(conn)
            company_columns = _table_info(conn, "company_enriched")
            if "zhihu_raw_results_json" not in company_columns:
                conn.execute(
                    "ALTER TABLE company_enriched ADD COLUMN zhihu_raw_results_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "zhihu_filtered_results_json" not in company_columns:
                conn.execute(
                    "ALTER TABLE company_enriched ADD COLUMN zhihu_filtered_results_json TEXT NOT NULL DEFAULT '[]'"
                )
            conn.commit()

    def job_exists(self, job_id: str) -> bool:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM jobs
                WHERE job_id = ?
                  AND title IS NOT NULL
                  AND TRIM(title) <> ''
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        return row is not None

    def insert_job_stub(self, *, job_id: str, keyword: str, detail_url: str) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, keyword, detail_url, title, benefits_json, raw_json,
                    clean_status, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, '[]', '{}', 0, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    keyword = excluded.keyword,
                    detail_url = excluded.detail_url,
                    clean_status = 0,
                    updated_at = excluded.updated_at
                """,
                (job_id, keyword, detail_url, now, now),
            )
            conn.commit()

    def get_pending_jobs(self, *, keyword: Optional[str], limit: int) -> list[dict[str, Any]]:
        sql = """
            SELECT job_id, keyword, detail_url
            FROM jobs
            WHERE title IS NULL OR TRIM(title) = ''
        """
        params: list[Any] = []

        if keyword:
            sql += " AND keyword = ?"
            params.append(keyword)

        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        with closing(self.connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def pending_job_count(self, *, keyword: Optional[str] = None) -> int:
        sql = """
            SELECT COUNT(*)
            FROM jobs
            WHERE title IS NULL OR TRIM(title) = ''
        """
        params: list[Any] = []

        if keyword:
            sql += " AND keyword = ?"
            params.append(keyword)

        with closing(self.connect()) as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def get_jobs_ready_for_scoring(
        self,
        *,
        keyword: Optional[str],
        limit: int,
        max_days_since_update: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT
                c.job_id,
                c.keyword,
                c.last_updated,
                c.days_since_update,
                c.company_name_norm,
                c.ai_input_json,
                c.quality_flags_json,
                c.clean_status,
                c.score_status,
                ce.risk_level AS company_risk_level,
                ce.zhihu_filtered_results_json
            FROM jobs_cleaned c
            LEFT JOIN scores s ON s.job_id = c.job_id
            LEFT JOIN company_enriched ce ON ce.company_name_norm = c.company_name_norm
            WHERE c.ai_input_json IS NOT NULL
              AND TRIM(c.ai_input_json) <> ''
              AND c.clean_status = 1
              AND (
                  c.score_status IS NULL
                  OR c.score_status <> 1
              )
        """
        params: list[Any] = []

        if keyword:
            sql += " AND c.keyword = ?"
            params.append(keyword)

        if max_days_since_update is not None:
            sql += """
              AND c.last_updated IS NOT NULL
              AND c.days_since_update IS NOT NULL
              AND c.days_since_update <= ?
            """
            params.append(max_days_since_update)

        sql += " ORDER BY c.cleaned_at ASC LIMIT ?"
        params.append(limit)

        with closing(self.connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def ready_for_scoring_count(
        self,
        *,
        keyword: Optional[str] = None,
        max_days_since_update: Optional[int] = None,
    ) -> int:
        sql = """
            SELECT COUNT(*)
            FROM jobs_cleaned c
            LEFT JOIN scores s ON s.job_id = c.job_id
            WHERE c.ai_input_json IS NOT NULL
              AND TRIM(c.ai_input_json) <> ''
              AND c.clean_status = 1
              AND (
                  c.score_status IS NULL
                  OR c.score_status <> 1
              )
        """
        params: list[Any] = []
        if keyword:
            sql += " AND c.keyword = ?"
            params.append(keyword)

        if max_days_since_update is not None:
            sql += """
              AND c.last_updated IS NOT NULL
              AND c.days_since_update IS NOT NULL
              AND c.days_since_update <= ?
            """
            params.append(max_days_since_update)

        with closing(self.connect()) as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def get_companies_ready_for_enrichment(
        self,
        *,
        keyword: Optional[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT
                company_name_norm,
                MIN(company_name) AS company_name_raw,
                MIN(keyword) AS keyword
            FROM jobs_cleaned
            WHERE need_company_check = 1
              AND company_check_status = 'pending'
              AND company_name_norm IS NOT NULL
              AND TRIM(company_name_norm) <> ''
        """
        params: list[Any] = []
        if keyword:
            sql += " AND keyword = ?"
            params.append(keyword)

        sql += """
            GROUP BY company_name_norm
            ORDER BY MIN(cleaned_at) ASC
            LIMIT ?
        """
        params.append(limit)

        with closing(self.connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_company_enriched(self, company_name_norm: str) -> Optional[dict[str, Any]]:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM company_enriched
                WHERE company_name_norm = ?
                LIMIT 1
                """,
                (company_name_norm,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_company_enriched(self, payload: dict[str, Any]) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        record = {
            "company_name_norm": payload["company_name_norm"],
            "company_name_raw": payload.get("company_name_raw"),
            "status": payload.get("status", "done"),
            "source": payload.get("source"),
            "query": payload.get("query"),
            "zhihu_raw_results_json": json.dumps(
                payload.get("zhihu_raw_results", []), ensure_ascii=False
            ),
            "zhihu_filtered_results_json": json.dumps(
                payload.get("zhihu_filtered_results", []), ensure_ascii=False
            ),
            "search_results_json": json.dumps(
                payload.get("search_results", []), ensure_ascii=False
            ),
            "negative_sentences_json": json.dumps(
                payload.get("negative_sentences", []), ensure_ascii=False
            ),
            "risk_level": payload.get("risk_level"),
            "risk_reasons_json": json.dumps(
                payload.get("risk_reasons", []), ensure_ascii=False
            ),
            "last_checked_at": payload.get("last_checked_at", now),
            "expire_at": payload.get("expire_at"),
            "created_at": now,
            "updated_at": now,
        }

        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO company_enriched (
                    company_name_norm, company_name_raw, status, source, query,
                    zhihu_raw_results_json, zhihu_filtered_results_json,
                    search_results_json, negative_sentences_json, risk_level,
                    risk_reasons_json, last_checked_at, expire_at, created_at, updated_at
                ) VALUES (
                    :company_name_norm, :company_name_raw, :status, :source, :query,
                    :zhihu_raw_results_json, :zhihu_filtered_results_json,
                    :search_results_json, :negative_sentences_json, :risk_level,
                    :risk_reasons_json, :last_checked_at, :expire_at, :created_at, :updated_at
                )
                ON CONFLICT(company_name_norm) DO UPDATE SET
                    company_name_raw = excluded.company_name_raw,
                    status = excluded.status,
                    source = excluded.source,
                    query = excluded.query,
                    zhihu_raw_results_json = excluded.zhihu_raw_results_json,
                    zhihu_filtered_results_json = excluded.zhihu_filtered_results_json,
                    search_results_json = excluded.search_results_json,
                    negative_sentences_json = excluded.negative_sentences_json,
                    risk_level = excluded.risk_level,
                    risk_reasons_json = excluded.risk_reasons_json,
                    last_checked_at = excluded.last_checked_at,
                    expire_at = excluded.expire_at,
                    updated_at = excluded.updated_at
                """,
                record,
            )
            conn.commit()

    def update_company_check_status(
        self,
        company_name_norm: str,
        *,
        status: str,
    ) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE jobs_cleaned
                SET company_check_status = ?
                WHERE company_name_norm = ?
                """,
                (status, company_name_norm),
            )
            conn.commit()

    def upsert_job(self, job: dict[str, Any]) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        benefits = job.get("benefits")

        payload = {
            "job_id": job["job_id"],
            "keyword": job.get("keyword"),
            "detail_url": job.get("detail_url"),
            "title": job.get("title"),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "salary_months": job.get("salary_months"),
            "city": job.get("city"),
            "exp_years": job.get("exp_years"),
            "education": job.get("education"),
            "date_posted": job.get("date_posted"),
            "last_updated": job.get("last_updated"),
            "days_since_update": job.get("days_since_update"),
            "company_name": job.get("company_name"),
            "company_size": job.get("company_size"),
            "company_verified": int(bool(job.get("company_verified"))),
            "company_logo_exists": int(bool(job.get("company_logo_exists"))),
            "publisher_type": job.get("publisher_type"),
            "jd_text": job.get("jd_text"),
            "jd_length": job.get("jd_length"),
            "benefits_json": json.dumps(benefits or [], ensure_ascii=False),
            "raw_html": job.get("raw_html"),
            "raw_json": json.dumps(job, ensure_ascii=False),
            "clean_status": 0,
            "created_at": now,
            "updated_at": now,
        }

        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, keyword, detail_url, title, salary_min, salary_max,
                    salary_months, city, exp_years, education, date_posted,
                    last_updated, days_since_update, company_name, company_size,
                    company_verified, company_logo_exists, publisher_type,
                    jd_text, jd_length, benefits_json, raw_html, raw_json, clean_status,
                    created_at, updated_at
                ) VALUES (
                    :job_id, :keyword, :detail_url, :title, :salary_min, :salary_max,
                    :salary_months, :city, :exp_years, :education, :date_posted,
                    :last_updated, :days_since_update, :company_name, :company_size,
                    :company_verified, :company_logo_exists, :publisher_type,
                    :jd_text, :jd_length, :benefits_json, :raw_html, :raw_json, :clean_status,
                    :created_at, :updated_at
                )
                ON CONFLICT(job_id) DO UPDATE SET
                    keyword = excluded.keyword,
                    detail_url = excluded.detail_url,
                    title = excluded.title,
                    salary_min = excluded.salary_min,
                    salary_max = excluded.salary_max,
                    salary_months = excluded.salary_months,
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
                    publisher_type = excluded.publisher_type,
                    jd_text = excluded.jd_text,
                    jd_length = excluded.jd_length,
                    benefits_json = excluded.benefits_json,
                    raw_html = excluded.raw_html,
                    raw_json = excluded.raw_json,
                    clean_status = excluded.clean_status,
                    updated_at = excluded.updated_at
                """
                ,
                payload,
            )
            conn.commit()

    def log_crawl(
        self,
        *,
        url: str,
        keyword: Optional[str],
        page_no: Optional[int],
        job_id: Optional[str],
        status_code: Optional[int],
        latency_seconds: Optional[float],
        retry_count: int,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO crawl_log (
                    url, keyword, page_no, job_id, status_code, latency_seconds,
                    retry_count, success, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    keyword,
                    page_no,
                    job_id,
                    status_code,
                    latency_seconds,
                    retry_count,
                    int(success),
                    error_message,
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()

    def upsert_score(self, score: dict[str, Any]) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        payload = {
            "job_id": score["job_id"],
            "score_activity": int(score["score_activity"]),
            "score_jd": int(score["score_jd"]),
            "score_company": int(score["score_company"]),
            "score_salary": int(score["score_salary"]),
            "score_other": int(score["score_other"]),
            "total": int(score["total"]),
            "verdict": score["verdict"],
            "red_flags_json": json.dumps(score.get("red_flags", []), ensure_ascii=False),
            "reasoning": score["reasoning"],
            "score_source": score.get("score_source", "ai"),
            "model_name": score.get("model_name", ""),
            "prompt_version": score.get("prompt_version", ""),
            "score_status": score.get("score_status", "success"),
            "raw_response_json": json.dumps(score.get("raw_response", {}), ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
            "scored_at": score.get("scored_at", now),
        }

        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO scores (
                    job_id, score_activity, score_jd, score_company, score_salary,
                    score_other, total, verdict, red_flags_json, reasoning,
                    score_source, model_name, prompt_version, score_status,
                    raw_response_json, created_at, updated_at, scored_at
                ) VALUES (
                    :job_id, :score_activity, :score_jd, :score_company, :score_salary,
                    :score_other, :total, :verdict, :red_flags_json, :reasoning,
                    :score_source, :model_name, :prompt_version, :score_status,
                    :raw_response_json, :created_at, :updated_at, :scored_at
                )
                ON CONFLICT(job_id) DO UPDATE SET
                    score_activity = excluded.score_activity,
                    score_jd = excluded.score_jd,
                    score_company = excluded.score_company,
                    score_salary = excluded.score_salary,
                    score_other = excluded.score_other,
                    total = excluded.total,
                    verdict = excluded.verdict,
                    red_flags_json = excluded.red_flags_json,
                    reasoning = excluded.reasoning,
                    score_source = excluded.score_source,
                    model_name = excluded.model_name,
                    prompt_version = excluded.prompt_version,
                    score_status = excluded.score_status,
                    raw_response_json = excluded.raw_response_json,
                    updated_at = excluded.updated_at,
                    scored_at = excluded.scored_at
                """,
                payload,
            )
            conn.execute(
                """
                UPDATE jobs
                SET ai_scored = 1,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (now, score["job_id"]),
            )
            conn.execute(
                """
                UPDATE jobs_cleaned
                SET score_status = 1
                WHERE job_id = ?
                """,
                (score["job_id"],),
            )
            conn.commit()

    def mark_job_cleaned(self, job_id: str, *, clean_status: int = 1) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET clean_status = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (clean_status, datetime.utcnow().isoformat(timespec="seconds"), job_id),
            )
            conn.commit()
