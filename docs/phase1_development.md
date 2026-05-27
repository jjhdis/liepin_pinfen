# 第一阶段开发文档

## 目标

第一阶段只实现“职位数据抓取与落库”，不包含 AI 评分和 PDF 生成。

系统从 `liepin.com` 抓取职位列表，再进入职位详情页提取结构化数据并保存到 SQLite。当前阶段的目标是：

- 稳定抓取列表页真实职位卡片
- 存储真实详情链接和 `job_id`
- 抓取详情页并解析 `JobPosting`
- 保留原始 HTML，方便后续调试和数据清洗
- 在较低频率下尽量规避风控

## 当前范围

已包含：

- Playwright 打开猎聘 PC 搜索页和详情页
- 使用真实列表卡片链接作为 `detail_url`
- 搜索页预热后直跳详情页
- 解析 `application/ld+json` 中的 `JobPosting`
- 对多行文本、非法反斜杠等非标准 JSON 做容错解析
- 保存 `jobs` / `crawl_log`
- 保存失败现场 HTML 到 `debug/`
- cookies 注入
- 基础反检测、延时和批内冷却

未包含：

- AI 评分
- 数据清洗规则库
- PDF 报告

## 搜索配置

搜索配置定义在 [config.py](/abs/path/D:/channel/PythonProject2/config.py:6) 的 `SEARCH_CONFIG`。

当前关键参数：

- `city_code = "020"`
- `dq_code = "020"`
- `page_size = 40`
- `keywords = ["%E5%85%A8%E6%A0%88", "python", "c%23", "java"]`
- `sfrom = "search_job_pc"`
- `scene = "input"`

当前 `list` 使用的搜索 URL 结构为：

```text
https://www.liepin.com/zhaopin/?city=020&dq=020&pubTime=&currentPage=0&pageSize=40&key=python&suggestTag=&workYearCode=0&compId=&compName=&compTag=&industry=&salaryCode=&jobKind=&compScale=&compKind=&compStage=&eduLevel=&otherCity=&sfrom=search_job_pc&scene=input
```

这套结构是对照手动访问页面收敛出来的，不再使用早期的简化 `pageNo` 版本。

## 运行参数配置

运行默认参数定义在 [config.py](/abs/path/D:/channel/PythonProject2/config.py:29) 的 `RUN_CONFIG`。

命令行未显式传参时，会使用这里的默认值。命令行传参时，会覆盖这些值。

当前默认值：

```python
RUN_CONFIG = {
    "list": {
        "page": 0,
        "pages": 1,
        "min_delay": 60.0,
        "max_delay": 120.0,
        "interactive": False,
    },
    "detail": {
        "max_detail": 10,
        "min_delay": 45.0,
        "max_delay": 90.0,
        "interactive": False,
        "confirm_every": 1,
        "cooldown_every": 10,
        "cooldown_min": 60.0,
        "cooldown_max": 120.0,
    },
}
```

目前这些参数主要用于测试风控阈值，后续可继续微调。

## 模块职责

### `config.py`

负责：

- 搜索参数
- 运行默认参数
- 浏览器配置
- 文件路径配置

### `crawler/browser.py`

负责：

- 启动 Chromium
- 创建 Browser Context
- 设置 User-Agent、时区、语言
- 注入 `cookies.json`
- 注入基础 stealth 脚本

### `crawler/anti_detect.py`

负责：

- 随机等待
- 鼠标移动
- 页面滚动
- 页面停留模拟

### `crawler/list_page.py`

负责：

- 构造接近手动访问的搜索 URL
- 打开搜索页并等待页面稳定
- 从真实职位卡片 `a[data-nick="job-detail-job-info"]` 提取：
  - `job_id`
  - 真实 `detail_url`
- 提取失败时保存列表页 HTML 到 `debug/`

说明：

- 当前 `list` 已不再依赖简单的 `/a/{job_id}` 链接扫描作为主逻辑
- 当前 `detail_url` 优先直接使用列表卡片里的 `href`

### `crawler/detail_page.py`

负责：

