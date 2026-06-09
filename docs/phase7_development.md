# Phase7 最终开发文档

> 实施日期：2026-06-08 ~ 2026-06-09
> 状态：已完成

---

## 1. 阶段定位

Phase7 目标是将 CLI 操作封装为 API + Web 管理后台，形成可长期稳定运行的完整系统。

截至 Phase7，项目已完成从"命令行脚本集合"到"守护进程 + Web 管理台 + 数据生命周期管理"的最终收敛。

---

## 2. 整体架构

```
┌──────────────────────┐     ┌──────────────────────┐
│   dashboard_server   │     │   crawler_daemon     │
│   (前端 UI，可随时开关)  │     │   (后台守护，常驻运行)    │
│                      │     │                      │
│  写: INSERT task_runs │     │  读: SELECT queued    │
│       status='queued' │     │  跑: subprocess.Popen │
│  读: SELECT task_runs │     │  写: UPDATE status     │
│       (展示进度)       │     │  收尸: reap finished  │
│                      │     │  串联: list→detail    │
└──────┬───────────────┘     └──────┬───────────────┘
       │                            │
       └─────────┬──────────────────┘
                 │
          ┌──────┴──────┐
          │   jobs.db   │  ← 唯一共享状态
          │  task_runs  │     (无 HTTP 通信)
          └─────────────┘
```

**运行方式：**
```bash
python crawler_daemon.py --daemon    # 后台守护
python dashboard_server.py            # Web 前端 (可随时开关)
```

**Web 页面：**

| 路径 | 页面 | 功能 |
|------|------|------|
| `/` | 抓取监控 | 详情状态、失败分布、最近 Job |
| `/scores` | Score 结果 | 评分结果筛选查看 |
| `/cookies` | Cookie 管理 | 账号状态、刷新鲜、添加 Cookie、恢复 |
| `/crawl` | 爬虫控制 | 提交 list/detail/postprocess 任务 |
| `/messages` | HR 消息 | 查看未读 HR 消息、一键刷新 |

---

## 3. 核心组件

### 3.1 crawler_daemon.py — 后台守护进程

独立后台进程，三个职责循环执行（每 3 秒一轮）：

**收尸 (reap)**：
- 轮询 `status='running'` 的任务，检查子进程是否退出
- 更新 task_runs 为 completed/failed
- list 完成后自动创建 detail 任务串联

**派活 (dispatch)**：
- 每个 platform 查一条 `status='queued'` 任务
- 同 platform 同时只允许一个 running 任务
- Popen 启动子进程 → 标记 running → 记录 pid

**维护**：
- 每 5 分钟扫描清理过期 cookie 文件

**启动时数据清理（2026-06-09 新增）**：
- 清理 8 张业务表中超过 30 天的记录
- 清理 `debug/` 目录超过 30 天的文件

### 3.2 dashboard_server.py — Web 管理后台

