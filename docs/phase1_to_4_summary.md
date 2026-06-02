# Phase1-4 阶段总结

## 总览

当前主链路已经形成四段式结构：

1. Phase1 抓取 -> `jobs`
2. Phase2 清洗 -> `jobs_cleaned`
3. Phase4 企业增强 -> `company_enriched`
4. Phase3 AI 评分 -> `scores`

其中第四阶段在执行顺序上位于第二阶段之后、第三阶段之前；`phase4_2` 属于第四阶段的联调总结，不是独立主阶段。

---

## Phase1 抓取阶段

### 目标

完成职位列表抓取、详情页解析、原始数据落库，并尽量降低风控干扰。

### 已实现内容

- 使用 Playwright 抓取猎聘 PC 搜索页和详情页
- 列表页从真实职位卡片提取 `job_id` 和真实 `detail_url`
- 详情页直接访问真实链接，不再依赖点击搜索结果进入
- 解析详情页 `ld+json` 中的 `JobPosting`
- 对多行文本、非法反斜杠等非标准 JSON 做容错解析
- 数据写入 SQLite，已落 `jobs`、`crawl_log`
- 保存失败现场到 `debug/`
- 已接入 Cookie、基础反检测、延时和批内冷却

### 当前结论

- 搜索 URL 必须尽量贴近真实手动访问参数，简化版 URL 结果质量差
- 列表卡片里的真实 `href` 比早期猜测的 `/a/{job_id}.shtml` 更可靠
- 详情页能稳定抓到一批真实职位，但风控阈值仍需要持续人工测试

### 当前输出

- 原始职位表：`jobs`
- 抓取日志：`crawl_log`
- 调试现场：`debug/`

---

## Phase2 清洗阶段

### 目标

基于 Phase1 的原始 HTML/JSON 做离线清洗，补齐字段，并生成统一的 AI 入参。

### 已实现内容

- 新增独立入口 `clean_jobs.py`
- 新增清洗模块 `cleaning/job_cleaner.py`
- 新增清洗结果表 `jobs_cleaned`
- 从 HTML 回填薪资、城市、经验、学历、更新时间
- 从公司信息区域补提取公司名、公司规模
- 当 `jd_text` 缺失时，从正文区域补提取并重算 `jd_length`
- 生成 `ai_input_json`
- 生成 `quality_flags_json`
- 移除了长期不稳定且几乎为空的 `benefits` 相关字段

### 当前结论

- 抓取与清洗已经解耦，清洗可以重复跑，不影响原始抓取表
- `ld+json.baseSalary` 不足以覆盖实际薪资，HTML 回退提取是必要的
- 当前已经具备给 AI 评分使用的标准化输入结构

### 当前输出

- 清洗结果表：`jobs_cleaned`
- 关键补充字段：
  - `salary_text_raw`
  - `salary_min` / `salary_max` / `salary_months`
  - `company_size`
  - `ai_input_json`
  - `quality_flags_json`

### 当前未完成

- 公司规模、学历、经验等枚举标准化
- 标题清洗规则增强
- 更明确的低质量样本判定规则

---

## Phase3 AI 评分阶段

### 目标

基于 `jobs_cleaned.ai_input_json` 调用模型评分，并将结果结构化落库。

### 已实现内容

- 新增 `ai/prompts.py`
- 新增 `ai/parser.py`
- 新增 `ai/scorer.py`
- 新增评分入口 `score_jobs.py`
- 新增评分结果表 `scores`
- 已支持 `--dry-run` 检查 prompt 和 AI 入参
- 评分结果在入库前已做本地结构校验

### 当前评分结构

- `score_activity`
- `score_jd`
- `score_company`
- `score_salary`
- `score_other`
- `total`
- `verdict`

### 当前结论

- 评分阶段已经独立成型，和抓取、清洗分离
- prompt 已从“泛规则”收敛到“明确 rubric + JSON 输出”
- 本地校验可以拦截分数范围、字段缺失、`total` 不一致等问题

### 当前输出

- 评分结果表：`scores`
- 关键字段：
  - `total`
  - `verdict`
  - `red_flags_json`
  - `reasoning`
  - `raw_response_json`

### 当前未完成

- 评分失败重试
- 自动批处理调度
- 与企业增强结果的稳定联动

---

## Phase4 企业增强阶段

### 目标

在评分前增加一层“公司是否值得深查”的判定，并为公司级风险证据提供独立缓存。

### 已实现内容

- 在 `jobs_cleaned` 中新增企业检查相关字段
- 新增公司级缓存表 `company_enriched`
- 在 `cleaning/job_cleaner.py` 中加入 `need_company_check` 判定逻辑
- 已加入 `hr_currently_online` 提取
- JD 风险词已从单一列表改为强 / 中 / 弱三级
- 已新增独立入口 `company_enrich.py`
- 已新增知乎搜索客户端 `crawler/zhihu_client.py`
- 已打通“知乎搜索摘要抓取 -> 入库 -> 状态回写”的第一版链路

### 当前判定逻辑

命中以下信号时，会把职位标记为需要企业深查：

- `company_size_small_or_unknown`
- `salary_abnormal_for_small_company`
- `jd_risk_score_gte_3`
- `job_posted_over_30d_and_hr_online`
- `weak_company_identity`

### Phase4_2 联调结论

- 知乎搜索接口在低频、小批量条件下可用
- 第一版企业增强可先只依赖标题和摘要，不必做正文全文抓取
- “阅读全文”方案已明确放弃，当前性价比不高
- 当前更值得投入的是：
  - 证据截断收敛
  - 关键词主题化
  - 语义匹配补漏

### 当前输出

- `jobs_cleaned` 中的企业检查字段：
  - `company_name_norm`
  - `need_company_check`
  - `company_check_status`
  - `company_check_reasons_json`
  - `hr_currently_online`
- `company_enriched` 中的公司级缓存与证据字段

### 当前未完成

- 更稳定的搜索结果清洗与去重
- 更短、更干净的证据片段输出
- 企业增强结果和评分链路的正式接入
- 基于摘要证据的语义匹配增强

---

## 当前阶段性进度判断

截至目前，Phase1 到 Phase4 的核心建设已经完成，系统已不再是单点脚本，而是分阶段链路：

- 抓取能稳定落原始数据
- 清洗能补齐关键字段并生成 AI 入参
- 评分能独立执行并结构化落库
- 企业增强已跑通第一版知乎摘要链路

当前最重要的工作重点已经从“加新功能”切换为：

- 提高阶段间联调稳定性
- 收敛失败分类和状态模型
- 优化企业增强证据质量
- 把后处理链路跑稳

---

## 建议的后续推进顺序

1. 继续稳定跑 `clean_jobs.py -> company_enrich.py -> score_jobs.py`
2. 收敛企业增强证据输出，优先压缩成短证据片段
3. 补齐抓取与后处理状态分类，方便批量联调
4. 再决定是否把企业增强结果正式并入评分 prompt
