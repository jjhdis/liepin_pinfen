# Phase5 最小字段与 SQL 方案

## 目标

先完成最小可用的一组字段定义和查询 SQL，服务当前阶段的三件事：

1. 看抓取状态
2. 看待处理数量
3. 看最终结果

当前原则：

- 先不做大而全状态机
- 先不改成复杂前后端架构
- 先保证能查、能看、能定位问题

## 最小字段方案

### 1. `jobs`

当前最值得补齐的是详情抓取状态字段：

- `detail_status`
  - `pending`
  - `success`
  - `expired`
  - `wrong_page`
  - `login_required`
  - `blocked`
  - `parse_failed`
- `detail_error_message`
- `detail_last_attempt_at`

说明：

- 这三个字段只描述“详情抓取阶段发生了什么”
- 不和清洗、企业增强、评分混成一个总状态机

### 2. `jobs_cleaned`

当前已有字段已经基本够用，先不扩张大改。当前可直接利用：

- `clean_status`
- `score_status`
- `need_company_check`
- `company_check_status`
- `company_check_reasons_json`

### 3. `company_enriched`

当前核心够用：

- `status`
- `risk_level`
- `zhihu_filtered_results_json`
- `last_checked_at`

### 4. `scores`

当前核心够用：

- `total`
- `verdict`
- `score_status`
- `scored_at`

## 查询目标

当前先支持三类查询：

1. 失败分类统计
2. 待处理队列统计
3. 最终结果联表查看

## 设计边界

当前这份方案先做：

- 查询 SQL
- 字段定义文档

当前不急着做：

- 复杂 dashboard API
- 全局统一状态机
- 多阶段控制台
