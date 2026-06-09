"""从 SQLite jobs.db 同步已评分职位到 MySQL job_showcase 表。

用法::

    # 全量覆盖（适合展示前刷新全部数据）
    python tools/sync_sqlite_to_mysql.py --mode full

    # 全量，限制条数
    python tools/sync_sqlite_to_mysql.py --mode full --limit 200

    # 增量同步（按 scored_at）
    python tools/sync_sqlite_to_mysql.py --mode incremental

    # dry-run 预览不写入
    python tools/sync_sqlite_to_mysql.py --mode full --dry-run

MySQL 连接从环境变量读取：MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE
"""

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 把项目根目录加到 sys.path，方便 import 本地模块
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def get_mysql_config() -> dict[str, Any]:
    missing: list[str] = []
    for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
        if not os.getenv(key):
            missing.append(key)
    if missing:
        print(f"[sync] 缺少环境变量: {', '.join(missing)}")
        print("[sync] 请在运行前设置: export MYSQL_HOST=... MYSQL_USER=... ...")
        sys.exit(1)

    return {
        "host": os.getenv("MYSQL_HOST"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": "utf8mb4",
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync SQLite scored jobs to MySQL job_showcase")
    p.add_argument("--mode", choices=("full", "incremental"), default="full")
    p.add_argument("--limit", type=int, default=0, help="最多同步条数，0=不限制")
    p.add_argument("--db", default=str(_project_root / "jobs.db"))
    p.add_argument("--dry-run", action="store_true", help="预览不写入")
    return p.parse_args()


# ---------------------------------------------------------------------------
# SQLite 查询：联表提取展示字段
# ---------------------------------------------------------------------------

QUERY_FULL = """
SELECT
    j.job_id,
    j.keyword,
    j.title,
    j.company_name,
    c.company_name_norm,
    j.city,
    c.salary_text_raw                           AS salary_text,
    CAST(c.salary_min  AS INTEGER)              AS salary_min,
    CAST(c.salary_max  AS INTEGER)              AS salary_max,
    c.education,
    c.exp_years,
    c.company_size,
    c.jd_text,
    CAST(s.total          AS INTEGER)           AS total_score,
    s.verdict,
    CAST(s.score_activity AS INTEGER)           AS score_activity,
    CAST(s.score_jd       AS INTEGER)           AS score_jd,
    CAST(s.score_company  AS INTEGER)           AS score_company,
    CAST(s.score_salary   AS INTEGER)           AS score_salary,
    CAST(s.score_other    AS INTEGER)           AS score_other,
    ce.risk_level                                AS company_risk_level,
    s.red_flags_json,
    s.reasoning,
    COALESCE(ce.negative_sentences_json, ce.zhihu_filtered_results_json, '[]') AS evidence_json,
    COALESCE(s.scored_at, c.cleaned_at, j.updated_at) AS source_updated_at
FROM scores s
JOIN jobs_cleaned c ON c.job_id = s.job_id
JOIN jobs j         ON j.job_id = s.job_id
LEFT JOIN company_enriched ce ON ce.company_name_norm = c.company_name_norm
WHERE s.score_status = 'success'
ORDER BY s.total DESC, s.scored_at DESC
"""

QUERY_INCREMENTAL = """
SELECT
    j.job_id,
    j.keyword,
    j.title,
    j.company_name,
    c.company_name_norm,
    j.city,
    c.salary_text_raw                           AS salary_text,
    CAST(c.salary_min  AS INTEGER)              AS salary_min,
    CAST(c.salary_max  AS INTEGER)              AS salary_max,
    c.education,
    c.exp_years,
    c.company_size,
    c.jd_text,
    CAST(s.total          AS INTEGER)           AS total_score,
    s.verdict,
    CAST(s.score_activity AS INTEGER)           AS score_activity,
    CAST(s.score_jd       AS INTEGER)           AS score_jd,
    CAST(s.score_company  AS INTEGER)           AS score_company,
    CAST(s.score_salary   AS INTEGER)           AS score_salary,
    CAST(s.score_other    AS INTEGER)           AS score_other,
    ce.risk_level                                AS company_risk_level,
    s.red_flags_json,
    s.reasoning,
    COALESCE(ce.negative_sentences_json, ce.zhihu_filtered_results_json, '[]') AS evidence_json,
    COALESCE(s.scored_at, c.cleaned_at, j.updated_at) AS source_updated_at
FROM scores s
JOIN jobs_cleaned c ON c.job_id = s.job_id
JOIN jobs j         ON j.job_id = s.job_id
LEFT JOIN company_enriched ce ON ce.company_name_norm = c.company_name_norm
WHERE s.score_status = 'success'
  AND s.scored_at > ?
ORDER BY s.scored_at DESC
"""


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def read_sqlite(db_path: str, mode: str, limit: int) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if mode == "full":
            sql = QUERY_FULL
            params: tuple = ()
        else:
            sql = QUERY_INCREMENTAL
            # 获取 MySQL 中最近一次同步时间
            params = ("1970-01-01T00:00:00",)

        if limit > 0:
            sql += " LIMIT ?"
            params = params + (limit,)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def sync_full(
    mysql_cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> dict[str, int]:
    import pymysql.cursors

    if dry_run:
        for r in rows[:5]:
            print(f"  [dry-run] {r['job_id']}  {r['title'][:40]}  total={r['total_score']}")
        if len(rows) > 5:
            print(f"  ... 共 {len(rows)} 条")
        return {"selected": len(rows), "upserted": 0, "deleted": 0}

    conn = pymysql.connect(**mysql_cfg, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_showcase")
            deleted = cur.rowcount

            upserted = 0
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO job_showcase (
                        job_id, keyword, title, company_name, company_name_norm,
                        city, salary_text, salary_min, salary_max,
                        education, exp_years, company_size, jd_text,
                        total_score, verdict,
                        score_activity, score_jd, score_company, score_salary, score_other,
                        company_risk_level, red_flags_json, reasoning, evidence_json,
                        source_updated_at, synced_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s
                    )
                    """,
                    (
                        r["job_id"], r["keyword"], r["title"], r["company_name"],
                        r["company_name_norm"],
                        r["city"], r["salary_text"], r["salary_min"], r["salary_max"],
                        r["education"], r["exp_years"], r["company_size"], r["jd_text"],
                        r["total_score"], r["verdict"],
                        r["score_activity"], r["score_jd"], r["score_company"],
                        r["score_salary"], r["score_other"],
                        r["company_risk_level"], r["red_flags_json"], r["reasoning"],
                        r["evidence_json"],
                        r["source_updated_at"], datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                upserted += 1
    finally:
        conn.close()

    return {"selected": len(rows), "upserted": upserted, "deleted": deleted}


def sync_incremental(
    mysql_cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> dict[str, int]:
    import pymysql.cursors

    if dry_run:
        for r in rows[:5]:
            print(f"  [dry-run] {r['job_id']}  {r['title'][:40]}  total={r['total_score']}")
        if len(rows) > 5:
            print(f"  ... 共 {len(rows)} 条")
        return {"selected": len(rows), "upserted": 0, "deleted": 0}

    conn = pymysql.connect(**mysql_cfg, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    try:
        with conn.cursor() as cur:
            upserted = 0
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO job_showcase (
                        job_id, keyword, title, company_name, company_name_norm,
                        city, salary_text, salary_min, salary_max,
                        education, exp_years, company_size, jd_text,
                        total_score, verdict,
                        score_activity, score_jd, score_company, score_salary, score_other,
                        company_risk_level, red_flags_json, reasoning, evidence_json,
                        source_updated_at, synced_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s
                    )
                    ON DUPLICATE KEY UPDATE
                        keyword = VALUES(keyword),
                        title = VALUES(title),
                        company_name = VALUES(company_name),
                        company_name_norm = VALUES(company_name_norm),
                        city = VALUES(city),
                        salary_text = VALUES(salary_text),
                        salary_min = VALUES(salary_min),
                        salary_max = VALUES(salary_max),
                        education = VALUES(education),
                        exp_years = VALUES(exp_years),
                        company_size = VALUES(company_size),
                        jd_text = VALUES(jd_text),
                        total_score = VALUES(total_score),
                        verdict = VALUES(verdict),
                        score_activity = VALUES(score_activity),
                        score_jd = VALUES(score_jd),
                        score_company = VALUES(score_company),
                        score_salary = VALUES(score_salary),
                        score_other = VALUES(score_other),
                        company_risk_level = VALUES(company_risk_level),
                        red_flags_json = VALUES(red_flags_json),
                        reasoning = VALUES(reasoning),
                        evidence_json = VALUES(evidence_json),
                        source_updated_at = VALUES(source_updated_at),
                        synced_at = VALUES(synced_at)
                    """,
                    (
                        r["job_id"], r["keyword"], r["title"], r["company_name"],
                        r["company_name_norm"],
                        r["city"], r["salary_text"], r["salary_min"], r["salary_max"],
                        r["education"], r["exp_years"], r["company_size"], r["jd_text"],
                        r["total_score"], r["verdict"],
                        r["score_activity"], r["score_jd"], r["score_company"],
                        r["score_salary"], r["score_other"],
                        r["company_risk_level"], r["red_flags_json"], r["reasoning"],
                        r["evidence_json"],
                        r["source_updated_at"], datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                upserted += 1
    finally:
        conn.close()

    return {"selected": len(rows), "upserted": upserted, "deleted": 0}


def record_sync_run(
    mysql_cfg: dict[str, Any],
    mode: str,
    stats: dict[str, int],
    *,
    started_at: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    import pymysql.cursors
    finished_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = pymysql.connect(**mysql_cfg, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO showcase_sync_runs
                    (mode, rows_selected, rows_upserted, rows_deleted,
                     started_at, finished_at, status, error_message)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    mode,
                    stats["selected"],
                    stats["upserted"],
                    stats.get("deleted", 0),
                    started_at,
                    finished_at,
                    status,
                    error_message,
                ),
            )
        conn.close()
    except Exception as exc:
        print(f"[sync] 记录 sync_run 失败: {exc}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    started_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[sync] mode={args.mode} db={args.db} limit={args.limit or '不限制'}")

    # 1) 读 SQLite
    rows = read_sqlite(args.db, args.mode, args.limit)
    print(f"[sync] selected {len(rows)} rows from SQLite")
    if not rows:
        print("[sync] nothing to sync, exiting")
        return

    # 2) 预览
    print(f"[sync] sample: {rows[0]['job_id']}  \"{rows[0]['title'][:50]}\"  total={rows[0]['total_score']}")

    # 3) 连接 MySQL
    if args.dry_run:
        stats = sync_full({}, rows, dry_run=True)
    else:
        mysql_cfg = get_mysql_config()
        print(f"[sync] connecting to MySQL {mysql_cfg['host']}:{mysql_cfg['port']}/{mysql_cfg['database']}")

        if args.mode == "full":
            stats = sync_full(mysql_cfg, rows, dry_run=False)
        else:
            stats = sync_incremental(mysql_cfg, rows, dry_run=False)

        record_sync_run(mysql_cfg, args.mode, stats, started_at=started_at, status="success")

    print(
        f"[sync] done — selected={stats['selected']} "
        f"upserted={stats['upserted']} deleted={stats.get('deleted', 0)}"
    )


if __name__ == "__main__":
    main()
