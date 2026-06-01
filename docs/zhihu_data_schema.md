# Zhihu Data Schema

本文档定义第四阶段从知乎取回并写入 `company_enriched` 的固定数据格式。

目标：

- 保留可追溯的搜索结果摘要
- 输出适合后续评分 / 语义匹配消费的精简证据结构
- 不再依赖调试期的 `need_expand_fulltext`、整段 `excerpt`、`matched_snippet`

## 1. `company_enriched.search_results_json`

用途：

- 保存本次用于分析的标准化搜索结果摘要
- 作为回溯和人工核查输入
- 不直接作为最终风险证据

当前格式：

```json
[
  {
    "schema_version": "zhihu_search_result_v1",
    "rank": 1,
    "content_type": "answer",
    "content_id": "123456",
    "url": "https://www.zhihu.com/question/xxx/answer/yyy",
    "title": "上海某公司怎么样？",
    "excerpt": "有人提到拖欠工资、离职不给证明……"
  }
]
```

字段说明：

- `schema_version`
  - 当前固定为 `zhihu_search_result_v1`
- `rank`
  - 搜索结果顺序，从 `1` 开始
- `content_type`
  - 当前可能值：`answer` / `article` / `question`
- `content_id`
  - 知乎内容 id，统一存字符串
- `url`
  - 原始内容链接
- `title`
  - 标题，已做空白压缩与长度截断
- `excerpt`
  - 搜索摘要，已做空白压缩与长度截断

## 2. `company_enriched.negative_sentences_json`

用途：

- 保存真正进入后续企业风险判断的证据数组
- 当前阶段的核心输出

当前格式：

```json
[
  {
    "schema_version": "zhihu_company_evidence_v1",
    "evidence_id": "answer:123456:excerpt:拖欠工资",
    "content_type": "answer",
    "content_id": "123456",
    "url": "https://www.zhihu.com/question/xxx/answer/yyy",
    "title": "上海某公司怎么样？",
    "description": "拖欠工资，离职时还卡证明",
    "match_type": "negative",
    "matched_in": "excerpt",
    "matched_keyword": "拖欠工资",
    "reason": "excerpt_negative_match"
  }
]
```

字段说明：

- `schema_version`
  - 当前固定为 `zhihu_company_evidence_v1`
- `evidence_id`
  - 证据唯一标识，格式：
  - `{content_type}:{content_id}:{matched_in}:{matched_keyword}`
- `content_type`
  - 内容类型
- `content_id`
  - 内容 id，统一存字符串
- `url`
  - 原始内容链接
- `title`
  - 命中的搜索结果标题
- `description`
  - 精简后的局部证据文本
  - 只保留判断所需的短片段，不保留整段摘要
- `match_type`
  - 当前枚举：
  - `negative`
  - `neutral_trigger`
- `matched_in`
  - 命中位置：
  - `title`
  - `excerpt`
- `matched_keyword`
  - 实际命中的关键词
- `reason`
  - 当前规则原因：
  - `excerpt_negative_match`
  - `title_negative_match`
  - `title_neutral_trigger`

## 3. `risk_level` 与 `risk_reasons_json`

这两个字段当前不作为核心证据源，但会同步写入便于后续快速筛选。

### `risk_level`

当前规则：

- 无证据：`none`
- 仅中立触发词证据：`low`
- 存在负面关键词证据：`medium`

当前阶段不产出 `high`。

### `risk_reasons_json`

保存本次证据中去重后的 `reason` 列表，例如：

```json
[
  "excerpt_negative_match",
  "title_neutral_trigger"
]
```

## 4. 明确不再保留为核心格式的字段

以下字段属于调试期产物，不再作为稳定 schema 的一部分：

- `need_expand_fulltext`
- 原始整段 `excerpt` 进入证据对象
- `matched_snippet`

原因：

- 后续主方向已放弃“阅读全文”
- 评分 / 语义匹配更适合消费短证据而不是长摘要
- 证据对象应尽量稳定、紧凑、低噪声
