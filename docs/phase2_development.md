# 第二阶段开发文档

## 目标

第二阶段聚焦“数据清洗与 AI 入参准备”，不改动现有抓取链路。

这一阶段的目标是：

- 基于 `jobs.raw_html` / `jobs.raw_json` 做离线清洗
- 将清洗结果写入独立表，避免影响正在运行的爬虫
- 尽可能补齐 AI 评分所需字段
- 为后续 `scores` 表和 AI API 调用准备统一输入结构

## 当前范围

已包含：

- 新增独立清洗入口 `clean_jobs.py`
- 新增清洗模块 `cleaning/job_cleaner.py`
- 在 `jobs.db` 中新增 `jobs_cleaned` 表
- 从详情页 HTML 回填薪资字段
- 从详情页 HTML 补提取城市、经验、学历、更新时间
- 从公司信息区域补提取公司名、公司规模
- 生成可直接传给 AI 的 `ai_input_json`
- 生成 `quality_flags_json` 标记缺失项
- 已移除不稳定且长期为空的 `benefits` 字段

未包含：

- AI 评分调用
- `scores` 表
- PDF 报告
- 大规模清洗规则库和枚举标准化体系

## 设计原则

第二阶段明确遵守以下边界：

- 不改 `main.py` 的抓取入口
- 不改 `list` / `detail` 的运行方式
- 不回写 `jobs` 原始抓取表
- 所有清洗结果写入新表 `jobs_cleaned`

这样做的原因是：

- 抓取和清洗职责分离
- 便于在爬虫运行期间单独重复执行清洗
- 保留原始抓取结果，方便回溯误判和补规则

## 模块职责

### `clean_jobs.py`

负责：

- 作为第二阶段的命令行入口
- 读取参数：
  - `--keyword`
  - `--limit`
  - `--only-missing`
- 调用清洗流程并输出统计结果

示例：

```powershell
.\.venv\Scripts\python.exe .\clean_jobs.py --limit 20
.\.venv\Scripts\python.exe .\clean_jobs.py --only-missing
```

### `cleaning/job_cleaner.py`

负责：

- 创建 `jobs_cleaned` 表
- 从 `jobs` 表读取已有详情页数据
- 基于 `raw_html` 和 `raw_json` 做字段补齐
- 生成 AI 入参 JSON
- 生成质量标记
- 将结果写入 `jobs_cleaned`

## 当前清洗内容

### 1. 薪资清洗

当前已实现：

- 从详情页 HTML 的 `span.salary` 提取原始薪资文本
- 保存 `salary_text_raw`
- 解析：
  - `10-14k`
  - `9-12k·14薪`
  - `15-20k·13薪`
  - `400-500k`

当前输出字段：

- `salary_text_raw`
- `salary_min`
- `salary_max`
- `salary_months`
- `salary_period`

说明：

- 第一阶段主要依赖 `ld+json.baseSalary`
- 实际页面里很多职位的 `baseSalary` 只有结构，没有具体数值
- 因此第二阶段增加了 HTML 薪资回退提取

### 2. 基础属性清洗

当前已从 `.job-properties` 区域补提取：

- `city`
- `exp_years`
- `education`
- `last_updated`

说明：

- 当 `jobs` 表中的这些字段为空或不完整时，优先用 HTML 补齐
- `last_updated` 支持从“`5月28日更新`”这类文本转成 `YYYY-MM-DD`

### 3. 公司信息清洗

当前已从公司信息区域补提取：

- `company_name`
- `company_size`

说明：

- 公司名优先从 logo 的 `img[alt]` 提取
- 公司规模目前按页面文本正则提取，如：
  - `50-99人`
  - `100-499人`
  - `5000-10000人`
  - `10000人以上`

### 4. JD 文本补齐

当前已实现：

- 当 `jobs.jd_text` 缺失时，尝试从详情页正文区域补提取
- 重新计算 `jd_length`

当前会尝试的区域包括：

- `.job-intro-content`
- `.desc-box`
- `.content-word`
- `.job-description`

## AI 入参准备

根据 `Developer_Spec_EN_Codex`，当前 `jobs_cleaned` 已保存一份可直接发给 AI 的 `ai_input_json`。

当前结构覆盖：

- `job_id`
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
- `company_size`
- `company_verified`
- `company_logo_exists`
- `publisher_type`
- `jd_text`
- `jd_length`

说明：

- 原本预留过 `benefits` / `benefits_json`
- 但在当前猎聘样本中，该字段既不稳定也几乎无法从 HTML 可靠提取
- 因此第二阶段已将其从清洗结果、AI 入参和质量标记中移除

## 质量标记

当前新增 `quality_flags_json`，用于标记仍然缺失或质量不足的字段。

目前会打的标记包括：

- `missing_salary`
- `missing_salary_months`
- `missing_company_size`
- `short_jd`
- `missing_last_updated`

这些标记后续可用于：

- 过滤低质量职位
- 单独回看异常样本
- 给 AI 打分时附加上下文

## 数据库设计

### `jobs_cleaned`

主键：`job_id`

关键字段：

- `keyword`
- `detail_url`
- `title`
- `salary_text_raw`
- `salary_min`
- `salary_max`
- `salary_months`
- `salary_period`
- `city`
- `exp_years`
- `education`
- `date_posted`
- `last_updated`
- `days_since_update`
- `company_name`
- `company_size`
- `company_verified`
- `company_logo_exists`
- `publisher_type`
- `jd_text`
- `jd_length`
- `ai_input_json`
- `quality_flags_json`
- `source_updated_at`
- `cleaned_at`

## 当前状态

截至目前，第二阶段已经落地：

- 清洗入口已独立出来
- 清洗结果已与原始抓取表隔离
- 已能补齐一批职位的薪资字段
- 已能补齐城市、经验、学历、更新时间、公司规模等字段
- 已能为后续 AI 评分生成标准化输入 JSON

## 当前未完成项

下一步仍需补充：

- 公司规模、学历、经验的统一枚举标准化
- 标题清洗规则增强
- 对异常页、噪声页、低质量页建立更明确的判定规则
- 新增 `scores` 表并接 AI 评分模块
- 在整条抓取 -> 清洗 -> AI -> 报告链路打通后，新增按数量阈值触发清洗的调度逻辑

## 后续调度计划

当前 `clean_jobs.py` 仍是手动触发。

后续整条链路打通后，需要新增自动调度规则：

- 抓取作为独立生产阶段持续写入原始 `jobs`
- 当待清洗职位累计达到 `50` 条时，自动触发一次清洗任务
- 清洗结果写入 `jobs_cleaned`
- 后续再由 AI 评分阶段消费 `jobs_cleaned`

这条规则的目的：

- 避免每抓到 1 条就立刻清洗，增加调度开销
- 避免积压过多原始数据后再一次性清洗
- 为后续 AI 批处理提供较稳定的输入规模

当前阶段先记录需求，不在本阶段实现自动触发逻辑

## 与第一阶段的衔接

第一阶段保留：

- 原始 `jobs`
- 原始 `crawl_log`
- 原始 `debug/` 失败现场

第二阶段在此基础上新增：

- `jobs_cleaned`
- 离线清洗逻辑
- AI 入参准备逻辑

这意味着：

- 第一阶段负责“尽量抓到真实页面”
- 第二阶段负责“尽量把真实页面整理成可评分数据”
