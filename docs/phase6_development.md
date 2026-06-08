# Phase6 开发文档

## 阶段定位

Phase6 按规划进入**账号与风控恢复管理**，同时落地了 Phase5 遗留的 pipeline 收敛和 cookie 管理基础设施。2026-06-05 集中开发完成。

---

## 1. Cookie Profile 基础设施

### 1.1 `cookie_profiles` 表

```sql
CREATE TABLE cookie_profiles (
    platform      TEXT NOT NULL,    -- liepin / boss / zhilian
    profile_name  TEXT NOT NULL,    -- 手机号，对应文件名 cookie_*_{phone}_{platform}.json
    status        TEXT DEFAULT 'ready',
    last_used_at  TEXT,
    detail_count_today  INTEGER DEFAULT 0,
    detail_total_count INTEGER DEFAULT 0,
    cooldown_until      TEXT,
    last_error    TEXT,
    last_error_at TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (platform, profile_name)
);
```

状态枚举：`ready` | `cooldown` | `needs_manual_verify` | `disabled`

### 1.2 `crawl_log.cookie_profile_name`

追溯每次请求使用的是哪个 cookie profile。已加建表和迁移逻辑。

### 1.3 数据库方法

- `upsert_cookie_profile()` — INSERT OR REPLACE，支持 reset_counters
- `increment_cookie_usage()` — 跨天自动重置 detail_count_today
- `update_cookie_profile_status()` — 状态变更（block → needs_manual_verify）
- `get_ready_cookie_profiles()` — 查询 ready 状态
- `ready_for_clean_count()` — 统计待清洗职位数

---

## 2. Cookie 管理模块 `cookie_manager.py`

可复用模块，CLI 和前端均可调用。

### 2.1 `scan_and_cleanup(platform)`

每次调用执行四步：

1. **清理过期文件**：文件名日期 <= (今天 - cookie_max_age_days) → 删除
2. **按手

机号去重**：同 profile_name 只保留最新文件
3. **同步 DB**：upsert cookie_profiles，检测文件变化时自动清零计数器
4. **按新鲜度排序返回**：fresh（当天）> day_old（昨天）> stale（更早但在保留期内）

### 2.2 `mark_profile_used(platform, profile_name)`

每次 detail 批次成功后调用，更新 last_used_at、detail_count_today（跨天自动从1开始）、detail_total_count。

### 2.3 `mark_profile_blocked(platform, profile_name, reason)`

C 类事件触发后调用，标记 status=needs_manual_verify，记录错误原因和时间。

### 2.4 `get_available_profiles(platform)`

从 DB 查询 ready 状态的 profile 列表。

---

## 3. Cookie 轮换 `rotate_liepin_cookies.py`

### 3.1 改造内容

- 移除 `--cookie-date` 和日期过滤，改用 `scan_and_cleanup()` 智能发现
- 优先级：当天 fresh → 昨天 day_old → 更早 stale
- 每份 cookie 跑完后 `mark_profile_used()`
- detail 失败时 `mark_profile_blocked()` 然后**继续下一份**（不再硬退出）
- 新增 `--auto` / `--no-auto` 控制自动后处理
- 新增 `--platform` 参数
- `--max-cookies` 默认值走 config `cookie_max_per_run`

### 3.2 自动后处理

每份 cookie 成功后检查 `ready_for_clean_count >= auto_postprocess_min_jobs`，达到阈值自动执行 `postprocess_pipeline.py`。

---

## 4. Pipeline 收敛

### 4.1 `postprocess_pipeline.py`

- Clean 阶段 `default=50`
- Enrich 阶段 `default=None`（全部 pending），安全上限 `max_requests_per_run=20`

### 4.2 评分准入守卫

`get_jobs_ready_for_scoring` 新增条件：排除 `company_check_status='pending'` 的职位。防止知乎还没爬完就送入评分。

### 4.3 数据表同步

