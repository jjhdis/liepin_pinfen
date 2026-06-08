# Phase7 架构文档 — 爬虫管理后台进程

> 实施日期：2026-06-08
> 状态：已完成

---

## 1. 架构全景

```
┌──────────────────────┐     ┌──────────────────────┐
│   dashboard_server   │     │   crawler_daemon     │
│   (前端 UI，可随时开关)  │     │   (后台守护，一直跑)    │
│                      │     │                      │
│  写: INSERT task_runs │     │  读: SELECT queued    │
│       status='queued' │     │  跑: subprocess.Popen │
│                      │     │  写: UPDATE status     │
│  读: SELECT task_runs │     │  收尸: reap finished  │
│       (展示进度)       │     │  串联: list→detail    │
└──────┬───────────────┘     └──────┬───────────────┘
       │                            │
       └─────────┬──────────────────┘
                 │
          ┌──────┴──────┐
          │   jobs.db   │  ← 唯一共享状态
          │  task_runs  │     (无 HTTP 通信)
          └─────────────┘
```

## 2. 任务模型

### task_runs 表

```sql
CREATE TABLE task_runs (
    task_id       TEXT PRIMARY KEY,
    platform      TEXT NOT NULL,            -- liepin / boss / zhilian
    task_type     TEXT NOT NULL,            -- list / detail / postprocess
    status        TEXT NOT NULL,            -- queued / running / completed / failed / cancelled
    keyword       TEXT,
    profile_name  TEXT,
    pid           INTEGER,
    priority      INTEGER DEFAULT 0,
    parent_task_id TEXT,                    -- list→detail 串联追溯
    progress_json TEXT,                     -- {done:50, total:125}
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    result_json   TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL
);
```

### 状态流转

```
queued ──daemon拾取──→ running ──进程退出──→ completed
                           │                    │
                           │ (list completed    │
                           │  有新pending?       │
                           │  →自动创建detail)   │
                           │                    │
                           ├─ 用户取消 ─→ cancelled
                           └─ 异常退出 ─→ failed
```

### 平台互斥

同一 platform 同一时间只允许一个 running 任务。queued 任务在排队中不会被拾取，直到 running 槽位空出。

## 3. 核心组件

### 3.1 crawler_daemon.py

独立后台进程，三个职责循环执行（每 3 秒一轮）：

**收尸 (reap)**：
- 轮询所有 `status='running'` 的任务
- 检查子进程是否退出（`proc.poll()`）
- 更新 task_runs 为 completed/failed
- list 完成后检查是否有新 pending → 自动创建 detail 任务

**派活 (dispatch)**：
- 每个 platform 查一条 `status='queued'` 任务
- 按 priority ASC, created_at ASC 排序
- 如该 platform 已有 running 则跳过
- Popen 启动子进程 → 标记 running → 记录 pid

**维护**：
- 每 5 分钟扫描清理过期 cookie 文件

**启动方式**：
```bash
python crawler_daemon.py              # 前台（调试）
python crawler_daemon.py --daemon     # 后台（写PID，重定向日志到 logs/）
python crawler_daemon.py --stop       # 停止（读PID发SIGTERM）
```

### 3.2 dashboard_server.py

纯前端 + API，不直接管理子进程：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/crawl` | GET | 爬虫控制页 |
| `/api/crawl/status` | GET | 活跃任务列表 + pending 计数 |
| `/api/crawl/tasks` | GET | 任务历史（最近 20 条） |
| `/api/crawl/keywords` | GET | 可用关键词 |
| `/api/crawl/list` | POST | 提交 list 任务 (queued) |
| `/api/crawl/detail` | POST | 提交 detail 任务 (queued) |
| `/api/crawl/postprocess` | POST | 提交 postprocess 任务 (queued) |
| `/api/crawl/tasks/{id}/cancel` | POST | 取消任务 |

前端轮询：10 秒一次，只轮询 `/api/crawl/status`。

### 3.3 rotate_liepin_cookies.py

Cookie 复用轮换调度，由 daemon 在 detail 任务中调用：

```
while pending_jobs > 0:
    cookie = pick_best_available()      # ready + cooldown已过期
    if not cookie → 报告最早恢复时间 → 退出
    run main.py detail --max-detail 25
    mark_profile_used()                 # 更新计数
    mark_profile_cooldown(2h)           # 设冷却
    auto-check postprocess threshold
```

复用机制：
- 2 小时后冷却自动过期（查询时判断 `cooldown_until <= now`）
- 不需要定时任务恢复状态
- `--max-rounds` 控制每 cookie 最大复用轮次
- `--daily-max` 控制单 cookie 每日上限

## 4. Cookie 管理体系

### 状态模型

```
ready ──使用──→ cooldown ──2h到期──→ ready (自动恢复)
  │                │
  └──触发风控──→ needs_manual_verify (需人工)
                     │
                     └──废弃──→ disabled
