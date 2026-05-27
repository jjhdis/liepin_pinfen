from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

SEARCH_CONFIG = {
    "city_code": "020",
    "dq_code": "020",
    "keywords": [
        "%E5%85%A8%E6%A0%88",
        "python",
        "c%23",
        "java",
    ],
    "pages_per_keyword": 5,
    "page_size": 40,
    "delay_min": 4,
    "delay_max": 9,
    "pub_time": "",
    "work_year_code": "0",
    "salary_code": "",
    "job_kind": "",
    "comp_scale": "",
    "comp_kind": "",
    "comp_stage": "",
    "edu_level": "",
    "industry": "",
    "other_city": "",
    "sfrom": "search_job_pc",
    "scene": "input",
}

# 运行默认参数。
# 命令行如果不显式传参，就会使用这里的值。
RUN_CONFIG = {
    "list": {
        # 列表页默认从第几页开始抓，以及连续抓多少页。
        "page": 0,
        "pages": 1,
        # 列表页之间的等待时间，单位秒。
        "min_delay": 60.0,
        "max_delay": 120.0,
        # 是否在开跑前/翻页前要求人工确认。
        "interactive": False,
    },
    "detail": {
        # 单次 detail 命令默认最多处理多少条 pending 职位。
        "max_detail": 10,
        # 相邻两个详情页之间的常规等待时间，单位秒。
        "min_delay": 45.0,
        "max_delay": 90.0,
        "interactive": False,
        # 启动 detail 批处理前先执行一次冷却，单位秒。
        "startup_cooldown_min": 120.0,
        "startup_cooldown_max": 180.0,
        # 每处理多少条就询问一次是否继续。
        "confirm_every": 1,
        # 每处理多少条后进入一段更长的冷却时间。
        # 设为 0 表示关闭批内冷却。
        "cooldown_every": 10,
        # 冷却时间范围，单位秒。
        "cooldown_min": 180.0,
        "cooldown_max": 240.0,
    },
}

BROWSER_CONFIG = {
    "headless": True,
    "goto_timeout_ms": 30000,
    "locale": "zh-CN",
    "timezone_id": "Asia/Shanghai",
    "viewport": {"width": 1440, "height": 900},
}

PATHS = {
    "cookies": BASE_DIR / "cookies.json",
    "database": BASE_DIR / "jobs.db",
    "debug": BASE_DIR / "debug",
}

SCORE_THRESHOLD = 60
TOP_N_JOBS = 30