- 访问 `jobs.detail_url`
- 解析详情页 `ld+json`
- 优先提取 `JobPosting`
- 对换行、非法反斜杠等非标准 JSON 做容错处理
- 补充提取 `last_updated`
- 计算 `days_since_update`
- 对错页、风控页、解析失败页保存调试 HTML

说明：

- 当前代码已经确认：有些页面虽然是正常职位详情页，但 `ld+json` 不是严格合法 JSON，因此需要容错解析
- 当前会校验最终落地页路径是否仍与目标详情路径一致

### `storage/database.py`

负责：

- 初始化 SQLite
- 开启 `WAL`
- 创建 `jobs`、`crawl_log`
- 插入或更新职位记录
- 记录每次抓取日志

### `main.py`

负责：

- 初始化数据库
- 执行 `list` / `detail`
- 用 `RUN_CONFIG` 和命令行参数控制抓取
- `detail` 模式下控制延时与批内冷却

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
3. 手动登录猎聘并导出 `cookies.json`

如果浏览器里只能复制整段 Cookie 字符串，也可以转换：

```powershell
.\.venv\Scripts\python.exe .\tools\convert_cookie_string.py "name1=value1; name2=value2"
```

## 当前启动方式

### 1. 抓列表页

```powershell
.\.venv\Scripts\python.exe .\main.py list --keyword python
```

需要临时覆盖参数时：

```powershell
.\.venv\Scripts\python.exe .\main.py list --keyword python --page 0 --pages 2 --min-delay 30 --max-delay 60
```

### 2. 抓详情页

```powershell
.\.venv\Scripts\python.exe .\main.py detail --keyword python
```

需要临时覆盖参数时：

```powershell
.\.venv\Scripts\python.exe .\main.py detail --keyword python --max-detail 5 --min-delay 30 --max-delay 50 --cooldown-every 5 --cooldown-min 120 --cooldown-max 240
```

## 当前详情页抓取策略

当前 `detail` 流程：

1. 从 `jobs` 表读取 pending 职位
2. 先打开搜索页做预热
3. 等待页面稳定
4. 直接访问该职位在 `jobs.detail_url` 中保存的真实详情链接
5. 使用搜索页 URL 作为 `referer`
6. 进入详情页后做人类行为模拟
7. 解析 `JobPosting`
8. 写回数据库
9. 按 `min_delay` / `max_delay` 等待
10. 每处理 `cooldown_every` 条后执行较长冷却

说明：

- 当前已经不再点击搜索结果卡片进入详情
- 这样做是为了减少点击错页、落入搜索页或首页的概率
- 当前真实详情访问质量明显依赖列表卡片 `href` 的正确保存

## 当前已知结论

截至第一阶段结束，已经确认：

- 简化版搜索 URL 会导致列表结果质量差
- 真实列表卡片 `href` 与早期猜测的 `/a/{job_id}.shtml` 并不总是一致
- 一部分真实详情链接是 `/job/...shtml?...`
- 详情页 `ld+json` 中的 `JobPosting` 有时包含：
  - 原始换行
  - 非法反斜杠
- 这些都需要在解析层做容错

## 调试产物

`debug/` 目录会保存失败现场，例如：

- `detail_{keyword}_{job_id}_wrong_page.html`
- `detail_{keyword}_{job_id}_blocked.html`
- `detail_{keyword}_{job_id}_parse_failed.html`
- `list_{keyword}_{page}.html`

这些文件是第二阶段数据清洗和规则补充的重要输入。

## 第一阶段验收状态

目前第一阶段已经达到以下状态：

- `list` 已切换到更接近手动访问的搜索 URL
- `list` 已切换到从真实职位卡片提取 `job_id` 和真实 `detail_url`
- `detail` 已切换到访问真实 `detail_url`
- `detail` 已能稳定解析一批真实职位详情页
- `ld+json` 容错已覆盖多行文本和非法反斜杠场景
- 风控阈值仍在继续人工测试中

## 第二阶段入口

第二阶段计划进入“数据清洗”：

- 清洗标题、城市、薪资等字段
- 剔除低质量职位
- 标记异常页和噪声数据
- 对列表质量和详情质量建立更明确的判定规则
