# 第一阶段开发文档

## 目标

第一阶段只实现“职位数据抓取与落库”，不包含 AI 评分与 PDF 生成。

系统需要从 `liepin.com` 按固定搜索配置抓取职位列表，进入职位详情页提取结构化数据，并保存到 SQLite，支持失败日志与中断后续跑。

## 范围

已包含：

- 使用 Playwright 渲染猎聘 React SPA 列表页
- 按关键词和分页抓取职位 `job_id`
- 进入详情页并解析 `ld+json`
- 补充提取 `last_updated`
- 在抓取时计算 `days_since_update`
- 保存职位数据到 `jobs` 表
- 保存请求日志到 `crawl_log` 表
- 注入 `cookies.json`
- 基础反检测策略

未包含：

- DeepSeek 评分
- `scores` 表
- PDF 报告

## 搜索配置

- 城市：上海 `010200`
- 关键词：`%E5%85%A8%E6%A0%88`、`python`、`c%23`、`java`
- 每个关键词页数：`5`
- 请求间隔：`random.uniform(4, 9)`

## 模块设计

### `config.py`

维护搜索配置、浏览器配置和路径配置。

### `crawler/browser.py`

负责：

- 启动 Playwright Chromium
- 创建 Browser Context
- 注入 User-Agent
- 加载 `cookies.json`

### `crawler/anti_detect.py`

负责：

- 随机等待
- 模拟鼠标移动
- 模拟页面滚动
- User-Agent 兜底

### `crawler/list_page.py`

负责：

- 生成搜索 URL
- 打开列表页
- 等待 `networkidle`
- 提取 `/a/{job_id}` 链接
- 去重后返回 `job_id`

### `crawler/detail_page.py`

负责：

- 打开详情页
- 解析 `script[type="application/ld+json"]`
- 兼容单个 dict、数组和 `@graph`
- 抽取职位核心字段
- 从 `.time-factor-wrap` 补充 `last_updated`
- 计算 `days_since_update`

### `storage/database.py`

负责：

- 初始化 SQLite
- 开启 `WAL`
- 创建 `jobs`、`crawl_log`
- 按 `job_id` 做 upsert
- 记录抓取日志
- 重复运行时跳过已入库职位详情

### `main.py`

负责：

- 初始化数据库
- 遍历关键词与页码
- 抓列表页
- 抓详情页
- 记录成功和失败

## 数据库设计

### `jobs`

主键：`job_id`

关键字段：

- `keyword`
- `detail_url`
- `title`
- `salary_min`
- `salary_max`
- `salary_months`
- `city`
- `exp_years`
- `education`
- `date_posted`
- `last_updated`
- `days_since_update`
- `company_name`
- `company_verified`
- `company_logo_exists`
- `publisher_type`
- `jd_text`
- `jd_length`
- `benefits_json`
- `raw_html`
- `raw_json`

### `crawl_log`

记录每次请求：

- `url`
- `keyword`
- `page_no`
- `job_id`
- `status_code`
- `latency_seconds`
- `retry_count`
- `success`
- `error_message`

## 运行前准备

1. 安装依赖
2. 执行 `playwright install chromium`
3. 手工登录猎聘并导出 `cookies.json`

如果浏览器里只能复制整段 Cookie 字符串，也可以直接转换：

```bash
.venv\Scripts\python.exe tools\convert_cookie_string.py "name1=value1; name2=value2"
```

默认会在项目根目录生成 `cookies.json`。

## 第一阶段验收标准

- 能完整遍历 4 个关键词，每个关键词 5 页
- 列表页能提取并去重职位 `job_id`
- 详情页能解析出结构化职位数据
- `jobs` 表按 `job_id` 去重保存
- `crawl_log` 能记录成功和失败
- `days_since_update` 在抓取阶段生成

## 当前入口

先抓列表页：

```bash
python main.py list --keyword python --page 0 --pages 1 --interactive
```

再抓少量详情页：

```bash
python main.py detail --keyword python --max-detail 3 --interactive --confirm-every 1
```

程序结束后应看到：

- 工作目录生成 `jobs.db`
- `list` 模式把发现的 `job_id` 写入 `jobs`
- `detail` 模式补全职位详情并写入 `crawl_log`
