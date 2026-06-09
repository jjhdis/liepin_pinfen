"""Crawler daemon — independent background process that manages crawl tasks.

Runs continuously, polling task_runs for queued tasks, launching them as
subprocesses, and updating their status.  Dashboard can be started/stopped
independently without affecting running crawls.

Usage::

    python crawler_daemon.py              # foreground (debug)
    python crawler_daemon.py --daemon     # background (daemonize)
    python crawler_daemon.py --stop       # stop a running daemon
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import PATHS, RUN_CONFIG, normalize_keyword
from cookie_manager import scan_and_cleanup
from storage.database import Database

BASE_DIR = Path(__file__).resolve().parent
PYTHON_EXE = BASE_DIR / ".venv" / "Scripts" / "python.exe"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def get_python() -> str:
    if PYTHON_EXE.exists():
        return str(PYTHON_EXE)
    return sys.executable


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[daemon {now_iso()}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# task command builders
# ---------------------------------------------------------------------------

def _build_list_cmd(task: dict) -> list[str]:
    keyword = task.get("keyword") or ""
    profile_name = task.get("profile_name") or ""
    cookie_file = ""
    if profile_name:
        cookie_dir = PATHS["cookie_dir"]
        platform = task.get("platform", "liepin")
        candidates = sorted(
            cookie_dir.glob(f"cookie_*_{profile_name}_{platform}.json"),
            reverse=True,
        )
        if candidates:
            cookie_file = candidates[0].name

    cmd = [
        get_python(), str(BASE_DIR / "main.py"), "list",
        "--keyword", keyword,
        "--store-top-n", str(RUN_CONFIG["list"]["store_top_n"]),
    ]
    if cookie_file:
        cmd.extend(["--cookie-file", cookie_file])
    return cmd


def _build_detail_cmd(task: dict) -> list[str]:
    platform = task.get("platform", "liepin")
    profile_name = task.get("profile_name") or ""
    cmd = [
        get_python(), str(BASE_DIR / "rotate_liepin_cookies.py"),
        "--platform", platform,
        "--output-json",
    ]
    if profile_name:
        cmd.extend(["--max-cookies", "1"])
    return cmd


def _build_postprocess_cmd(task: dict) -> list[str]:  # noqa: ARG001
    return [get_python(), str(BASE_DIR / "postprocess_pipeline.py")]


TASK_BUILDERS = {
    "list": _build_list_cmd,
    "detail": _build_detail_cmd,
    "postprocess": _build_postprocess_cmd,
}


# ---------------------------------------------------------------------------
# daemon core
# ---------------------------------------------------------------------------

class CrawlerDaemon:
    def __init__(self, db: Database, platform_filter: str = "") -> None:
        self.db = db
        self.platform_filter = platform_filter
        self._running: dict[str, dict] = {}  # task_id → {proc, task_type, platform, keyword}
        self._last_cookie_scan = 0.0
        self._shutdown = False

    # ---- reaping -----------------------------------------------------------

    def _reap_finished(self) -> None:
        """Check each running subprocess; update DB if it exited or was cancelled."""
        finished: list[str] = []
        for task_id, entry in list(self._running.items()):
            proc = entry["proc"]

            # Check if user cancelled this task via dashboard
            if self._is_task_cancelled(task_id):
                log(f"task={task_id} cancelled by user, killing pid={proc.pid}")
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log(f"task={task_id} did not exit after SIGTERM, force-killing")
                    proc.kill()
                    proc.wait()
                except Exception:
                    proc.kill()
                self.db.update_task_run(
                    task_id, status="cancelled",
                    error_message="killed by user",
                )
                finished.append(task_id)
                continue

            ret = proc.poll()
            if ret is not None:
                status = "completed" if ret == 0 else "failed"
                err_msg = None if ret == 0 else f"exit_code={ret}"
                self.db.update_task_run(
                    task_id, status=status, error_message=err_msg,
                )
                finished.append(task_id)
                log(f"task={task_id} finished status={status} exit={ret}")

                # ---- auto-chain: list → detail ----
                if status == "completed" and entry.get("task_type") == "list":
                    self._maybe_chain_detail(entry)

        for tid in finished:
            del self._running[tid]

    def _is_task_cancelled(self, task_id: str) -> bool:
        """Check if a task has been marked cancelled in the DB."""
        import sqlite3
        conn = self.db.connect()
        try:
            row = conn.execute(
                "SELECT status FROM task_runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return row is not None and row["status"] == "cancelled"
        finally:
            conn.close()

    def _maybe_chain_detail(self, task_entry: dict) -> None:
        """If a list task completed, check for new pending jobs and auto-create
        a detail task.  Only fires when ALL list tasks for the platform are done,
        so detail gets the full batch of pending jobs for cookie rotation."""
        platform = task_entry.get("platform", "liepin")
        keyword = task_entry.get("keyword")
        list_task_id = task_entry.get("task_id", "")

        # Don't create detail if there are still queued list tasks
        all_queued = self.db.get_queued_tasks(platform=platform, limit=100)
        has_more_lists = any(
            t.get("task_type") == "list" for t in all_queued
        )
        if has_more_lists:
            log(f"auto-chain: list={list_task_id} done but more list tasks queued, waiting")
            return

        # Check if we already have a running detail for this platform
        running = self.db.get_running_task(platform)
        if running:
            return
        # Check if a detail is already queued
        has_detail_queued = any(
            t.get("task_type") == "detail" for t in all_queued
        )
        if has_detail_queued:
            return

        # Check pending count (all keywords, since detail processes everything)
        pending = self.db.pending_job_count(keyword=None)
        if pending <= 0:
            log(f"auto-chain: list={list_task_id} done but pending=0, skip detail")
            return

        # Create detail task
        import uuid
        detail_id = f"task_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.db.create_task_run(
            task_id=detail_id,
            platform=platform,
            task_type="detail",
            keyword=keyword,
            status="queued",
            parent_task_id=list_task_id,
        )
        log(
            f"auto-chain: list={list_task_id} → detail={detail_id} "
            f"platform={platform} pending={pending}"
        )

    # ---- dispatching -------------------------------------------------------

    def _dispatch(self) -> None:
        """Pick queued tasks and launch them, one per platform at a time."""
        platforms = ["liepin"]
        if self.platform_filter:
            platforms = [self.platform_filter]

        for platform in platforms:
            # Mutual exclusion — one running task per platform
            running = self.db.get_running_task(platform)
            if running:
                if running["task_id"] not in self._running:
                    log(
                        f"orphan running task={running['task_id']} "
                        f"platform={platform} — will not re-launch"
                    )
                continue

            # Fetch next queued task
            queued = self.db.get_queued_tasks(platform=platform, limit=1)
            if not queued:
                continue

            task = queued[0]
            task_type = task.get("task_type", "")
            builder = TASK_BUILDERS.get(task_type)
            if not builder:
                log(f"unknown task_type={task_type} task={task['task_id']}, skipping")
                self.db.update_task_run(task["task_id"], status="failed", error_message=f"unknown task_type={task_type}")
                continue

            cmd = builder(task)
            log(f"launch task={task['task_id']} type={task_type} platform={platform} cmd={' '.join(cmd)}")

            try:
                log_dir = BASE_DIR / RUN_CONFIG.get("daemon_log_dir", "logs")
                log_dir.mkdir(exist_ok=True)
                task_log = open(str(log_dir / "daemon_tasks.log"), "a")
                proc = subprocess.Popen(
                    cmd,
                    cwd=BASE_DIR,
                    stdout=task_log,
                    stderr=subprocess.STDOUT,
                )
            except Exception as exc:
                log(f"launch failed task={task['task_id']} error={exc}")
                self.db.update_task_run(task["task_id"], status="failed", error_message=str(exc))
                continue

            self._running[task["task_id"]] = {
                "proc": proc,
                "task_type": task_type,
                "platform": platform,
                "keyword": task.get("keyword"),
                "task_id": task["task_id"],
            }
            self.db.update_task_run(
                task["task_id"],
                status="running",
                pid=proc.pid,
            )

    # ---- cookie maintenance ------------------------------------------------

    def _maybe_scan_cookies(self) -> None:
        now = time.time()
        interval = RUN_CONFIG.get("daemon_cookie_scan_interval_seconds", 300)
        if now - self._last_cookie_scan < interval:
            return
        self._last_cookie_scan = now

        platforms = ["liepin", "boss", "zhilian"]
        if self.platform_filter:
            platforms = [self.platform_filter]
        for pf in platforms:
            try:
                scan_and_cleanup(platform=pf)
            except Exception as exc:
                log(f"cookie scan error platform={pf}: {exc}")

    # ---- main loop ---------------------------------------------------------

    def run_forever(self) -> None:
        poll_interval = RUN_CONFIG.get("daemon_poll_interval_seconds", 3)
        log(f"daemon started poll_interval={poll_interval}s")

        while not self._shutdown:
            try:
                self._reap_finished()
                self._dispatch()
                self._maybe_scan_cookies()
            except Exception as exc:
                log(f"loop error: {exc}")

            time.sleep(poll_interval)

        # graceful shutdown
        log("shutting down, waiting for running tasks...")
        for task_id, entry in self._running.items():
            proc = entry["proc"]
            log(f"terminating task={task_id} pid={proc.pid}")
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        log("daemon stopped")

    def shutdown(self) -> None:
        self._shutdown = True


# ---------------------------------------------------------------------------
# daemonize helpers (Windows-compatible)
# ---------------------------------------------------------------------------

def _pid_file_path() -> Path:
    name = RUN_CONFIG.get("daemon_pid_file", "crawler_daemon.pid")
    return BASE_DIR / name


def _write_pid(pid: int) -> None:
    _pid_file_path().write_text(str(pid))


def _read_pid() -> Optional[int]:
    path = _pid_file_path()
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def _remove_pid() -> None:
    path = _pid_file_path()
    if path.exists():
        path.unlink()


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawler daemon")
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run in background (daemonize).",
    )
    parser.add_argument(
        "--stop", action="store_true",
        help="Stop a running daemon.",
    )
    parser.add_argument(
        "--platform", default="",
        help="Only manage this platform. Default: all.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # --- stop ---
    if args.stop:
        pid = _read_pid()
        if pid is None:
            print("No daemon PID file found.")
            raise SystemExit(0)
        if not _is_process_running(pid):
            print(f"PID {pid} is not running. Removing stale PID file.")
            _remove_pid()
            raise SystemExit(0)
        print(f"Sending SIGTERM to pid={pid} ...")
        os.kill(pid, signal.SIGTERM)
        _remove_pid()
        print("Stop signal sent.")
        return

    # --- daemonize (Windows: just detach console) ---
    if args.daemon:
        pid = _read_pid()
        if pid and _is_process_running(pid):
            print(f"Daemon already running (pid={pid}). Use --stop first.")
            raise SystemExit(1)

        # Simple daemonize: spawn self without --daemon in background
        _write_pid(os.getpid())
        # Redirect stdio
        log_dir = BASE_DIR / RUN_CONFIG.get("daemon_log_dir", "logs")
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "crawler_daemon.log"
        print(f"Daemon starting. Log: {log_path}  PID: {os.getpid()}")
        # Detach by spawning a new process
        python = get_python()
        script = Path(__file__).resolve()
        subprocess.Popen(
            [python, str(script)],
            cwd=BASE_DIR,
            stdout=open(str(log_path), "a"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        print("Daemon launched in background.")
        return

    # --- foreground ---
    db = Database(PATHS["database"])
    db.init()

    # 启动时清理过期数据
    retention = RUN_CONFIG["data_retention_days"]
    deleted = db.cleanup_old_records(retention_days=retention)
    cleaned = [(t, n) for t, n in deleted.items() if n]
    if cleaned:
        print(f"[daemon] cleanup (>{retention}d): " + ", ".join(f"{t}={n}" for t, n in cleaned))
    else:
        print(f"[daemon] cleanup (>{retention}d): nothing to delete")

    # 清理 debug 目录过期文件
    debug_dir = PATHS["debug"]
    if debug_dir.exists():
        cutoff = time.time() - retention * 86400
        debug_deleted = 0
        for f in debug_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                debug_deleted += 1
        if debug_deleted:
            print(f"[daemon] cleanup debug/: {debug_deleted} files deleted")

    daemon = CrawlerDaemon(db, platform_filter=args.platform)

    # Handle SIGTERM / SIGINT gracefully
    def _handle_signal(signum, frame):
        daemon.shutdown()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    _write_pid(os.getpid())
    try:
        daemon.run_forever()
    finally:
        _remove_pid()


if __name__ == "__main__":
    main()
