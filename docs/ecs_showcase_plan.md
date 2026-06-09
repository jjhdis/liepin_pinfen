# ECS 功能展示计划

> 记录时间：2026-06-09
> 目标：将当前本地招聘数据系统包装成可用于面试展示的云端演示项目。爬虫、Cookie、AI 处理继续留在本地运行；ECS 只部署 MySQL、后端 API 和前端展示页。

---

## 1. 总体定位

当前项目已经满足个人使用场景，不计划公开售卖或长期商业化。ECS 展示的目的不是让云端系统真实爬取招聘平台，而是作为找工作时的项目筹码，展示以下能力：

- 本地低频采集招聘数据
- 自动清洗职位字段
- 企业风险证据增强
- AI 五维评分
- 数据同步到云端
- 云端前后端 CRUD / 筛选 / 排序 / Dashboard 展示

核心原则：

- 爬虫主程序不放 ECS
- Cookie 不上传 ECS
- SQLite 不直接暴露给公网
- ECS 只读或展示脱敏后的结果数据

---

## 2. 推荐架构

```text
本地电脑
├── jobs.db (SQLite)
├── 爬虫 / 清洗 / 企业增强 / AI 评分
└── sync_to_mysql.py
        |
        | 通过 SSH tunnel 或受限 MySQL 账号同步
        v
ECS
├── MySQL
├── 后端 API（CRUD / 查询 / 统计）
└── 前端展示页（职位评分、公司风险、任务概览）
```

说明：

- ECS 不能直接访问本地 SQLite 文件。SQLite 是本地文件数据库，不是网络数据库。
- 可以把 SQLite 文件手动上传到 ECS，但这不适合持续展示，也容易携带敏感运行数据。
- 最合理方式是本地写同步脚本，把需要展示的数据同步到 ECS MySQL。

---

## 3. ECS 展示范围

### 3.1 建议展示的数据

推荐同步以下业务结果表：

| 表 | 用途 |
|---|---|
| `jobs` | 原始职位基础信息、关键词、详情状态 |
| `jobs_cleaned` | 清洗后的薪资、公司名、AI 输入字段、质量标记 |
| `scores` | AI 评分、总分、建议、风险标签、评分理由 |
| `company_enriched` | 公司风险等级、知乎证据摘要、负面片段 |

### 3.2 不建议同步的数据

| 数据 | 原因 |
|---|---|
| `cookie_profiles` | 包含账号运行状态，不适合展示 |
| `crawl_log` | 运行日志量大，且展示价值低 |
| `message_contacts` | 涉及 HR 联系人信息，敏感 |
| `account_message_status` | 账号消息接口状态，不适合云端展示 |
| `cookies/*.json` | Cookie 绝对不能上传 |
| `zhihu_cookies.json` | Cookie 绝对不能上传 |
| `raw_html` / `raw_json` | 字段大、敏感、展示价值低 |

---

## 4. MySQL 展示库设计

不建议 100% 复刻本地 SQLite 表结构。展示系统可以设计成更干净的宽表，降低前后端复杂度。

### 4.1 推荐宽表：`job_showcase`

```sql
CREATE TABLE job_showcase (
    job_id VARCHAR(128) PRIMARY KEY,
    keyword VARCHAR(64),
    title VARCHAR(255),
    company_name VARCHAR(255),
    company_name_norm VARCHAR(255),
    city VARCHAR(64),
    salary_text VARCHAR(128),
    salary_min INT NULL,
    salary_max INT NULL,
    education VARCHAR(64),
    exp_years VARCHAR(64),
    company_size VARCHAR(128),
    jd_text MEDIUMTEXT,
    total_score INT NULL,
    verdict VARCHAR(64),
    score_activity INT NULL,
    score_jd INT NULL,
    score_company INT NULL,
    score_salary INT NULL,
    score_other INT NULL,
    company_risk_level VARCHAR(64),
    red_flags_json JSON NULL,
    reasoning TEXT,
    evidence_json JSON NULL,
    source_updated_at DATETIME NULL,
    synced_at DATETIME NOT NULL,
    INDEX idx_keyword (keyword),
    INDEX idx_total_score (total_score),
    INDEX idx_verdict (verdict),
    INDEX idx_company_risk_level (company_risk_level)
);
```

优点：

- 前端查询简单
- 后端 CRUD 简单
- 不暴露内部运行表
- 可以按展示需求脱敏、裁剪字段

### 4.2 可选统计表：`showcase_sync_runs`

```sql
CREATE TABLE showcase_sync_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mode VARCHAR(32) NOT NULL,
    rows_selected INT NOT NULL DEFAULT 0,
    rows_upserted INT NOT NULL DEFAULT 0,
    rows_deleted INT NOT NULL DEFAULT 0,
    started_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    status VARCHAR(32) NOT NULL,
    error_message TEXT
);
```

用于展示或排查最近一次同步状态。

---

## 5. 同步策略

### 5.1 第一阶段：全量覆盖

适合当前找工作展示阶段。

流程：

