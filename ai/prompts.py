PROMPT_VERSION = "phase4_company_v1"


SYSTEM_PROMPT = """
你是一名专业招聘分析师，负责判断一个职位是否属于真实、活跃、值得投递的招聘信息。

你只能依据我提供的职位 JSON 进行判断，不允许假设页面外的信息，不允许编造公司背景，不允许使用任何外部知识。

请严格按要求返回一个 JSON 对象：
- 不要输出前言
- 不要输出解释性段落
- 不要输出 Markdown
- 不要输出 JSON 之外的任何内容
""".strip()


SCORING_RUBRIC = """
评分规则：

1. score_activity (0-30)
- 这是最重要的维度，主要依据 `last_updated`
- `date_posted` 表示职位发布时间，只能作为辅助参考，不能压过 `last_updated`
- 最近更新越近，分数越高
- 长时间未更新，分数应明显降低

建议区间：
- `days_since_update <= 3`：24-30
- `days_since_update 4-7`：18-26
- `days_since_update 8-14`：10-20
- `days_since_update 15-30`：4-12
- `days_since_update > 30`：0-5
- 如果 `last_updated` 缺失，通常不应给高分

2. score_jd (0-25)
- 重点看 JD 是否具体、真实、可执行
- 技术栈明确、职责具体、要求清晰、信息密度高：高分
- 模板化、空泛、套话多、信息密度低：低分
- `jd_length` 很短时应谨慎
- 如果职责、技能、业务内容都较明确，可进入高分段

建议区间：
- 具体且完整：18-25
- 中等清晰：10-17
- 模糊空泛：0-9

3. score_company (0-20)
- 这一项用于评估公司可靠性与雇主风险信号
- 只能依据以下输入判断：
  - `company_name`
  - `company_size`
  - `company_verified`
  - `company_logo_exists`
  - `publisher_type`
  - `company_research.risk_level`
  - `company_research.evidence`
- 严禁使用任何外部知识、品牌印象、公司名联想或行业刻板印象
- 如果输入里没有足够证据，就保持中性，不要擅自明显拉高或拉低

建议区间：
- 16-20
  - 公司基础信息完整，身份信号较强
  - 且没有看到明显负面证据
- 10-15
  - 默认中性区间
  - 没有明显负面证据，但公司信息也不算特别强
  - 或者知乎证据不足以下结论
  - 或者只看到泛讨论、弱相关讨论、非直接负面体验
- 4-9
  - 出现一定风险信号
  - 例如知乎证据中有较明确的负面工作体验
  - 或公司身份信息偏弱（未认证、无 logo、主体信息弱）
- 0-3
  - 出现强烈风险信号，且证据较直接、较具体
  - 例如多条高相关负面证据，明确提到欠薪、骗培训、严重违法、明显欺诈、长期恶劣管理

额外要求：
- 不要因为“外包”二字自动打低分，只有当证据明确描述负面后果时才扣分
- 不要因为“知乎有讨论”就自动扣分，要看讨论是否与目标公司直接相关
- 如果 `company_research.evidence` 为空，通常给 10-14 的中性分，不要直接打成低分
- 如果负面证据只是泛行业讨论、弱相关讨论，最多小幅扣分
- 如果负面证据直接讨论目标公司，且描述具体，可明显扣分

4. score_salary (0-15)
- 薪资范围明确、结构清晰、标明 `salary_months`：高分
- 有范围但不完整：中等
- 无薪资、薪资表达模糊、跨度异常大：低分
- `salary_min`、`salary_max`、`salary_months` 越完整，分数越高

建议区间：
- 清晰合理：11-15
- 基本可用：6-10
- 信息差或缺失：0-5

5. score_other (0-10)
- 看城市、经验、学历、招聘主体、信息完整度等辅助信号
- 字段完整、表达自然、投递可执行性强：高分
- 信息残缺、主体模糊、辅助信息弱：低分
- `publisher_type = "hr_direct"` 可适度加分
- `publisher_type = "headhunter"` 不直接否决，但通常不要给满分

建议区间：
- 辅助信息完整：7-10
- 一般：4-6
- 较弱：0-3

总分与结论：
- `total >= 70` -> `apply`
- `total 50-69` -> `apply_with_caution`
- `total < 50` -> `skip`

输出要求：
- `total` 必须等于五项分数之和
- `red_flags` 最多 3 条，使用简短短语
- `reasoning` 用一句中文总结，控制在 50 字以内
- 只能依据提供的 JSON 判断
""".strip()


USER_PROMPT_TEMPLATE = """
分析以下职位并返回评分。

{scoring_rubric}

职位 JSON：
{job_json}

请严格返回以下 JSON：
{{
  "score_activity": <0-30>,
  "score_jd": <0-25>,
  "score_company": <0-20>,
  "score_salary": <0-15>,
  "score_other": <0-10>,
  "total": <int>,
  "verdict": <"apply" | "apply_with_caution" | "skip">,
  "red_flags": [<最多 3 个简短问题>],
  "reasoning": "<50字以内总结>"
}}
""".strip()


def build_user_prompt(job_json: str) -> str:
    return USER_PROMPT_TEMPLATE.format(
        scoring_rubric=SCORING_RUBRIC,
        job_json=job_json,
    )
