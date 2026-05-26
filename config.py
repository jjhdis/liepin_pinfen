from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

SEARCH_CONFIG = {
    "city_code": "010200",
    "keywords": [
        "%E5%85%A8%E6%A0%88",
        "python",
        "c%23",
        "java",
    ],
    "pages_per_keyword": 5,
    "delay_min": 4,
    "delay_max": 9,
}

BROWSER_CONFIG = {
    "headless": True,
    "goto_timeout_ms": 30000,
}

PATHS = {
    "cookies": BASE_DIR / "cookies.json",
    "database": BASE_DIR / "jobs.db",
    "debug": BASE_DIR / "debug",
}

SCORE_THRESHOLD = 60
TOP_N_JOBS = 30
