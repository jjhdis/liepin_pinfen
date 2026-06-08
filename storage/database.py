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
    detail_status = columns.get("detail_status")
    detail_error_message = columns.get("detail_error_message")
    detail_last_attempt_at = columns.get("detail_last_attempt_at")
    if not clean_status:
        return False
    column_type = (clean_status[2] or "").upper()
    default_value = (clean_status[4] or "").strip("'\"")
    return (
        column_type != "INTEGER"
        or default_value != "0"
        or detail_status is None
        or detail_error_message is None
        or detail_last_attempt_at is None
    )


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
            detail_status TEXT NOT NULL DEFAULT 'pending',
            detail_error_message TEXT,
            detail_last_attempt_at TEXT,
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
            detail_status, detail_error_message, detail_last_attempt_at,
            clean_status, ai_scored, created_at, updated_at
        )
        SELECT
            job_id, keyword, detail_url, title, salary_min, salary_max, salary_months,
            city, exp_years, education, date_posted, last_updated, days_since_update,
            company_name, company_size, company_verified, company_logo_exists,
            publisher_type, jd_text, jd_length, benefits_json, raw_html, raw_json,
            COALESCE(detail_status, CASE WHEN title IS NOT NULL AND TRIM(title) <> '' THEN 'success' ELSE 'pending' END),
            detail_error_message,
            detail_last_attempt_at,
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
                    detail_status TEXT NOT NULL DEFAULT 'pending',
                    detail_error_message TEXT,
                    detail_last_attempt_at TEXT,
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
                    cookie_profile_name TEXT,
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS account_message_status (
                    platform TEXT NOT NULL,
                    cookie_profile_id TEXT NOT NULL,
                    account_label TEXT,
                    cookie_file TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    has_unread INTEGER NOT NULL DEFAULT 0,
                    unread_total INTEGER NOT NULL DEFAULT 0,
                    contact_total INTEGER NOT NULL DEFAULT 0,
                    latest_contact_name TEXT,
                    latest_contact_company TEXT,
                    latest_msg_time TEXT,
                    checked_at TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (platform, cookie_profile_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_contacts (
                    platform TEXT NOT NULL,
                    cookie_profile_id TEXT NOT NULL,
                    account_label TEXT,
                    cookie_file TEXT,
                    contact_id TEXT NOT NULL,
                    name TEXT,
                    company TEXT,
                    user_tag TEXT,
                    title TEXT,
                    photo TEXT,
                    home_page TEXT,
                    latest_msg_id TEXT,
                    latest_msg_type TEXT,
                    last_payload_json TEXT,
                    last_message_preview TEXT,
                    unread_cnt INTEGER NOT NULL DEFAULT 0,
                    latest_msg_time TEXT,
                    user_id TEXT,
                    im_user_type TEXT,
                    opposite_user_id TEXT,
                    im_id TEXT,
                    opposite_im_id TEXT,
                    opposite_im_user_type TEXT,
                    chat_type TEXT,
                    direction TEXT,
                    contact INTEGER NOT NULL DEFAULT 1,
                    checked_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (platform, cookie_profile_id, contact_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_runs (
                    task_id      TEXT PRIMARY KEY,
                    platform     TEXT NOT NULL,
                    task_type    TEXT NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'queued',
                    keyword      TEXT,
                    profile_name TEXT,
                    pid          INTEGER,
                    priority     INTEGER NOT NULL DEFAULT 0,
                    parent_task_id TEXT,
                    progress_json TEXT,
                    started_at   TEXT NOT NULL,
                    finished_at  TEXT,
                    result_json  TEXT,
                    error_message TEXT,
                    created_at   TEXT NOT NULL
                )
                """
            )
            # Migrate existing task_runs table
            task_runs_cols = _table_info(conn, "task_runs")
            if "priority" not in task_runs_cols:
                conn.execute("ALTER TABLE task_runs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
            if "parent_task_id" not in task_runs_cols:
                conn.execute("ALTER TABLE task_runs ADD COLUMN parent_task_id TEXT")
            if "progress_json" not in task_runs_cols:
                conn.execute("ALTER TABLE task_runs ADD COLUMN progress_json TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cookie_profiles (
                    platform TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    last_used_at TEXT,
                    detail_count_today INTEGER NOT NULL DEFAULT 0,
                    detail_total_count INTEGER NOT NULL DEFAULT 0,
                    cooldown_until TEXT,
                    last_error TEXT,
                    last_error_at TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (platform, profile_name)
                )
                """
            )
            job_columns = _table_info(conn, "jobs")
            if "detail_status" not in job_columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN detail_status TEXT NOT NULL DEFAULT 'pending'"
                )
            if "detail_error_message" not in job_columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN detail_error_message TEXT")
            if "detail_last_attempt_at" not in job_columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN detail_last_attempt_at TEXT")
            if "clean_status" not in job_columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN clean_status INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                UPDATE jobs
                SET detail_status = CASE
                    WHEN title IS NOT NULL AND TRIM(title) <> '' THEN 'success'
                    WHEN detail_status IS NULL OR TRIM(detail_status) = '' THEN 'pending'
                    ELSE detail_status
                END
                """
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

            crawl_log_columns = _table_info(conn, "crawl_log")
            if "cookie_profile_name" not in crawl_log_columns:
                if "cookie_profile_id" in crawl_log_columns:
                    conn.execute("ALTER TABLE crawl_log RENAME COLUMN cookie_profile_id TO cookie_profile_name")
                else:
                    conn.execute("ALTER TABLE crawl_log ADD COLUMN cookie_profile_name TEXT")

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
                    detail_status, detail_error_message, detail_last_attempt_at,
                    clean_status, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, '[]', '{}', 'pending', NULL, NULL, 0, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    keyword = excluded.keyword,
                    detail_url = excluded.detail_url,
                    detail_status = CASE
                        WHEN jobs.title IS NOT NULL AND TRIM(jobs.title) <> '' THEN jobs.detail_status
                        ELSE 'pending'
                    END,
                    detail_error_message = CASE
                        WHEN jobs.title IS NOT NULL AND TRIM(jobs.title) <> '' THEN jobs.detail_error_message
                        ELSE NULL
                    END,
                    detail_last_attempt_at = CASE
                        WHEN jobs.title IS NOT NULL AND TRIM(jobs.title) <> '' THEN jobs.detail_last_attempt_at
                        ELSE NULL
                    END,
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
            WHERE detail_status = 'pending'
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
            WHERE detail_status = 'pending'
        """
        params: list[Any] = []

        if keyword:
            sql += " AND keyword = ?"
            params.append(keyword)

        with closing(self.connect()) as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def ready_for_clean_count(self, *, keyword: Optional[str] = None) -> int:
        """Count detail-scraped jobs that haven't been cleaned yet."""
        sql = """
            SELECT COUNT(*)
            FROM jobs
            WHERE detail_status = 'success'
              AND clean_status = 0
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
              AND (
                  COALESCE(c.need_company_check, 0) = 0
                  OR COALESCE(c.company_check_status, 'skip') != 'pending'
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
              AND (
                  COALESCE(c.need_company_check, 0) = 0
                  OR COALESCE(c.company_check_status, 'skip') != 'pending'
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
            "detail_status": "success",
            "detail_error_message": None,
            "detail_last_attempt_at": now,
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
                    jd_text, jd_length, benefits_json, raw_html, raw_json,
                    detail_status, detail_error_message, detail_last_attempt_at, clean_status,
                    created_at, updated_at
                ) VALUES (
                    :job_id, :keyword, :detail_url, :title, :salary_min, :salary_max,
                    :salary_months, :city, :exp_years, :education, :date_posted,
                    :last_updated, :days_since_update, :company_name, :company_size,
                    :company_verified, :company_logo_exists, :publisher_type,
                    :jd_text, :jd_length, :benefits_json, :raw_html, :raw_json,
                    :detail_status, :detail_error_message, :detail_last_attempt_at, :clean_status,
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
                    detail_status = excluded.detail_status,
                    detail_error_message = excluded.detail_error_message,
                    detail_last_attempt_at = excluded.detail_last_attempt_at,
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
        cookie_profile_name: Optional[str] = None,
    ) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO crawl_log (
                    url, keyword, page_no, job_id, status_code, latency_seconds,
                    retry_count, success, error_message, cookie_profile_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    cookie_profile_name,
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

    def update_detail_status(
        self,
        job_id: str,
        *,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET detail_status = ?,
                    detail_error_message = ?,
                    detail_last_attempt_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (status, error_message, now, now, job_id),
            )
            conn.commit()

    def delete_job(self, job_id: str) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                DELETE FROM scores
                WHERE job_id = ?
                """,
                (job_id,),
            )
            conn.execute(
                """
                DELETE FROM jobs_cleaned
                WHERE job_id = ?
                """,
                (job_id,),
            )
            conn.execute(
                """
                DELETE FROM jobs
                WHERE job_id = ?
                """,
                (job_id,),
            )
            conn.commit()

    def delete_raw_job(self, job_id: str) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                DELETE FROM jobs
                WHERE job_id = ?
                """,
                (job_id,),
            )
            conn.commit()

    def upsert_account_message_status(self, payload: dict[str, Any]) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        record = {
            "platform": payload["platform"],
            "cookie_profile_id": payload["cookie_profile_id"],
            "account_label": payload.get("account_label"),
            "cookie_file": payload.get("cookie_file"),
            "status": payload.get("status", "success"),
            "has_unread": int(bool(payload.get("has_unread"))),
            "unread_total": int(payload.get("unread_total") or 0),
            "contact_total": int(payload.get("contact_total") or 0),
            "latest_contact_name": payload.get("latest_contact_name"),
            "latest_contact_company": payload.get("latest_contact_company"),
            "latest_msg_time": payload.get("latest_msg_time"),
            "checked_at": payload.get("checked_at", now),
            "error_message": payload.get("error_message"),
            "created_at": now,
            "updated_at": now,
        }

        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO account_message_status (
                    platform, cookie_profile_id, account_label, cookie_file,
                    status, has_unread, unread_total, contact_total,
                    latest_contact_name, latest_contact_company, latest_msg_time,
                    checked_at, error_message, created_at, updated_at
                ) VALUES (
                    :platform, :cookie_profile_id, :account_label, :cookie_file,
                    :status, :has_unread, :unread_total, :contact_total,
                    :latest_contact_name, :latest_contact_company, :latest_msg_time,
                    :checked_at, :error_message, :created_at, :updated_at
                )
                ON CONFLICT(platform, cookie_profile_id) DO UPDATE SET
                    account_label = excluded.account_label,
                    cookie_file = excluded.cookie_file,
                    status = excluded.status,
                    has_unread = excluded.has_unread,
                    unread_total = excluded.unread_total,
                    contact_total = excluded.contact_total,
                    latest_contact_name = excluded.latest_contact_name,
                    latest_contact_company = excluded.latest_contact_company,
                    latest_msg_time = excluded.latest_msg_time,
                    checked_at = excluded.checked_at,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                record,
            )
            conn.commit()

    def replace_message_contacts(
        self,
        *,
        platform: str,
        cookie_profile_id: str,
        account_label: Optional[str],
        cookie_file: Optional[str],
        contacts: list[dict[str, Any]],
        checked_at: str,
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute(
                """
                DELETE FROM message_contacts
                WHERE platform = ?
                  AND cookie_profile_id = ?
                """,
                (platform, cookie_profile_id),
            )

            for item in contacts:
                conn.execute(
                    """
                    INSERT INTO message_contacts (
                        platform, cookie_profile_id, account_label, cookie_file,
                        contact_id, name, company, user_tag, title, photo, home_page,
                        latest_msg_id, latest_msg_type, last_payload_json, last_message_preview,
                        unread_cnt, latest_msg_time, user_id, im_user_type, opposite_user_id,
                        im_id, opposite_im_id, opposite_im_user_type, chat_type, direction,
                        contact, checked_at, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        platform,
                        cookie_profile_id,
                        account_label,
                        cookie_file,
                        item.get("contact_id"),
                        item.get("name"),
                        item.get("company"),
                        item.get("user_tag"),
                        item.get("title"),
                        item.get("photo"),
                        item.get("home_page"),
                        item.get("latest_msg_id"),
                        item.get("latest_msg_type"),
                        item.get("last_payload_json"),
                        item.get("last_message_preview"),
                        int(item.get("unread_cnt") or 0),
                        item.get("latest_msg_time"),
                        item.get("user_id"),
                        item.get("im_user_type"),
                        item.get("opposite_user_id"),
                        item.get("im_id"),
                        item.get("opposite_im_id"),
                        item.get("opposite_im_user_type"),
                        item.get("chat_type"),
                        item.get("direction"),
                        int(bool(item.get("contact"))),
                        checked_at,
                        now,
                        now,
                    ),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # cookie_profiles
    # ------------------------------------------------------------------

    def upsert_cookie_profile(
        self,
        *,
        platform: str,
        profile_name: str,
        status: str = "ready",
        notes: str = "",
        updated_at: str,
        reset_counters: bool = False,
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        counter_sql = (
            ", detail_count_today = 0, detail_total_count = 0"
            if reset_counters
            else ""
        )
        with closing(self.connect()) as conn:
            conn.execute(
                f"""
                INSERT INTO cookie_profiles (
                    platform, profile_name, status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, profile_name) DO UPDATE SET
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                    {counter_sql}
                """,
                (platform, profile_name, status, notes, now, updated_at),
            )
            conn.commit()

    def increment_cookie_usage(
        self,
        platform: str,
        profile_name: str,
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE cookie_profiles
                SET last_used_at = ?,
                    detail_count_today = CASE
                        WHEN DATE(last_used_at) < DATE(?) THEN 1
                        ELSE detail_count_today + 1
                    END,
                    detail_total_count = detail_total_count + 1,
                    updated_at = ?
                WHERE platform = ? AND profile_name = ?
                """,
                (now, now, now, platform, profile_name),
            )
            conn.commit()

    def update_cookie_profile_status(
        self,
        platform: str,
        profile_name: str,
        *,
        status: str,
        last_error: str = "",
        last_error_at: str = "",
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE cookie_profiles
                SET status = ?,
                    last_error = ?,
                    last_error_at = ?,
                    updated_at = ?
                WHERE platform = ? AND profile_name = ?
                """,
                (status, last_error, last_error_at, now, platform, profile_name),
            )
            conn.commit()

    def get_ready_cookie_profiles(
        self, platform: str
    ) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM cookie_profiles
                WHERE platform = ? AND status = 'ready'
                ORDER BY profile_name
                """,
                (platform,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_usable_cookie_profiles(
        self,
        platform: str,
        *,
        daily_max: int = 0,
    ) -> list[dict[str, Any]]:
        """Return profiles that are ready OR cooldown-expired, ordered by priority.

        Priority: ready > cooldown (expired), then least used today, then
        least recently used.  Excludes profiles over ``daily_max`` when > 0.
        """
        sql = """
            SELECT *
            FROM cookie_profiles
            WHERE platform = ?
              AND status IN ('ready', 'cooldown')
              AND (status = 'ready' OR cooldown_until <= datetime('now'))
        """
        params: list[Any] = [platform]

        if daily_max > 0:
            sql += " AND detail_count_today < ?"
            params.append(daily_max)

        sql += """
            ORDER BY
              CASE status WHEN 'ready' THEN 0 WHEN 'cooldown' THEN 1 END,
              detail_count_today ASC,
              last_used_at ASC
        """
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def mark_cookie_cooldown(
        self,
        platform: str,
        profile_name: str,
        *,
        hours: int = 2,
    ) -> None:
        """Set a cookie profile into cooldown for *hours* hours."""
        now = datetime.utcnow().isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE cookie_profiles
                SET status = 'cooldown',
                    cooldown_until = datetime('now', ?),
                    updated_at = ?
                WHERE platform = ? AND profile_name = ?
                """,
                (f"+{hours} hours", now, platform, profile_name),
            )
            conn.commit()

    def get_earliest_cooldown_expiry(
        self, platform: str
    ) -> Optional[str]:
        """Return the earliest cooldown_until for profiles in cooldown."""
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT MIN(cooldown_until) AS earliest
                FROM cookie_profiles
                WHERE platform = ?
                  AND status = 'cooldown'
                  AND cooldown_until > datetime('now')
                """,
                (platform,),
            ).fetchone()
        return row["earliest"] if row and row["earliest"] else None

    # ------------------------------------------------------------------
    # task_runs
    # ------------------------------------------------------------------

    def create_task_run(
        self,
        *,
        task_id: str,
        platform: str,
        task_type: str,
        keyword: Optional[str] = None,
        profile_name: Optional[str] = None,
        pid: Optional[int] = None,
        status: str = "queued",
        priority: int = 0,
        parent_task_id: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO task_runs (
                    task_id, platform, task_type, status, keyword,
                    profile_name, pid, priority, parent_task_id,
                    started_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, platform, task_type, status, keyword, profile_name, pid, priority, parent_task_id, now, now),
            )
            conn.commit()

    def update_task_run(
        self,
        task_id: str,
        *,
        status: str,
        pid: Optional[int] = None,
        result_json: Optional[str] = None,
        error_message: Optional[str] = None,
        progress_json: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        sql = "UPDATE task_runs SET status = ?, finished_at = ?"
        params: list[Any] = [status, now]

        if pid is not None:
            sql += ", pid = ?"
            params.append(pid)
        if result_json is not None:
            sql += ", result_json = ?"
            params.append(result_json)
        if error_message is not None:
            sql += ", error_message = ?"
            params.append(error_message)
        if progress_json is not None:
            sql += ", progress_json = ?"
            params.append(progress_json)

        sql += " WHERE task_id = ?"
        params.append(task_id)

        with closing(self.connect()) as conn:
            conn.execute(sql, params)
            conn.commit()

    def get_running_task(self, platform: str) -> Optional[dict[str, Any]]:
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM task_runs
                WHERE platform = ? AND status = 'running'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (platform,),
            ).fetchone()
        return dict(row) if row else None

    def get_running_tasks_all(self) -> list[dict[str, Any]]:
        """Return all running tasks across all platforms (with pid for reaping)."""
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM task_runs
                WHERE status = 'running'
                ORDER BY started_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_queued_tasks(
        self,
        *,
        platform: str = "",
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        """Return queued tasks ordered by priority then created_at."""
        sql = """
            SELECT *
            FROM task_runs
            WHERE status = 'queued'
        """
        params: list[Any] = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        sql += " ORDER BY priority ASC, created_at ASC LIMIT ?"
        params.append(limit)

        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a queued or running task. Returns True if updated."""
        with closing(self.connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE task_runs
                SET status = 'cancelled', finished_at = ?
                WHERE task_id = ? AND status IN ('queued', 'running')
                """,
                (datetime.utcnow().isoformat(timespec="seconds"), task_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def get_task_runs(
        self,
        *,
        platform: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT *
            FROM task_runs
            WHERE 1 = 1
        """
        params: list[Any] = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def crawl_status(self) -> dict[str, Any]:
        """Aggregate status for the crawl API."""
        pending_detail = self.pending_job_count()
        pending_clean = self.ready_for_clean_count()
        pending_score = self.ready_for_scoring_count()

        active_tasks = []
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT task_id, platform, task_type, status, keyword,
                       profile_name, priority, parent_task_id, started_at
                FROM task_runs
                WHERE status IN ('queued', 'running')
                ORDER BY priority ASC, started_at ASC
                """
            ).fetchall()
            active_tasks = [dict(row) for row in rows]

        last_completed = None
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT task_id, platform, task_type, status, keyword,
                       profile_name, started_at, finished_at
                FROM task_runs
                WHERE status IN ('completed', 'failed')
                ORDER BY finished_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row:
                last_completed = dict(row)

        return {
            "pending_detail": pending_detail,
            "pending_cleaned": pending_clean,
            "pending_score": pending_score,
            "active_tasks": active_tasks,
            "last_completed_task": last_completed,
        }