纯前端 + API，不直接管理子进程：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/` `/scores` `/cookies` `/crawl` `/messages` | GET | 页面 |
| `/api/summary` | GET | 抓取概览统计 |
| `/api/jobs` | GET | Job 列表（支持筛选） |
| `/api/score-summary` | GET | 评分统计 |
| `/api/score-results` | GET | 评分结果（支持筛选） |
| `/api/cookie-profiles` | GET | Cookie 列表 |
| `/api/cookie-refresh` | POST | 扫描 Cookie 目录 |
| `/api/cookie-refresh-login` | POST | 浏览器登录添加 Cookie |
| `/api/cookie-recover` | POST | 恢复 needs_manual_verify → ready |
| `/api/crawl/status` | GET | 活跃任务 + pending 计数 |
| `/api/crawl/tasks` | GET | 任务历史 |
| `/api/crawl/keywords` | GET | 可用关键词 |
| `/api/crawl/list` | POST | 提交 list 任务 |
| `/api/crawl/detail` | POST | 提交 detail 任务 |
| `/api/crawl/postprocess` | POST | 提交 postprocess 任务 |
| `/api/crawl/tasks/{id}/cancel` | POST | 取消任务 |
| `/api/message-contacts` | GET | HR 未读消息列表 |
| `/api/message-refresh` | POST | 刷新 HR 消息 |

### 3.3 task_runs 任务模型

```sql
CREATE TABLE task_runs (
    task_id       TEXT PRIMARY KEY,
    platform      TEXT NOT NULL,
    task_type     TEXT NOT NULL,       -- list / detail / postprocess
    status        TEXT NOT NULL,       -- queued / running / completed / failed / cancelled
    keyword       TEXT,
    profile_name  TEXT,
    pid           INTEGER,
    priority      INTEGER DEFAULT 0,
    parent_task_id TEXT,               -- list→detail 串联追溯
    progress_json TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    result_json   TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL
);
```

状态流转：`queued → running → completed / failed / cancelled`

---

## 4. 评分失败重试（2026-06-09 新增）

### 4.1 场景

本地 VPN 导致 DeepSeek API 偶尔不通、DB Browser 打开数据库导致 SQLite 锁。

### 4.2 实现

**`config.py`**：
```python
"max_retries": 3,
"retry_delay_seconds": 3.0,
```

**`ai/scorer.py`**：
- `score_job()` 新增重试循环，最多 3 次，固定 3 秒间隔
- `ScoreValidationError`（数据/解析问题）直接抛，不浪费重试
- 其余异常全部重试（网络不通、超时、锁库、VPN）
- 实际 API 调用抽到 `_call_api()` 保持代码整洁

**`score_jobs.py`**：
- 单条评分失败时 `continue` 继续下一条，不中断批处理
- 汇总输出增加 `failed=N` 字段

---

## 5. HR 消息管理（2026-06-09 新增）

### 5.1 已有基础

`check_liepin_messages.py` 和 `message_contacts` / `account_message_status` 表在 Phase6 已实现，通过猎聘 contact-list API 抓取 HR 消息。

### 5.2 新增内容

**`check_liepin_messages.py`**：
- 新增 `_clean_preview_text()` 清理消息预览中的 `>>`、`【】` 标记、多余空白

**`storage/database.py`**：
- `get_message_contacts(platform, cookie_profile_id)` — 只查 `unread_cnt > 0`，按 `latest_msg_time` 倒序
- `delete_old_message_contacts(before_days=7)` — 按 `latest_msg_time` 清理旧消息

**`dashboard_server.py`** — `/messages` 页面：
- Platform 下拉 + 手机号下拉（自动从 `cookie_profiles` 加载，无 cookie 时红色提示）
- 查询按钮 → 显示该账号未读 HR 消息列表
- 刷新按钮 → 调用 `check_liepin_messages.py` 获取最新消息 → 清理 7 天前旧数据
- 表格列：HR姓名、职位、最新消息预览、未读数、消息时间（`latest_msg_time`）

---

## 6. 数据库定时清理（2026-06-09 新增）

### 6.1 问题

数据库没有清理机制会持续膨胀。过期招聘信息也没有保留价值。

### 6.2 实现

**`config.py`**：
```python
"data_retention_days": 30,
```

**`storage/database.py`** — `cleanup_old_records()`：
删除 8 张表中超过 30 天的记录（`cookie_profiles` 除外，由 scan/refresh 管理）：

| 表 | 时间字段 |
|---|---------|
| `jobs` | `created_at` |
| `jobs_cleaned` | `cleaned_at` |
| `scores` | `scored_at` |
| `company_enriched` | `last_checked_at` |
| `crawl_log` | `created_at` |
| `task_runs` | `created_at` |
| `message_contacts` | `latest_msg_time` |
| `account_message_status` | `checked_at` |

**`crawler_daemon.py`**：
- `main()` 在 `db.init()` 后、主循环前执行清理
- 同步清理 `debug/` 目录超过 30 天的文件

---

## 7. 配置新增

```python
RUN_CONFIG = {
    # ... 已有配置 ...
    "data_retention_days": 30,      # 数据库记录保留天数
}

