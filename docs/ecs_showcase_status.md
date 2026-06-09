# ECS 云端展示项目 — 完成状态

> 记录时间：2026-06-09
> 状态：开发完成，待部署

---

## 1. 项目定位

将本地招聘数据系统的评分结果同步到 ECS 云端，通过 Web 前后端展示给面试官，作为找工作时的项目筹码。

核心原则：
- 爬虫、Cookie、AI 处理留在本地，不上云
- ECS 只部署 MySQL + 后端 API + 前端展示页
- 通过同步脚本把 SQLite 结果发布到 MySQL

---

## 2. 完成项

### 2.1 前端 (`liepinecs/front/`)

| 项 | 状态 | 说明 |
|---|:--:|------|
| React + Vite + TypeScript 项目 | ✅ | 工程化前端，可直接 `npm run build` 部署 |
| Tailwind CSS v4 | ✅ | 零手写 CSS |
| 概览 Dashboard | ✅ | 统计卡片 + 评分分布条形图 |
| 职位列表页 | ✅ | keyword / verdict / risk / sort 筛选 + 分页 |
| 职位详情弹窗 | ✅ | 五维评分条、AI 分析理由、风险标记、企业证据、JD 预览 |
| 敏感词清理 | ✅ | 页面标题/品牌名使用 "Job Radar"，不出现 Liepin |

### 2.2 后端 (`liepinecs/backend/`)

| 项 | 状态 | 说明 |
|---|:--:|------|
| FastAPI 应用 | ✅ | 4 个 GET 端点，纯查询 |
| `GET /api/summary` | ✅ | 总数、平均分、apply/caution/skip 计数 |
| `GET /api/filters` | ✅ | 可选 keyword / verdict / risk_level |
| `GET /api/jobs` | ✅ | 分页列表，支持筛选排序 |
| `GET /api/jobs/{job_id}` | ✅ | 单条详情 |
| `schema.sql` | ✅ | `job_showcase` + `showcase_sync_runs` 建表 |
| CORS 中间件 | ✅ | 允许前端跨域访问 |
| `.env.example` | ✅ | MySQL 连接配置模板 |
| Swagger 文档 | ✅ | FastAPI 自动生成 `/docs` |

### 2.3 数据同步脚本 (`PythonProject2/tools/`)

| 项 | 状态 | 说明 |
|---|:--:|------|
| `sync_sqlite_to_mysql.py` | ✅ | SQLite → MySQL 同步 |
| `--mode full` | ✅ | 清空后全量写入 |
| `--mode incremental` | ✅ | ON DUPLICATE KEY UPDATE 增量 |
| `--dry-run` | ✅ | 预览不写入 |
| `--limit N` | ✅ | 限制同步条数 |
| 环境变量读取 | ✅ | MYSQL_HOST / USER / PASSWORD / DATABASE |
| 同步记录 | ✅ | 写入 `showcase_sync_runs` 表 |

### 2.4 联表查询映射

同步脚本从 SQLite 的 4 张表联表查询，映射到 MySQL 的 1 张宽表：

```
scores + jobs_cleaned + jobs + company_enriched
                    ↓
              job_showcase
```

只同步 `score_status = 'success'` 的已评分职位，按 `total_score` 从高到低排序。

---

## 3. 待部署项

| 项 | 优先级 | 说明 |
|---|:--:|------|
| ECS 安装 MySQL 8.0+ | 高 | 最小配置 1C1G 即可 |
| 执行 `schema.sql` 建库建表 | 高 | 复制粘贴到 MySQL 客户端 |
| 创建 MySQL 账号 | 高 | `showcase_reader`（读） + `sync_writer`（写） |
| 安全组配置 | 高 | 3306 只对本地 IP 或 SSH tunnel 开放 |
| 部署后端 | 中 | `uvicorn main:app --host 0.0.0.0 --port 8000` |
| 部署前端 | 中 | `nginx` 指向 `front/dist/`，或 `npm run preview` |
| 首次同步 | 中 | `python tools/sync_sqlite_to_mysql.py --mode full` |
| 定时同步 | 低 | crontab 每天跑一次增量同步 |

---

## 4. 项目文件结构

```
D:\channel\
├── PythonProject2/               # 本地系统（爬虫 + Dashboard）
│   ├── tools/
│   │   └── sync_sqlite_to_mysql.py   # 同步脚本
│   └── docs/
│       ├── ecs_showcase_plan.md      # 架构设计
│       └── ecs_showcase_status.md    # 本文档
│
└── liepinecs/                    # ECS 展示项目
    ├── front/                    # React + Vite + Tailwind
    │   └── src/components/
    │       ├── Dashboard.tsx
    │       ├── JobList.tsx
    │       └── JobDetail.tsx
    └── backend/                  # FastAPI
        ├── main.py
        ├── config.py
        ├── schema.sql
        └── requirements.txt
```

---

## 5. 面试表达参考

> 整套系统分两层：本地私有层负责低频采集、数据清洗、企业风险增强和 AI 五维评分，所有敏感数据（Cookie、API Key、原始 HTML）不离开本机；云端展示层通过同步脚本把脱敏后的评分结果发布到 ECS MySQL，前端基于 React + TypeScript + Tailwind CSS 构建，后端用 FastAPI 提供 RESTful 查询 API。两端完全解耦，既保证本地爬虫安全性，也能在面试中稳定演示完整的数据分析能力。

---

## 6. 验收结论

ECS 展示项目的开发阶段已全部完成：
- 前端 3 个页面 + 职位详情弹窗
- 后端 4 个 GET API + Swagger 文档
- SQLite → MySQL 同步脚本（全量 / 增量 / dry-run）
- 建表 SQL + 环境变量配置模板

剩余工作为 ECS 基础环境搭建和部署，属于运维操作，不涉及代码开发。
