import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote


BASE_DIR = Path(__file__).resolve().parent

SEARCH_CONFIG = {
    "city_code": "020",
    "dq_code": "020",
    "keywords": [
        "全栈",
        "python",
        "c#",
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
    # 是否在 cookie 轮换时自动触发后处理 pipeline。
    # True: 每份 cookie 跑完后检查待清洗数量，达到阈值时自动执行 clean→enrich→score
    # False: 所有后处理阶段手动执行
    "auto_postprocess": False,
    # 触发自动后处理的最小待清洗职位数
    "auto_postprocess_min_jobs": 50,
    # Cookie 文件最大保留天数，超过自动删除
    "cookie_max_age_days": 2,
    # 单次 rotate 最多使用几份 cookie，None 或 0 = 不限制
    "cookie_max_per_run": 3,
    # 每批 detail 跑完后为 cookie 设置的冷却时间（小时）
    "cookie_cooldown_hours": 2,
    # 数据库记录保留天数，超过自动清理（cookie_profiles 除外）
    "data_retention_days": 30,
    # 单个 cookie 每日最大 detail 条数上限，0 = 不限
    "cookie_daily_max_detail": 0,
    # --- crawler daemon ---
    # 守护进程主循环轮询间隔（秒）
    "daemon_poll_interval_seconds": 3,
    # PID 文件路径
    "daemon_pid_file": "crawler_daemon.pid",
    # 日志目录
    "daemon_log_dir": "logs",
    # Cookie 自动扫描间隔（秒）
    "daemon_cookie_scan_interval_seconds": 300,
    "list": {
        # 列表页默认从第几页开始抓，以及连续抓多少页。
        "page": 0,
        "pages": 1,
        # 每个列表页默认只保留前多少条职位进入待抓详情队列。
        "store_top_n": 30,
        # 列表页之间的等待时间，单位秒。
        "min_delay": 60.0,
        "max_delay": 120.0,
        # 是否在开跑前/翻页前要求人工确认。
        "interactive": False,
    },
    "detail": {
        # 单次 detail 命令默认最多处理多少条 pending 职位。
        "max_detail": 25,
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
    "cookie_dir": BASE_DIR / "cookies",
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
    "summary_top_n": 10,
    "filtered_top_n": 3,
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

LIEPIN_MESSAGE_CONFIG = {
    "contact_list_api": "https://api-c.liepin.com/api/com.liepin.im.c.contact.get-contact-list",
    "origin": "https://c.liepin.com",
    "referer": "https://c.liepin.com/",
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
    ),
    "accept": "application/json, text/plain, */*",
    "accept_language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "content_type": "application/x-www-form-urlencoded",
    "sec_ch_ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
    "sec_ch_ua_mobile": "?0",
    "sec_ch_ua_platform": '"Windows"',
    "sec_fetch_dest": "empty",
    "sec_fetch_mode": "cors",
    "sec_fetch_site": "same-site",
    "x_client_type": "web",
    "x_fscp_fe_version": "1.0.0",
    "x_fscp_std_info": '{"client_id":"11156"}',
    "x_fscp_version": "1.1",
    "page_size": 50,
    "max_pages": 20,
    "request_timeout_seconds": 30.0,
}

AI_CONFIG = {
    "api_key": os.getenv("DEEPSEEK_API_KEY", "sk-48560546f57b4262bdaeca0353c58bf5"),
    "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    "temperature": 0.1,
    "max_tokens": 900,
    "request_timeout_seconds": 120.0,
    "max_retries": 3,
    "retry_delay_seconds": 3.0,
    "batch_size": 50,
    "max_days_since_update": 14,
}

SCORE_THRESHOLD = 60
TOP_N_JOBS = 30


def normalize_keyword(keyword: Optional[str]) -> Optional[str]:
    if keyword is None:
        return None

    normalized = unquote(str(keyword).strip())
    if not normalized:
        return None

    alias_map = {
        "csharp": "c#",
        "全棧": "全栈",
    }
    return alias_map.get(normalized.lower(), normalized)
