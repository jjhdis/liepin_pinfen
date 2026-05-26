import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


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
                    created_at, updated_at
                ) VALUES (?, ?, ?, NULL, '[]', '{}', ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    keyword = excluded.keyword,
                    detail_url = excluded.detail_url,
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
                    created_at, updated_at
                ) VALUES (
                    :job_id, :keyword, :detail_url, :title, :salary_min, :salary_max,
                    :salary_months, :city, :exp_years, :education, :date_posted,
                    :last_updated, :days_since_update, :company_name, :company_size,
                    :company_verified, :company_logo_exists, :publisher_type,
                    :jd_text, :jd_length, :benefits_json, :raw_html, :raw_json,
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
