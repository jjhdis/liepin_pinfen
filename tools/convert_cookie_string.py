import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = BASE_DIR / "cookies"


def parse_cookie_string(cookie_string: str, domain: str, path: str) -> list[dict]:
    cookies: list[dict] = []
    seen_names: set[str] = set()

    for raw_part in cookie_string.split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue

        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()

        if not name:
            continue

        # Keep the last occurrence if the same cookie name appears multiple times.
        if name in seen_names:
            cookies = [item for item in cookies if item["name"] != name]

        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
            }
        )
        seen_names.add(name)

    return cookies


def _sanitize_phone_for_filename(phone: Optional[str]) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits or "unknown"


def _build_default_output_path(output_dir: str, phone: Optional[str]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    phone_tag = _sanitize_phone_for_filename(phone)
    filename = f"cookie_{timestamp}_{phone_tag}_liepin.json"
    return Path(output_dir) / filename


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a raw browser cookie string into a named Playwright cookie JSON file."
    )
    parser.add_argument(
        "cookie_string",
        help="Raw cookie string copied from the browser, e.g. 'a=1; b=2'.",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file path. Overrides the auto-generated filename.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory used for auto-generated cookie files. Default: project_root/cookies",
    )
    parser.add_argument(
        "--phone",
        help="Optional phone number tag used in the generated filename.",
    )
    parser.add_argument(
        "--domain",
        default=".liepin.com",
        help="Cookie domain. Default: .liepin.com",
    )
    parser.add_argument(
        "--path",
        default="/",
        help="Cookie path. Default: /",
    )
    parser.add_argument(
        "--decode-preview",
        action="store_true",
        help="Print a decoded preview for percent-encoded values such as user_name.",
    )
    args = parser.parse_args()

    cookies = parse_cookie_string(
        cookie_string=args.cookie_string,
        domain=args.domain,
        path=args.path,
    )

    output_path = Path(args.output) if args.output else _build_default_output_path(args.output_dir, args.phone)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"wrote {len(cookies)} cookies to {output_path}")

    if args.decode_preview:
        for item in cookies:
            decoded = unquote(item["value"])
            if decoded != item["value"]:
                print(f"{item['name']} = {decoded}")


if __name__ == "__main__":
    main()
