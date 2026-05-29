# 第四阶段开发文档

## 目标

第四阶段聚焦“公司可靠性增强接入”。

这一阶段放在第二阶段清洗之后、第三阶段 AI 评分之前，目标不是重做评分系统，而是在已有 `jobs_cleaned` 基础上补一层“是否需要企业深查”的判定和公司级增强结果缓存，为后续知乎抓取与评分输入扩展做准备。

当前阶段的核心目标：

- 在清洗阶段产出稳定的公司检查判定结果
- 将“要不要查”与“查到了什么”拆开
- 为后续知乎抓取保留独立异步入口
- 保持抓取、清洗、企业增强、评分四段解耦

## 当前范围

当前已落地：

- `jobs_cleaned` 新增企业检查相关字段
- 新增公司级缓存表 `company_enriched`
- 在 `cleaning/job_cleaner.py` 中加入“是否需要企业深查”的判定逻辑
- 已加入 `hr_currently_online` 提取
- 已将 JD 风险词从单一列表改为强 / 中 / 弱三级
- 清洗阶段已可输出：
  - `company_name_norm`
  - `need_company_check`
  - `company_check_status`
  - `company_check_reasons_json`
  - `hr_currently_online`

当前尚未落地：

- 知乎搜索请求实现
- 搜索结果清洗与去重
- 正文抓取与负面句提取
- `score_jobs.py` 拼接企业增强结果
- `ai/prompts.py` 根据企业增强结果调整 `score_company`

## 设计原则

- 企业可靠性验证不进入第一阶段抓取流程
- 企业可靠性验证不阻塞第二阶段清洗主流程
- 企业可靠性验证不直接绑死在第三阶段评分主循环里
- 职位级“是否需要查”和公司级“查到了什么”拆开存
- 优先减少重复查询，同一家公司多个职位复用同一份增强结果
- 企业增强失败时允许降级，不阻塞评分主流程

## 当前主链路

当前确认的整体链路为：

1. 第一阶段抓取 -> `jobs`
2. 第二阶段清洗 -> `jobs_cleaned`
3. 第四阶段企业增强 -> `company_enriched`
4. 第三阶段评分 -> `scores`

也就是说，第四阶段不是嵌到第一阶段和第二阶段内部同步执行，而是作为独立阶段存在。

## 数据结构

### `jobs_cleaned`

在原有清洗字段之外，当前已新增：

- `company_name_norm`
- `need_company_check`
- `company_check_status`
- `company_check_reasons_json`
- `hr_currently_online`

字段含义：

- `company_name_norm`
  - 公司名标准化结果，用于公司级去重和缓存命中
- `need_company_check`
  - 是否需要进入企业深查
  - `0` 表示不需要
  - `1` 表示需要
- `company_check_status`
  - 当前状态：
    - `skip`
    - `pending`
    - 后续预留 `done` / `failed`
- `company_check_reasons_json`
  - 命中的判定原因列表
- `hr_currently_online`
  - 是否命中职位页中的“当前在线”状态
  - `0` 表示未命中
  - `1` 表示命中

### `company_enriched`

当前已新增公司级缓存表：

- `company_name_norm`
- `company_name_raw`
- `status`
- `source`
- `query`
- `search_results_json`
- `negative_sentences_json`
- `risk_level`
- `risk_reasons_json`
- `last_checked_at`
- `expire_at`
- `created_at`
- `updated_at`

这张表当前主要用于为后续知乎抓取结果提供承载结构和缓存位置。

## 当前判定逻辑

当前清洗阶段已接入“是否需要企业深查”的第一版规则。

设计方式：

- 基于 `jobs_cleaned` 的结构化字段做离线判定
- 在规则累计前，若公司名包含 `某`，则直接跳过企业深查规则
- 当前联调阶段命中 1 条及以上，标记 `need_company_check = 1`
- 若需要查，则 `company_check_status = "pending"`
- 若不需要查，则 `company_check_status = "skip"`

### 当前已实现规则

当前第一版已实现以下规则：

- `company_size_small_or_unknown`
  - 公司规模较小（当前放宽到 `<= 100` 人），或公司规模缺失
- `salary_abnormal_for_small_company`
  - 小公司或未知规模公司，但薪资明显偏高
- `jd_risk_score_gte_3`
  - JD 风险词按强 / 中 / 弱三级计分，当前总分阈值为 `3`
- `job_posted_over_30d_and_hr_online`
  - `date_posted` 超过 30 天，且 `hr_currently_online = 1`
- `weak_company_identity`
  - 公司身份信号弱，例如：
    - 未认证
    - 无 logo
    - `publisher_type` 弱或未知

