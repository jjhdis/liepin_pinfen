"""
Cookie file discovery, cleanup, and profile management.
Reusable module — callable from CLI scripts or future frontend.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from config import PATHS, RUN_CONFIG
from storage.database import Database

# Cookie file pattern: cookie_YYYYMMDD_HHMMSS_phone_platform.json
_COOKIE_FILE_RE = re.compile(
    r"^cookie_(\d{8})_\d{6}_(.+?)_(liepin|boss|zhilian)\.json$"
)

_TIER_ORDER = {"fresh": 0, "day_old": 1, "stale": 2}


def _extract_date(filename: str) -> Optional[str]:
    m = _COOKIE_FILE_RE.match(filename)
    return m.group(1) if m else None


def _extract_profile_name(filename: str) -> Optional[str]:
    m = _COOKIE_FILE_RE.match(filename)
    return m.group(2) if m else None


def _extract_platform(filename: str) -> Optional[str]:
    m = _COOKIE_FILE_RE.match(filename)
    return m.group(3) if m else None


def _classify_tier(date_str: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    if date_str == today:
        return "fresh"
    if date_str == yesterday:
        return "day_old"
    return "stale"


def scan_and_cleanup(platform: str = "liepin") -> list[dict[str, Any]]:
    """Scan cookies/ dir, delete stale files, sync to cookie_profiles table.

    Returns list of available cookies ordered by freshness priority
    (today > yesterday > older within max_age_days).

    Each item::
        {"path": Path, "tier": "fresh"|"day_old"|"stale", "profile_name": str}
    """
    cookie_dir = PATHS["cookie_dir"]
    max_age_days = RUN_CONFIG.get("cookie_max_age_days", 2)
    cutoff_str = (datetime.now() - timedelta(days=max_age_days)).strftime("%Y%m%d")

    if not cookie_dir.exists():
        print(f"[cookie-manager] cookie dir not found: {cookie_dir}")
        return []

    # --- Step 1: delete stale files (> max_age_days) ---
    deleted = 0
    for f in sorted(cookie_dir.glob(f"cookie_*_{platform}.json")):
        date_str = _extract_date(f.name)
        if date_str and date_str <= cutoff_str:
            f.unlink()
            deleted += 1
            print(f"[cookie-manager] deleted stale: {f.name}")
    if deleted:
        print(f"[cookie-manager] cleanup: {deleted} stale file(s) deleted")

    # --- Step 2: group by profile_name, keep newest per group ---
    remaining = sorted(
        cookie_dir.glob(f"cookie_*_{platform}.json"),
        key=lambda p: p.name,
        reverse=True,
    )
    seen: dict[str, Path] = {}
    for f in remaining:
        profile_name = _extract_profile_name(f.name)
        if profile_name and profile_name not in seen:
            seen[profile_name] = f

    if not seen:
        print(
            f"[cookie-manager] no cookie files available for "
            f"platform={platform} (check cookies/ dir)"
        )
        return []

    # --- Step 3: sync to cookie_profiles table ---
    db = Database(PATHS["database"])
    db.init()
    now = datetime.utcnow().isoformat(timespec="seconds")

    previous = {
        p["profile_name"]: p.get("notes", "")
        for p in db.get_ready_cookie_profiles(platform)
    }

    for profile_name, f in seen.items():
        date_str = _extract_date(f.name)
        tier = _classify_tier(date_str) if date_str else "stale"
        file_changed = f.name not in previous.get(profile_name, "")

        db.upsert_cookie_profile(
            platform=platform,
            profile_name=profile_name,
            status="ready",
            notes=f"file: {f.name}  tier: {tier}",
            updated_at=now,
            reset_counters=file_changed,
        )
        if file_changed:
            print(
                f"[cookie-manager] new cookie file for profile={profile_name}, "
                f"counters reset"
            )

    # --- disable profiles whose files no longer exist ---
    for p in db.get_ready_cookie_profiles(platform):
        if p["profile_name"] not in seen:
            db.update_cookie_profile_status(
                platform=platform,
                profile_name=p["profile_name"],
                status="disabled",
                last_error="cookie file deleted / expired",
                last_error_at=now,
            )
            print(
                f"[cookie-manager] disabled profile: "
                f"platform={platform} profile={p['profile_name']} "
                f"(no cookie file found)"
            )

    # --- Step 4: build ordered result list ---
    results: list[dict[str, Any]] = []
    for profile_name, f in seen.items():
        date_str = _extract_date(f.name)
        tier = _classify_tier(date_str) if date_str else "stale"
        results.append({
            "path": f,
            "tier": tier,
            "profile_name": profile_name,
        })

    results.sort(
        key=lambda r: (
            _TIER_ORDER.get(r["tier"], 99),
            r["path"].name,
        )
    )

    # --- summary ---
    tier_counts: dict[str, int] = {}
    for r in results:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
    parts = ", ".join(f"{t}={c}" for t, c in tier_counts.items())
    print(
        f"[cookie-manager] platform={platform} "
        f"available={len(results)} ({parts})"
    )
    for r in results:
        label = _TIER_LABEL(r["tier"])
        extra = f"  {label}" if label else ""
        print(
            f"  tier={r['tier']:<8} profile={r['profile_name']:<16} "
            f"file={r['path'].name}{extra}"
        )

    return results


def mark_profile_used(platform: str, profile_name: str) -> None:
    """Update usage counters after a cookie batch completes successfully."""
    db = Database(PATHS["database"])
    db.init()
    db.increment_cookie_usage(platform, profile_name)
    print(
        f"[cookie-manager] mark_used platform={platform} "
        f"profile={profile_name}"
    )


def mark_profile_blocked(
    platform: str, profile_name: str, reason: str = ""
) -> None:
    """Mark profile as needs_manual_verify after a block / C-class event."""
    db = Database(PATHS["database"])
    db.init()
    now = datetime.utcnow().isoformat(timespec="seconds")
    db.update_cookie_profile_status(
        platform=platform,
        profile_name=profile_name,
        status="needs_manual_verify",
        last_error=reason,
        last_error_at=now,
    )
    print(
        f"[cookie-manager] mark_blocked platform={platform} "
        f"profile={profile_name} reason={reason}"
    )


def get_available_profiles(platform: str = "liepin") -> list[dict[str, Any]]:
    """Query cookie_profiles for ready-status profiles."""
    db = Database(PATHS["database"])
    db.init()
    return db.get_ready_cookie_profiles(platform)


def get_usable_profiles(
    platform: str = "liepin",
    *,
    daily_max: int = 0,
) -> list[dict[str, Any]]:
    """Query cookie_profiles for usable profiles (ready + cooldown-expired)."""
    db = Database(PATHS["database"])
    db.init()
    return db.get_usable_cookie_profiles(platform, daily_max=daily_max)


def mark_profile_cooldown(
    platform: str,
    profile_name: str,
    *,
    hours: int = 2,
) -> None:
    """Set a cookie profile into cooldown state for *hours* hours."""
    db = Database(PATHS["database"])
    db.init()
    db.mark_cookie_cooldown(platform, profile_name, hours=hours)
    print(
        f"[cookie-manager] mark_cooldown platform={platform} "
        f"profile={profile_name} hours={hours}"
    )


def get_earliest_cooldown_expiry(platform: str = "liepin") -> Optional[str]:
    """Return the earliest cooldown expiry time for the platform."""
    db = Database(PATHS["database"])
    db.init()
    return db.get_earliest_cooldown_expiry(platform)


def _TIER_LABEL(tier: str) -> str:
    if tier == "day_old":
        return "[WARN] day-old cookie, may trigger captcha"
    if tier == "stale":
        return "[WARN] stale cookie, high risk of block"
    return ""