```

### 查询优先级

可用 cookie 排序：ready > cooldown(已过期)，然后今天用得少的 > 最久没用的。

### 工具链

| 工具 | 功能 |
|------|------|
| `tools/refresh_liepin_cookies.py` | 半自动浏览器登录 + 导出 Cookie |
| `check_liepin_messages.py` | 验证消息接口可用性 |
| `cookie_manager.py` | 扫描/清理/状态管理模块 |
| `rotate_liepin_cookies.py` | 复用轮换调度 |

## 5. 数据管道

```
Phase1 list    →  jobs (job_id + detail_url)
Phase1 detail  →  jobs (title, salary, jd_text, detail_status)
Phase2 clean   →  jobs_cleaned (ai_input_json, company_check)
Phase4 enrich  →  company_enriched (知乎证据)
Phase3 score   →  scores (五维度评分)
```

串联入口：`postprocess_pipeline.py` (clean → enrich → score)

## 6. 配置一览

```python
RUN_CONFIG = {
    "auto_postprocess": False,
    "auto_postprocess_min_jobs": 50,
    "cookie_max_age_days": 2,
    "cookie_max_per_run": 3,
    "cookie_cooldown_hours": 2,           # 每批后冷却
    "cookie_daily_max_detail": 0,         # 单日上限(0=不限)
    "daemon_poll_interval_seconds": 3,    # 主循环间隔
    "daemon_pid_file": "crawler_daemon.pid",
    "daemon_log_dir": "logs",
    "daemon_cookie_scan_interval_seconds": 300,
    "list": {...},
    "detail": {...},
}
```

## 7. 运行方式

```bash
# 启动
python crawler_daemon.py --daemon    # 后台守护
python dashboard_server.py            # 前端 (可随时开关)

# 浏览器
http://127.0.0.1:8765/crawl           # 爬虫控制
http://127.0.0.1:8765/                # 抓取监控
http://127.0.0.1:8765/scores          # 评分结果
http://127.0.0.1:8765/cookies         # Cookie 管理

# CLI 直接跑（不走 daemon）
python main.py list --keyword python
python main.py detail --max-detail 25
python rotate_liepin_cookies.py --output-json

# 停止
python crawler_daemon.py --stop
```

## 8. 文件结构

```
D:\channel\PythonProject2\
├── crawler_daemon.py             # 🆕 后台守护进程
├── dashboard_server.py           # Dashboard HTTP 服务
├── main.py                       # CLI 入口 (list/detail)
├── rotate_liepin_cookies.py      # Cookie 复用轮换
├── postprocess_pipeline.py       # 后处理串联
├── cookie_manager.py             # Cookie 管理模块
├── config.py                     # 全局配置
│
├── crawler/                      # 抓取层
│   ├── browser.py, list_page.py, detail_page.py
│   ├── anti_detect.py, zhihu_client.py
├── cleaning/job_cleaner.py       # 清洗层
├── ai/prompts.py, scorer.py, parser.py  # AI评分层
├── storage/database.py           # 数据层（所有SQL操作）
├── tools/                        # 工具脚本
│
├── docs/                         # 文档
│   ├── 功能实现文档.md
│   └── phase7_architecture.md
├── cookies/                      # Cookie 文件
├── logs/                         # Daemon 日志
└── jobs.db                       # SQLite 数据库
```

## 9. Cookie 恢复功能

在 `/cookies` 页面，`needs_manual_verify` 状态的 profile 行会显示"恢复"按钮。点击后调用：

```
POST /api/cookie-recover  {platform, profile_name}
  → 清除 cooldown_until, last_error, last_error_at
  → status 恢复为 ready
```

## 10. 遗留待办

以下事项不在 Phase7 范围内，记录于此供后续参考：

| # | 事项 | 优先级 | 说明 |
|---|------|:--:|------|
| 1 | **评分失败重试** | 中 | `ai/scorer.py` 中 API 调用失败时自动重试 2-3 次 |
| 2 | **枚举标准化** | 低 | `cleaning/job_cleaner.py` 中公司规模/学历/经验做统一映射 |

### 已闭合（不再需要处理）

| 事项 | 结论 |
|------|------|
| 稳定性测试 | 已验证：单 cookie 每日上限约 30 条，当前保守使用 25 |
| 企业增强证据质量 | 已实现：三级风险词过滤 + 摘要截断 |
| Boss/智联接入 | 暂不考虑 |
| WebSocket 实时推送 | 暂不考虑 |
