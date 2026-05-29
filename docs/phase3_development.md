# 第三阶段开发文档

## 目标

第三阶段聚焦“AI 评分接入”，基于第二阶段产出的 `jobs_cleaned.ai_input_json` 调用模型评分，并将评分结果落库到独立表。

这一阶段的目标是：

- 建立可审计的评分规则提示词
- 将清洗后的职位数据批量发送给 AI
- 对 AI 返回结果做结构校验
- 将评分结果写入 `scores`
- 保持抓取、清洗、评分三阶段解耦

## 当前范围

已包含：

- 新增 `ai/prompts.py`
- 新增 `ai/parser.py`
- 新增 `ai/scorer.py`
- 新增评分入口 `score_jobs.py`
- 在数据库中新增 `scores` 表
- 增加 `--dry-run` 模式，用于检查 AI 入参与 prompt

未包含：

- 公司外部可信度增强
- 多模型 fallback
- 报告生成
- 自动调度

## 设计原则

- 不直接让模型自由发挥评分标准
- 先给定明确 rubric，再要求模型输出 JSON
- 原始抓取数据、清洗数据、评分结果分表保存
- 模型返回结果必须经过本地校验后再落库

## 模块职责

### `ai/prompts.py`

负责：

- 定义 `SYSTEM_PROMPT`
- 定义评分 rubric
- 生成用户 prompt
- 管理 `PROMPT_VERSION`

当前评分维度：

- `score_activity`
- `score_jd`
- `score_company`
- `score_salary`
- `score_other`

### `ai/parser.py`

负责：

- 解析模型 JSON 返回
- 校验字段是否齐全
- 校验分数范围
- 校验 `total` 是否等于各维度和
- 校验 `verdict` 是否合法

### `ai/scorer.py`

负责：

- 使用 OpenAI-compatible SDK 调用 DeepSeek
- 传入 prompt 和职位 JSON
- 解析并校验模型返回
- 为结果补充：
  - `model_name`
  - `prompt_version`
  - `score_source`
  - `scored_at`

### `score_jobs.py`

负责：

- 作为第三阶段命令行入口
- 从 `jobs_cleaned` 读取待评分数据
- 调用 `JobScorer`
- 将结果写入 `scores`
- 支持 `--dry-run`

示例：

```powershell
.\.venv\Scripts\python.exe .\score_jobs.py --dry-run --limit 1
.\.venv\Scripts\python.exe .\score_jobs.py --limit 5
```

## 当前评分逻辑

当前 prompt 不再只给原则，而是显式给出评分区间：

- `score_activity (0-30)`
- `score_jd (0-25)`
- `score_company (0-20)`
- `score_salary (0-15)`
- `score_other (0-10)`

同时给出 `verdict` 参考区间：

- `total >= 70` -> `apply`
- `50-69` -> `apply_with_caution`
- `<50` -> `skip`

## 数据库设计

### `scores`

主键：`job_id`

关键字段：

- `score_activity`
- `score_jd`
- `score_company`
- `score_salary`
- `score_other`
- `total`
- `verdict`
- `red_flags_json`
- `reasoning`
- `score_source`
- `model_name`
- `prompt_version`
- `score_status`
- `raw_response_json`
- `scored_at`

说明：

- `scores` 独立保存 AI 结果
- `jobs.ai_scored` 在评分成功后同步更新为 `1`

## 当前未完成项

- 公司可信度外部增强查询
- `company_enriched` 表
- 评分失败重试策略
- 自动批处理调度
- 第三阶段和第四阶段报告输出衔接