`company_enrich.py` limit 改为默认 None，配合 `max_requests_per_run` 安全上限。

---

## 5. Dashboard Cookie 管理页

`dashboard_server.py` 新增 `/cookies` 页面：

- 统计卡片：可用数量、需验证数量、总数
- 筛选：按平台 + 状态
- 刷新扫描按钮：调用 `scan_and_cleanup()` 重新扫描清理
- 表格：平台、账号、状态、今日详情、累计详情、最后使用、备注（含 tier 标签）
- 30 秒自动刷新

---

## 6. Cookie 刷新登录

### 6.1  —  模式

新增  flag，前端调用时使用。自动检测逻辑：

- 不依赖 cookie 数量变化（容易在验证码步骤误触发）
- 改为检测**特定 auth cookie 是否出现**：、、、
- 这 4 个 cookie 只有猎聘完整登录后才写入，输入验证码阶段不会出现
- 每 3 秒轮询一次，最长等待 300 秒

### 6.2  前端集成

-  — 接收 ，调用脚本  模式
- 登录成功后自动执行  同步新 cookie
- 前端：手机号输入框 + "添加 Cookie"按钮 + 状态提示

---

## 7. Crawl Log 追溯

 新增  参数， 自动传入。

 记录每次请求使用的账号，支持按账号维度统计查询。

---

## 8. 配置新增

```python
RUN_CONFIG = {
    "auto_postprocess": False,
    "auto_postprocess_min_jobs": 50,
    "cookie_max_age_days": 2,
    "cookie_max_per_run": 3,
}
```

---

## 已完成的 Phase6 计划项

| 计划项 | 状态 |
|--------|------|
| C 类事件定义 | ✅ blocked/login_required → needs_manual_verify |
| Cookie profile 表 + crawl_log 追踪字段 | ✅ |
| 四种状态模型 (ready/cooldown/needs_manual_verify/disabled) | ✅ 表已支持，cooldown 逻辑待接 |
| Cookie 智能发现与优先级 (fresh/day_old/stale) | ✅ |
| 过期文件自动清理 | ✅ |
| detail 失败后标记并继续切换 | ✅ |
| 前端 Cookie 管理页（查看/筛选/刷新扫描/添加Cookie） | ✅ |
| 浏览器登录自动检测 + 前端一键添加 Cookie | ✅ |
| crawl_log 写入 cookie_profile_name 追溯 | ✅ |
| 计数器管理（新文件清零 + 跨天清零） | ✅ |

---

## 剩余待办

### Phase6 内部未完成

| 事项 | 说明 |
|------|------|
| **冷却机制** | ✅ Phase7 已实现 — `mark_profile_cooldown()` + 查询时自动判断 |
| **同日复用策略** | ✅ Phase7 已实现 — for→while 复用轮换 |
| **人工验证恢复闭环** | ✅ 2026-06-08 已实现 — `/cookies` 页面新增"恢复"按钮 |

### 跨 Phase 遗留

| 事项 | 来源 | 状态 |
|------|------|:--:|
| 稳定性测试计划执行 | Phase5 test_plan | ✅ 已验证 — 单 cookie 上限 30 条，保守使用 25 |
| 企业增强证据质量提升 | Phase4 | ✅ 已实现 |
| API 封装 (Phase7) | 已记录 docs/phase7_planning.md | ✅ 已实现 |
| 评分失败重试 | Phase3 | ❌ 仍开放 |
| 公司规模/学历/经验枚举标准化 | Phase2 | ❌ 仍开放 |

### 建议推进顺序

1. ✅ 稳定性基准测试 — 已完成（30 为上限，保守 25）
2. ✅ 冷却机制 + 同日复用 — Phase7 已实现
3. ✅ 人工验证恢复闭环 — 2026-06-08 已实现
4. ✅ API 封装（Phase7）— 已实现
5. 评分失败重试（Phase3）+ 枚举标准化（Phase2）— 仅剩的两项