### JD 风险词当前分层

当前已确认：

- 强风险词：单个权重 `3`
- 中风险词：单个权重 `2`
- 弱风险词：单个权重 `1`
- 当前触发阈值：总分 `>= 3`

这意味着：

- 单个强风险词即可触发
- 2 个中风险词可触发
- 3 个弱风险词可触发
- 强中弱可混合累计

### 当前暂未实现规则

以下规则仍在规划中，尚未接入代码：

- `company_age_short`
- 更可靠的平台异常信号识别
- 更细的公司规模标准化
- 更细的薪资异常判定

### 当前明确不做

以下内容已经讨论过，当前版本不纳入实现：

- 为了补“公司成立时间”而新增公司详情页二次抓取
- 用 `last_updated` 做清洗阶段硬过滤
- 用 `last_updated > 7天` 直接拒绝评分

当前对时间字段的边界是：

- `date_posted`
  - 可用于职位级风险规则
  - 当前已用于 `job_posted_over_30d_and_hr_online`
- `last_updated`
  - 先保留给后续 prompt 打分使用
  - 当前不做硬筛

## 模块职责

### `clean_jobs.py` / `cleaning/job_cleaner.py`

当前职责已经扩展为：

- 继续完成职位清洗
- 计算公司名标准化结果
- 输出是否需要企业深查
- 输出触发原因
- 输出职位级辅助信号，例如：
  - `hr_currently_online`
  - JD 风险词分层计分结果（当前已在规则层使用）

当前不负责：

- 真实知乎请求
- 搜索摘要抓取
- 正文抓取

### 后续 `company_enrich.py`

下一步计划新增独立入口，例如：

- `company_enrich.py`

其职责将是：

- 从 `jobs_cleaned` 中筛出：
  - `need_company_check = 1`
  - `company_check_status = 'pending'`
- 按 `company_name_norm` 去重
- 查询 `company_enriched` 是否已有缓存
- 对未缓存公司发起知乎抓取
- 将抓取结果写入 `company_enriched`
- 后续再回写状态或供评分阶段读取

## 为什么采用独立异步阶段

企业可靠性增强最终会走知乎抓取，而这部分和第一阶段一样，具有以下特点：

- 外部依赖强
- 频率敏感
- Cookie 会过期
- 失败不可控
- 单条耗时明显高于本地清洗

因此当前已明确：

- 不把知乎抓取塞进 `clean_jobs.py` 主循环同步执行
- 不把知乎抓取塞进 `score_jobs.py` 每条职位实时执行
- 企业增强作为独立异步阶段更稳

## 与评分阶段的边界

当前阶段还没有改 prompt，也没有改评分入参。

当前明确的边界是：

- 第四阶段先只完成数据结构和触发判定
- 评分阶段暂时保持原样
- 等知乎抓取结果结构稳定后，再扩展：
  - `score_jobs.py`
  - `ai/prompts.py`

这样可以减少返工。

## 职位级与公司级边界

当前已明确：

- 职位级信号继续放在 `jobs_cleaned`
- 公司级增强结果放在 `company_enriched`

当前不把以下信号塞进 `company_enriched`：

- JD 风险词命中
- `date_posted`
- `hr_currently_online`
- 职位级触发原因

原因是这些都属于职位维度，而不是公司维度。

后续如果需要提升可读性，优先采用方案 A：

- 继续留在 `jobs_cleaned`
- 将部分职位级中间结果拆成显式字段
- 而不是把规则结果混进公司表

## 当前状态

截至目前，第四阶段已经完成：

- 流程位置确认
- 数据结构确认
- 规则入口确认
- 数据库字段落地
- 第一版判定逻辑落地

当前阶段尚未完成：

- 知乎正文抓取实现
- 企业增强结果与评分链路对接

补充说明：

- `phase4_2` 已完成搜索摘要抓取联调，总结见 `docs/phase4_2_summary.md`
- 当前结论是：先基于搜索结果标题/摘要做企业增强，放弃“阅读全文”，后续主方向改为语义匹配增强

## 下一步

下一步将开始尝试知乎抓取，顺序预计为：

1. 已实现独立入口 `company_enrich.py`
2. 当前先处理 `need_company_check = 1` 且 `company_check_status = 'pending'` 的公司
3. 第一版先做知乎搜索摘要抓取并写入 `company_enriched`
4. 继续验证成功率、Cookie、频率控制和缓存策略
5. 再决定是否进入正文抓取与负面句提取

当前阶段先以“搜索摘要可稳定拿到”为第一目标，不急着改评分 prompt。