AI_CONFIG = {
    # ... 已有配置 ...
    "max_retries": 3,               # API 调用最大重试次数
    "retry_delay_seconds": 3.0,     # 重试间隔（秒）
}
```

---

## 8. 文件结构（最终版）

```
D:\channel\PythonProject2\
├── crawler_daemon.py             # 后台守护进程
├── dashboard_server.py           # Dashboard HTTP 服务（5 个页面）
├── main.py                       # CLI 入口 (list/detail)
├── rotate_liepin_cookies.py      # Cookie 复用轮换
├── postprocess_pipeline.py       # 后处理串联 (clean→enrich→score)
├── cookie_manager.py             # Cookie 管理模块
├── check_liepin_messages.py      # HR 消息抓取
├── config.py                     # 全局配置
│
├── crawler/                      # 抓取层
│   ├── browser.py, list_page.py, detail_page.py
│   ├── anti_detect.py, zhihu_client.py
├── cleaning/job_cleaner.py       # 清洗层
├── ai/                           # AI 评分层
│   ├── prompts.py, scorer.py, parser.py
├── storage/database.py           # 数据层（所有 SQL 操作）
├── tools/                        # 工具脚本
│
├── docs/                         # 文档
├── cookies/                      # Cookie 文件
├── logs/                         # Daemon 日志
├── debug/                        # 调试产物（30 天自动清理）
└── jobs.db                       # SQLite 数据库（30 天自动清理）
```

---

## 9. 验收状态

截至 Phase7 结束，项目已达到以下状态：

- 守护进程 + Web 管理台双进程架构稳定运行
- 5 个管理页面覆盖全部运维场景
- 任务队列支持前端提交 / daemon 执行 / 自动串联
- Cookie 完整生命周期管理（ready ↔ cooldown ↔ needs_manual_verify ↔ disabled）
- 评分 API 失败自动重试、单条失败不中断
- HR 消息页面支持筛选查询、一键刷新、文本清理
- 数据库 30 天自动清理，防止无限膨胀
- postprocess_pipeline 串联 clean → enrich → score

### 全部遗留待办已清零

| 事项 | 来源 | 状态 |
|------|------|:--:|
| 评分失败重试 | Phase3 | ✅ Phase7 已实现 |
| 枚举标准化 | Phase2 | ✅ 已确认不需要（AI 可直接理解中文文本） |
| 冷却机制 | Phase6 | ✅ Phase7 已实现 |
| 同日复用策略 | Phase6 | ✅ Phase7 已实现 |
| 人工验证恢复闭环 | Phase6 | ✅ 已实现 |
| API 封装 | Phase7 | ✅ 已实现 |
| 数据库定时清理 | — | ✅ Phase7 已实现 |
| HR 消息管理页面 | — | ✅ Phase7 已实现 |

---

## 10. 收尾改进建议（Boss / 智联接入前）

> 记录时间：2026-06-09
> 结论：当前系统已经接近可长期运行状态，后续重点不应继续堆功能，而应先补齐安全、风控闭环、计数准确性和多平台边界。

### 10.1 配置安全与运行数据隔离

**优先级：高**

当前 `config.py` 中 `AI_CONFIG["api_key"]` 存在明文默认值。建议改成只从环境变量读取：

```python
"api_key": os.getenv("DEEPSEEK_API_KEY", "")
```

如果环境变量不存在，则在 `JobScorer` 初始化时报错即可。这样可以避免后续提交代码或分享项目时泄露 API Key。

同时建议 `.gitignore` 增加以下运行数据：

```gitignore
jobs.db
cookies.json
zhihu_cookies.json
cookies/*.json
```

原因：数据库、Cookie、知乎 Cookie 都属于本地运行资产，不应进入版本管理。

### 10.2 Cookie 状态闭环需要防止被扫描重置

**优先级：高**

当前 `cookie_manager.scan_and_cleanup()` 在扫描到文件后会调用：

```python
db.upsert_cookie_profile(..., status="ready", ...)
```

而 `storage/database.py` 的 `upsert_cookie_profile()` 在冲突更新时会直接写入：

```sql
status = excluded.status
```

这会导致一个已经被标记为 `needs_manual_verify` 的账号，在下一次自动扫描 Cookie 文件时重新变成 `ready`。这会绕过人工验证恢复闭环。

建议规则：

- 新 profile 首次发现时可以写入 `ready`
- 已存在且状态为 `ready` / `cooldown` 时，可以更新 notes / tier / 文件信息
- 已存在且状态为 `needs_manual_verify` / `disabled` 时，不应由扫描任务自动恢复
- 只有前端“恢复”按钮或重新登录写入新 Cookie 文件时，才允许恢复为 `ready`

### 10.3 Cookie 今日计数应按实际详情条数累加

**优先级：高**

当前 `detail_count_today` 每跑完一批只 `+1`，实际含义更接近“今日批次数”，不是“今日详情条数”。如果后续使用 `cookie_daily_max_detail` 控制单 Cookie 每日上限，这个数会偏小。

建议调整：

- `mark_profile_used(platform, profile_name, detail_count=0)` 支持传入实际成功详情数
- `rotate_liepin_cookies.py` 从 detail 子进程输出或数据库差值中得到本批成功数
- `detail_count_today += detail_count`

如果短期不改实现，至少把字段含义改名或在文档中注明它目前是“批次数”。

### 10.4 `max_rounds` 计数逻辑需要修正

**优先级：中**

`rotate_liepin_cookies.py` 当前使用：

```python
used_in_run: set[str] = set()
round_count = sum(1 for u in used_in_run if u == pn)
```

由于 `set` 不保存重复值，同一个 profile 的 `round_count` 最大只能是 1，无法准确表达复用轮次。

建议改成：

```python
used_rounds: dict[str, int] = {}
used_rounds[profile_name] = used_rounds.get(profile_name, 0) + 1
```

这样 `--max-rounds` 才能真正限制同一 Cookie 在单次 rotate 中的复用次数。

### 10.5 Boss / 智联接入前先抽平台适配层

**优先级：中**

当前数据库、Cookie、任务队列已经预留了 `platform` 字段，但爬虫主逻辑仍然偏猎聘。Boss / 智联接入前建议先抽一层很薄的平台 adapter，避免新平台逻辑污染已经稳定的猎聘链路。

建议最小接口：

```python
class PlatformCrawler:
    platform: str

    async def list_jobs(...)
    async def fetch_detail(...)
    def detect_block(...)
    def resolve_cookie(...)
```

落地顺序建议：

1. 先把猎聘现有逻辑包成 `LiepinCrawler`
2. `main.py` 根据 `--platform` 分发到对应 adapter
3. Boss / 智联只新增 adapter，不改猎聘主流程
4. `crawler_daemon.py` 的 `platforms = ["liepin"]` 再扩展为配置项

### 10.6 增加每日运行体检视图

**优先级：中**

目前 dashboard 已经有多个页面，但后续多平台运行后，需要一个更快判断系统健康状态的入口。建议增加一个“每日体检”API 或页面，聚合以下指标：

- 各平台 ready / cooldown / needs_manual_verify / disabled Cookie 数
- 今日成功详情数、失败详情数、blocked / login_required 次数
- pending_detail / pending_clean / pending_score 数
- 最近一次 task_runs 状态
- 今日评分成功数、评分失败数
- 数据库大小、最近清理时间

这不是新功能，而是运维视角的总览，可以显著降低日常排查成本。

### 10.7 建议推进顺序

1. 配置安全与 `.gitignore`
2. Cookie `needs_manual_verify` 不被扫描自动恢复
3. Cookie 今日计数按实际详情数累加
4. 修正 `max_rounds` 计数
5. 抽平台 adapter
6. 再接 Boss / 智联

最终判断：Phase7 主体已经完成，后续最值得做的是“长期运行护栏”，而不是继续增加页面或流程。Boss / 智联接入时，重点是让平台差异留在 adapter 内部，不要把已经稳定的猎聘路径重新搅复杂。

---

## 附注

Phase7 的架构设计详细内容保留在：
- [phase7_architecture.md](/abs/path/D:/channel/PythonProject2/docs/phase7_architecture.md)

本文件为 Phase7 的最终收敛版，后续若与架构文档冲突，以本文件为准。