```text
1. 本地完成一轮爬取、清洗、企业增强、AI 评分
2. 执行 sync_to_mysql.py --mode full
3. 脚本读取 SQLite 中已评分职位
4. 清空 ECS MySQL 的 job_showcase
5. 重新写入最新展示数据
```

优点：

- 实现简单
- 不容易产生脏数据
- 面试展示足够稳定

适用条件：

- 展示数据量不大
- 每次同步频率不高
- 不需要实时同步

### 5.2 第二阶段：增量 upsert

等数据量变大后再做。

流程：

```text
1. 按 job_id 作为主键
2. 本地读取最近更新或最近评分的数据
3. MySQL 使用 INSERT ... ON DUPLICATE KEY UPDATE
4. 只更新变化数据
```

增量依据可以优先使用：

- `scores.scored_at`
- `jobs_cleaned.cleaned_at`
- `company_enriched.last_checked_at`
- `jobs.updated_at` 或 `created_at`

如果字段不完全统一，短期仍建议使用全量覆盖。

---

## 6. 本地同步脚本计划

建议新增脚本：

```text
tools/sync_sqlite_to_mysql.py
```

职责：

- 连接本地 `jobs.db`
- 查询展示所需字段
- 清洗或裁剪敏感字段
- 连接 ECS MySQL
- 写入 `job_showcase`
- 记录同步结果到 `showcase_sync_runs`

建议参数：

```bash
python tools/sync_sqlite_to_mysql.py --mode full
python tools/sync_sqlite_to_mysql.py --mode full --limit 200
python tools/sync_sqlite_to_mysql.py --mode incremental --since "2026-06-01 00:00:00"
```

MySQL 连接信息只从环境变量读取：

```text
SHOWCASE_MYSQL_HOST
SHOWCASE_MYSQL_PORT
SHOWCASE_MYSQL_USER
SHOWCASE_MYSQL_PASSWORD
SHOWCASE_MYSQL_DATABASE
```

不要把 ECS MySQL 密码写进代码。

---

## 7. ECS 安全策略

### 7.1 MySQL 暴露方式

推荐优先级：

1. SSH tunnel：本地通过 SSH 隧道连接 ECS MySQL
2. 安全组只允许本机公网 IP 访问 3306
3. 不建议 MySQL 3306 对公网 `0.0.0.0/0` 开放

### 7.2 MySQL 账号拆分

建议创建两个账号：

| 账号 | 用途 | 权限 |
|---|---|---|
| `sync_writer` | 本地同步脚本 | `SELECT`, `INSERT`, `UPDATE`, `DELETE` on showcase 库 |
| `showcase_reader` | ECS 后端 API | `SELECT` 为主，必要时少量 CRUD |

### 7.3 展示数据脱敏

上线前检查：

- 不上传 Cookie
- 不上传手机号
- 不上传 HR 私聊信息
- 不展示完整原始 HTML
- 不展示本地路径
- 不展示 API Key

---

## 8. 云端前后端展示功能

### 8.1 后端 API

最小功能：

| API | 功能 |
|---|---|
| `GET /api/jobs` | 职位列表，支持分页 |
| `GET /api/jobs/{job_id}` | 职位详情 |
| `GET /api/summary` | 总数、平均分、推荐数、风险公司数 |
| `GET /api/filters` | keyword / verdict / risk_level 可选项 |
| `POST /api/jobs` | 手动新增展示记录（CRUD 展示用） |
| `PUT /api/jobs/{job_id}` | 手动编辑展示记录 |
| `DELETE /api/jobs/{job_id}` | 删除展示记录 |

### 8.2 前端页面

建议页面：

- Dashboard：首页统计
- 职位评分列表：搜索、筛选、排序
- 职位详情：JD、评分理由、风险标签
- 公司风险：风险等级、证据摘要
- 数据同步状态：最近一次同步时间、同步条数、状态

### 8.3 面试表达重点

可以这样介绍：

> 本地系统负责低频采集、清洗、企业风险增强和 AI 评分；云端 ECS 只承载脱敏后的展示数据。通过同步脚本把 SQLite 中的结果发布到 MySQL，前后端基于 MySQL 做筛选、CRUD 和 Dashboard 展示。这样既保留本地爬虫运行的安全性，也能提供稳定的在线项目演示。

---

## 9. 推荐推进顺序

1. ECS 安装 MySQL
2. 创建 `job_showcase` 和 `showcase_sync_runs`
3. 本地新增 `tools/sync_sqlite_to_mysql.py`
4. 先实现 `--mode full`
5. ECS 后端读取 MySQL
6. 前端实现职位列表、详情、统计
7. 增加 CRUD 能力
8. 后续再做增量同步

---

## 10. 结论

当前项目本地自用已经够用。为了找工作展示，不需要把爬虫主程序搬到 ECS，也不需要让 ECS 访问本地 SQLite。最稳的方式是：

```text
本地 SQLite 作为生产数据源
本地同步脚本作为发布管道
ECS MySQL 作为展示数据库
ECS 前后端作为在线作品集入口
```

这套方案实现成本低、风险小，也更容易在面试中讲清楚系统边界和工程取舍。
