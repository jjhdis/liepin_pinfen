import argparse
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from curl_cffi import requests as curl_requests

from config import LIEPIN_MESSAGE_CONFIG, PATHS
from storage.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Liepin HR message status from the contact list API."
    )
    parser.add_argument(
        "--cookie-file",
        required=True,
        help=(
            "Liepin cookie file. Supports an absolute path, a project-relative path, "
            "or a filename under the cookies/ directory."
        ),
    )
    parser.add_argument(
        "--cookie-profile-id",
        help="Optional stable cookie profile id. Default derives from the cookie filename.",
    )
    parser.add_argument(
        "--account-label",
        help="Optional human-readable account label. Default derives from the cookie filename.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=LIEPIN_MESSAGE_CONFIG["page_size"],
        help="How many contacts to request per page. Default: %(default)s",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=LIEPIN_MESSAGE_CONFIG["max_pages"],
        help="Maximum pages to fetch. Default: %(default)s",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print summary without writing database.",
    )
    return parser.parse_args()


def resolve_cookie_path(cookie_file: str) -> Path:
    raw_path = Path(cookie_file)
    candidates: list[Path] = []

    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.extend(
            [
                raw_path,
                PATHS["cookie_dir"] / raw_path.name,
                PATHS["cookies"].parent / raw_path,
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate

    if raw_path.is_absolute():
        return raw_path

    if raw_path.parent == Path("."):
        return PATHS["cookie_dir"] / raw_path.name

    return PATHS["cookies"].parent / raw_path


def load_cookie_list(cookie_path: Path) -> list[dict[str, Any]]:
    with cookie_path.open("r", encoding="utf-8") as fh:
        cookies = json.load(fh)
    if not isinstance(cookies, list):
        raise ValueError(f"{cookie_path.name} must be a list of cookie dicts.")
    return cookies


def resolve_message_context_path(cookie_path: Path) -> Path:
    return cookie_path.with_name(f"{cookie_path.stem}_message_context.json")


def load_message_context(cookie_path: Path) -> dict[str, Any]:
    context_path = resolve_message_context_path(cookie_path)
    if not context_path.exists():
        return {}

    with context_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if not isinstance(payload, dict):
        raise ValueError(f"{context_path.name} must be a JSON object.")
    return payload


def derive_cookie_profile_id(cookie_path: Path) -> str:
    return cookie_path.stem


def derive_account_label(cookie_path: Path) -> str:
    match = re.search(r"cookie_\d{8}_\d{6}_(\d+)_liepin$", cookie_path.stem)
    if match:
        return f"liepin_{match.group(1)}"
    return cookie_path.stem


def sanitize_filename_part(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return sanitized.strip("._-") or "unknown"


def dump_debug_payload(
    *,
    cookie_profile_id: str,
    reason: str,
    payload: Any,
) -> Path:
    debug_dir = PATHS["debug"]
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_profile = sanitize_filename_part(cookie_profile_id)
    safe_reason = sanitize_filename_part(reason)
    debug_path = (
        debug_dir / f"liepin_message_{safe_profile}_{safe_reason}_{timestamp}.json"
    )
    with debug_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return debug_path


def build_session(
    cookies: list[dict[str, Any]],
    *,
    message_context: Optional[dict[str, Any]] = None,
) -> curl_requests.Session:
    message_context = message_context or {}
    session = curl_requests.Session(
        impersonate="chrome124",
        timeout=LIEPIN_MESSAGE_CONFIG["request_timeout_seconds"],
    )
    session.headers.update(
        {
            "Accept": str(message_context.get("accept") or LIEPIN_MESSAGE_CONFIG["accept"]),
            "Accept-Language": str(
                message_context.get("accept_language") or LIEPIN_MESSAGE_CONFIG["accept_language"]
            ),
            "Cache-Control": "no-cache",
            "Content-Type": str(
                message_context.get("content_type") or LIEPIN_MESSAGE_CONFIG["content_type"]
            ),
            "Origin": str(message_context.get("origin") or LIEPIN_MESSAGE_CONFIG["origin"]),
            "Pragma": "no-cache",
            "Referer": str(message_context.get("referer") or LIEPIN_MESSAGE_CONFIG["referer"]),
            "Sec-CH-UA": str(message_context.get("sec_ch_ua") or LIEPIN_MESSAGE_CONFIG["sec_ch_ua"]),
            "Sec-CH-UA-Mobile": str(
                message_context.get("sec_ch_ua_mobile") or LIEPIN_MESSAGE_CONFIG["sec_ch_ua_mobile"]
            ),
            "Sec-CH-UA-Platform": str(
                message_context.get("sec_ch_ua_platform") or LIEPIN_MESSAGE_CONFIG["sec_ch_ua_platform"]
            ),
            "Sec-Fetch-Dest": str(
                message_context.get("sec_fetch_dest") or LIEPIN_MESSAGE_CONFIG["sec_fetch_dest"]
            ),
            "Sec-Fetch-Mode": str(
                message_context.get("sec_fetch_mode") or LIEPIN_MESSAGE_CONFIG["sec_fetch_mode"]
            ),
            "Sec-Fetch-Site": str(
                message_context.get("sec_fetch_site") or LIEPIN_MESSAGE_CONFIG["sec_fetch_site"]
            ),
            "User-Agent": str(message_context.get("user_agent") or LIEPIN_MESSAGE_CONFIG["user_agent"]),
            "X-Client-Type": str(
                message_context.get("x_client_type") or LIEPIN_MESSAGE_CONFIG["x_client_type"]
            ),
            "X-Fscp-Fe-Version": str(
                message_context.get("x_fscp_fe_version") or LIEPIN_MESSAGE_CONFIG["x_fscp_fe_version"]
            ),
            "X-Fscp-Std-Info": str(
                message_context.get("x_fscp_std_info") or LIEPIN_MESSAGE_CONFIG["x_fscp_std_info"]
            ),
            "X-Fscp-Version": str(
                message_context.get("x_fscp_version") or LIEPIN_MESSAGE_CONFIG["x_fscp_version"]
            ),
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    for item in cookies:
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        if not name:
            continue
        domain = str(item.get("domain") or ".liepin.com")
        session.cookies.set(name, value, domain=domain)

    return session


def request_contact_page(
    session: curl_requests.Session,
    *,
    cur_page: int,
    page_size: int,
    message_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    message_context = message_context or {}
    api_url = LIEPIN_MESSAGE_CONFIG["contact_list_api"]
    payload = {
        "curPage": cur_page,
        "pageSize": page_size,
    }
    bi_stat_location = str(
        message_context.get("x_fscp_bi_stat_location")
        or f"{LIEPIN_MESSAGE_CONFIG['referer']}?time={int(datetime.utcnow().timestamp() * 1000)}"
    )
    session.headers["X-Fscp-Bi-Stat"] = json.dumps(
        {"location": bi_stat_location},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    session.headers["X-Fscp-Trace-Id"] = str(uuid.uuid4())
    request_attempts = [
        ("post_form", lambda: session.post(api_url, data=payload)),
        ("post_json", lambda: session.post(api_url, json=payload)),
        ("get_query", lambda: session.get(api_url, params=payload)),
    ]

    last_error: Optional[Exception] = None
    for _, request_fn in request_attempts:
        try:
            response = request_fn()
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
            last_error = ValueError("Liepin message API returned a non-object response.")
        except Exception as exc:
            last_error = exc

    if last_error is None:
        raise RuntimeError("Liepin message API request failed for an unknown reason.")
    raise last_error


def _clean_preview_text(text: str) -> str:
    """Remove noise symbols from message preview text."""
    text = re.sub(r">+", " ", text)
    text = re.sub(r"【.*?】", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_message_preview(last_payload_raw: Any) -> str:
    if not last_payload_raw:
        return ""

    text = str(last_payload_raw).strip()
    if not text:
        return ""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _clean_preview_text(text[:200])

    bodies = payload.get("bodies")
    if isinstance(bodies, list):
        parts: list[str] = []
        for body in bodies:
            if not isinstance(body, dict):
                continue
            msg = str(body.get("msg") or "").strip()
            if msg:
                parts.append(msg)
        if parts:
            return _clean_preview_text(" ".join(parts)[:200])

    ext_body = (
        payload.get("ext", {})
        .get("extBody", {})
        .get("bizData", {})
    )
    if isinstance(ext_body, dict):
        list_content = str(ext_body.get("listContent") or "").strip()
        if list_content:
            return _clean_preview_text(list_content[:200])
        content = str(ext_body.get("content") or "").strip()
        if content:
            return _clean_preview_text(content[:200])

    return _clean_preview_text(text[:200])


def normalize_contact(raw_item: dict[str, Any], *, checked_at: str) -> dict[str, Any]:
    contact_id = str(
        raw_item.get("id")
        or raw_item.get("oppositeImId")
        or raw_item.get("imId")
        or ""
    ).strip()
    latest_msg_time = raw_item.get("latestMsgTime")
    try:
        latest_msg_time_iso = datetime.fromtimestamp(
            int(latest_msg_time) / 1000
        ).isoformat(timespec="seconds")
    except Exception:
        latest_msg_time_iso = None

    return {
        "contact_id": contact_id,
        "name": str(raw_item.get("name") or "").strip(),
        "company": str(raw_item.get("company") or "").strip(),
        "user_tag": str(raw_item.get("userTag") or "").strip(),
        "title": str(raw_item.get("title") or "").strip(),
        "photo": str(raw_item.get("photo") or "").strip(),
        "home_page": str(raw_item.get("homePage") or "").strip(),
        "latest_msg_id": str(raw_item.get("latestMsgId") or "").strip(),
        "latest_msg_type": str(raw_item.get("latestMsgType") or "").strip(),
        "last_payload_json": str(raw_item.get("lastPayload") or ""),
        "last_message_preview": extract_message_preview(raw_item.get("lastPayload")),
        "unread_cnt": int(raw_item.get("unReadCnt") or 0),
        "latest_msg_time": latest_msg_time_iso,
        "user_id": str(raw_item.get("userId") or "").strip(),
        "im_user_type": str(raw_item.get("imUserType") or "").strip(),
        "opposite_user_id": str(raw_item.get("oppositeUserId") or "").strip(),
        "im_id": str(raw_item.get("imId") or "").strip(),
        "opposite_im_id": str(raw_item.get("oppositeImId") or "").strip(),
        "opposite_im_user_type": str(raw_item.get("oppositeImUserType") or "").strip(),
        "chat_type": str(raw_item.get("chatType") or "").strip(),
        "direction": str(raw_item.get("direction") or "").strip(),
        "contact": int(bool(raw_item.get("contact"))),
        "checked_at": checked_at,
    }


def fetch_all_contacts(
    session: curl_requests.Session,
    *,
    page_size: int,
    max_pages: int,
    checked_at: str,
    cookie_profile_id: str,
    message_context: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []

    for cur_page in range(max_pages):
        payload = request_contact_page(
            session,
            cur_page=cur_page,
            page_size=page_size,
            message_context=message_context,
        )
        if int(payload.get("flag") or 0) != 1:
            debug_path = dump_debug_payload(
                cookie_profile_id=cookie_profile_id,
                reason=f"flag_{payload.get('flag')}",
                payload={
                    "checked_at": checked_at,
                    "cur_page": cur_page,
                    "page_size": page_size,
                    "response": payload,
                },
            )
            raise RuntimeError(
                "Liepin message API returned "
                f"flag={payload.get('flag')} debug={debug_path}"
            )

        data = payload.get("data") or {}
        raw_items = data.get("list") or []
        if not isinstance(raw_items, list):
            debug_path = dump_debug_payload(
                cookie_profile_id=cookie_profile_id,
                reason="invalid_contact_list",
                payload={
                    "checked_at": checked_at,
                    "cur_page": cur_page,
                    "page_size": page_size,
                    "response": payload,
                },
            )
            raise RuntimeError("Liepin message API returned an invalid contact list.")

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            normalized = normalize_contact(raw_item, checked_at=checked_at)
            if normalized["contact_id"]:
                contacts.append(normalized)

        has_more = bool(data.get("hasMore")) or bool(data.get("hasNext"))
        if not has_more or not raw_items:
            break

    deduped: dict[str, dict[str, Any]] = {}
    for item in contacts:
        deduped[item["contact_id"]] = item
    return list(deduped.values())


def build_status_summary(
    contacts: list[dict[str, Any]],
    *,
    cookie_profile_id: str,
    account_label: str,
    cookie_file: str,
    checked_at: str,
) -> dict[str, Any]:
    unread_total = sum(max(0, int(item.get("unread_cnt") or 0)) for item in contacts)
    latest_contact = max(
        contacts,
        key=lambda item: item.get("latest_msg_time") or "",
        default=None,
    )
    latest_msg_time = latest_contact.get("latest_msg_time") if latest_contact else None

    return {
        "platform": "liepin",
        "cookie_profile_id": cookie_profile_id,
        "account_label": account_label,
        "cookie_file": cookie_file,
        "status": "success",
        "has_unread": int(unread_total > 0),
        "unread_total": unread_total,
        "contact_total": len(contacts),
        "latest_contact_name": latest_contact.get("name") if latest_contact else None,
        "latest_contact_company": latest_contact.get("company") if latest_contact else None,
        "latest_msg_time": latest_msg_time,
        "checked_at": checked_at,
        "error_message": None,
    }


def main() -> None:
    args = parse_args()
    cookie_path = resolve_cookie_path(args.cookie_file)
    if not cookie_path.exists():
        raise FileNotFoundError(f"Cookie file not found: {cookie_path}")

    cookie_profile_id = args.cookie_profile_id or derive_cookie_profile_id(cookie_path)
    account_label = args.account_label or derive_account_label(cookie_path)
    checked_at = datetime.utcnow().isoformat(timespec="seconds")

    database = Database(PATHS["database"])
    database.init()

    try:
        cookies = load_cookie_list(cookie_path)
        message_context = load_message_context(cookie_path)
        session = build_session(cookies, message_context=message_context)
        contacts = fetch_all_contacts(
            session,
            page_size=args.page_size,
            max_pages=args.max_pages,
            checked_at=checked_at,
            cookie_profile_id=cookie_profile_id,
            message_context=message_context,
        )
        summary = build_status_summary(
            contacts,
            cookie_profile_id=cookie_profile_id,
            account_label=account_label,
            cookie_file=cookie_path.name,
            checked_at=checked_at,
        )
    except Exception as exc:
        failure_status = {
            "platform": "liepin",
            "cookie_profile_id": cookie_profile_id,
            "account_label": account_label,
            "cookie_file": cookie_path.name,
            "status": "failed",
            "has_unread": 0,
            "unread_total": 0,
            "contact_total": 0,
            "latest_contact_name": None,
            "latest_contact_company": None,
            "latest_msg_time": None,
            "checked_at": checked_at,
            "error_message": str(exc),
        }
        if not args.dry_run:
            database.upsert_account_message_status(failure_status)
        print(
            f"[liepin-message-failed] cookie={cookie_path.name} "
            f"profile={cookie_profile_id} error={exc}"
        )
        raise SystemExit(1) from exc

    if not args.dry_run:
        database.upsert_account_message_status(summary)
        database.replace_message_contacts(
            platform="liepin",
            cookie_profile_id=cookie_profile_id,
            account_label=account_label,
            cookie_file=cookie_path.name,
            contacts=contacts,
            checked_at=checked_at,
        )

    print(
        f"[liepin-message] cookie={cookie_path.name} profile={cookie_profile_id} "
        f"account={account_label} contacts={summary['contact_total']} "
        f"unread_total={summary['unread_total']} has_unread={summary['has_unread']}"
    )
    if summary["latest_contact_name"]:
        print(
            f"[liepin-message-latest] contact={summary['latest_contact_name']} "
            f"company={summary['latest_contact_company'] or 'N/A'} "
            f"time={summary['latest_msg_time'] or 'N/A'}"
        )


if __name__ == "__main__":
    main()
