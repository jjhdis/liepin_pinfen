# Phase7 规划 — 爬虫 API 封装

## 目标

将 CLI 操作封装为 API，前端页面通过接口调用爬虫，用户无需接触终端。

## 用户操作流程

```
1. Cookie 管理页 → 刷新/查看 cookie 列表 → 选择一个 cookie
2. 爬虫页 Step 1 → 选择 keyword（4 个固定选项）→ 点击"开始列表抓取"
   → POST /api/crawl/list {keyword, cookie_profile_name, store_top_n?}
3. 爬虫页 Step 2 → 选择 cookie → 点击"开始详情抓取"
   → POST /api/crawl/detail {cookie_profile_name}
```

## API 端点

基于现有 `dashboard_server.py` 扩展。

### POST /api/crawl/list

```json
{
    "keyword": "python",
    "cookie_profile_name": "15317685379",
    "store_top_n": 30
}
```

- `keyword`: 必填，当前固定 4 个值：全栈 / python / c# / java
- `cookie_profile_name`: 必填，前端从 cookie 管理页选取
- `store_top_n`: 可选，默认 config 值 30，最大 40

### POST /api/crawl/detail

```json
{
    "cookie_profile_name": "15317685379"
}
```

- `cookie_profile_name`: 必填
- `max_detail` 固定 25，不从 API 传参

### GET /api/crawl/keywords

```json
["全栈", "python", "c#", "java"]
```

### GET /api/crawl/status

```json
{
    "pending_detail": 45,
    "pending_cleaned": 30,
    "pending_score": 12,
    "last_list_run": "2026-06-05T10:30:00",
    "last_detail_run": "2026-06-05T10:35:00"
}
```

## 参数层级

| 参数 | config 默认值 | API 可覆盖 |
|------|-------------|-----------|
| keyword | — | ✅ 必传（list） |
| store_top_n | 30 | ✅ 可选，最大 40 |
| cookie_profile_name | — | ✅ 必传 |
| max_detail | 25 | ❌ 固定 |

## 改动清单

1. `dashboard_server.py` — 新增 4 个端点
2. `main.py` — 抽取 `run_list_mode()` / `run_detail_mode()` 为可编程调用函数
3. `cookie_manager.py` — 已可复用

## 备注

- list 和 detail 保持分离，不合并
- detail 不指定 keyword，爬所有 pending
- cookie 通过 `profile_name` 定位，对应 `cookie_profiles` 表
- `cookie_*_{profile_name}_{platform}.json` 匹配文件
