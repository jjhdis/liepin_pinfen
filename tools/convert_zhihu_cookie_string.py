import argparse
import json
from pathlib import Path


REQUIRED_KEYS = ("z_c0", "_xsrf")
OPTIONAL_KEYS = ("_zap", "tst")


def parse_cookie_string(cookie_string: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for raw_part in cookie_string.split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies[name] = value
    return cookies


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a raw Zhihu cookie string into zhihu_cookies.json format."
    )
    parser.add_argument(
        "cookie_string",
        help="Raw cookie string copied from the browser, e.g. 'a=1; b=2'.",
    )
    parser.add_argument(
        "--output",
        default="zhihu_cookies.json",
        help="Output JSON file path. Default: zhihu_cookies.json",
    )
    args = parser.parse_args()

    cookies = parse_cookie_string(args.cookie_string)
    output = dict(cookies)
    for key in REQUIRED_KEYS:
        output.setdefault(key, "")

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    missing = [key for key, value in output.items() if not value]
    print(f"wrote zhihu cookies to {output_path}")
    if missing:
        print("missing required keys:", ", ".join(missing))
    else:
        print("all required keys present")
        optional_missing = [key for key in OPTIONAL_KEYS if not output.get(key)]
        if optional_missing:
            print("optional keys missing:", ", ".join(optional_missing))


if __name__ == "__main__":
    main()
