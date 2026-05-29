import os
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
    "zhihu_cookies": BASE_DIR / "zhihu_cookies.json",
    "database": BASE_DIR / "jobs.db",
    "debug": BASE_DIR / "debug",
}

ZHIHU_CONFIG = {
    "base_url": "https://www.zhihu.com",
    "search_api": "https://www.zhihu.com/api/v4/search_v3",
    "search_params": {
        "gk_version": "gz-gaokao",
        "t": "general",
        "correction": 1,
        "offset": 0,
        "limit": 20,
        "filter_fields": "",
        "lc_idx": 0,
        "show_all_topics": 0,
        "search_source": "Normal",
    },
    "summary_top_n": 3,
    "search_delay_min": 5.0,
    "search_delay_max": 10.0,
    "max_requests_per_run": 20,
    "cache_ttl_hours": 168,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
    "accept_language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "x_zse_93": "101_3_3.0",
    "x_zse_96": "2.0_3A91I2Rl2B7qYDRa/InaVucYXH03=FWy1stjfm/swsR5LyeTd=Jwqr5SyBlxCte0",
    "x_api_version": "3.0.91",
    "x_app_za": "OS=Web",
    "sec_ch_ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
    "sec_ch_ua_mobile": "?0",
    "sec_ch_ua_platform": '"Windows"',
    "source": "zhihu_search_v1",
}

AI_CONFIG = {
    "api_key": os.getenv("DEEPSEEK_API_KEY", "sk-48560546f57b4262bdaeca0353c58bf5"),
    "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    "temperature": 0.1,
    "max_tokens": 900,
    "request_timeout_seconds": 120.0,
    "batch_size": 5,
    "max_days_since_update": 7,
}

SCORE_THRESHOLD = 60
TOP_N_JOBS = 30
