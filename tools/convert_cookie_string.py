import argparse
import json
from pathlib import Path
from urllib.parse import unquote


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a raw browser cookie string into Playwright cookies.json format."
    )
    parser.add_argument(
        "cookie_string",
        help="Raw cookie string copied from the browser, e.g. 'a=1; b=2'.",
    )
    parser.add_argument(
        "--output",
        default="cookies.json",
        help="Output JSON file path. Default: cookies.json",
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

    output_path = Path(args.output)
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
