# Phase5 最终开发文档

## 1. 阶段定位

Phase5 的目标不是继续扩功能，而是把现有链路收敛成一套可以稳定联调、可批量运行、可观察、可恢复的运行方案。

截至 Phase5，项目主链路已经明确为：

1. 第一阶段抓取 -> `jobs`
2. 第二阶段清洗 -> `jobs_cleaned`
3. 第四阶段企业增强 -> `company_enriched`
4. 第三阶段评分 -> `scores`

Phase5 负责的是：

- 强化猎聘详情抓取稳定性
- 收敛失败分类和停批边界
- 固化 Cookie 刷新与轮换方式
- 固化后处理串联入口
- 为后续 dashboard / 管理页提供稳定状态字段和查询结构

Phase5 不负责：

- 前端页面正式实现
- 多招聘站正式接入
- 分布式调度或重型工作流系统
- `C 类` 高危事件后的完整人工恢复体系

`C 类` 事件、Cookie profile 正式管理、账号池恢复闭环，统一放到 Phase6 处理。

## 2. 当前已落地能力

### 2.1 抓取链路

- `list` 使用接近真实访问的搜索 URL。
- `list` 从真实职位卡片提取 `job_id` 与真实 `detail_url`。
- `list` 已跳过 `display:none` 的隐藏职位卡。
- `detail` 直接访问真实 `detail_url`，不再点击搜索卡片进入。
- `detail` 对 `ld+json` 的多行文本、非法反斜杠等场景做了容错。

### 2.2 详情异常分类

详情抓取阶段的显式状态已收敛为：

- `pending`
- `success`
- `expired`
- `wrong_page`
- `login_required`
- `blocked`
- `parse_failed`

这些状态用于 `jobs.detail_status`，不再依赖“标题是否为空”等隐式判断。

### 2.3 后处理链路

已保留独立入口：

- `clean_jobs.py`
- `company_enrich.py`
- `score_jobs.py`

并新增串联入口：

- `postprocess_pipeline.py`

该入口只做顺序编排，不重写各阶段业务逻辑，用作后续前端“后处理按钮”的统一入口。

### 2.4 Cookie 工具链

已落地以下工具：

- `tools/refresh_liepin_cookies.py`
  - 半自动登录并导出猎聘 Cookie
  - 登录成功后同时导出消息接口上下文文件
- `check_liepin_messages.py`
  - 使用 Cookie + 消息接口上下文检查消息状态
  - 已修正为按 `c.liepin.com` 上下文请求
- `rotate_liepin_cookies.py`
  - 扫描 `cookies/` 目录中的猎聘 Cookie
  - 按顺序切换 Cookie 执行 `detail`

## 3. Phase5 核心运行原则

### 3.1 抓取与后处理继续解耦

- `list/detail` 只负责生产和完善原始职位数据。
- 清洗、企业增强、评分继续作为独立阶段存在。
- 不把知乎抓取、AI 评分等逻辑塞回主抓取循环。

### 3.2 先做明确分类，再做自动化

当前优先级是：

1. 明确状态
2. 明确停批条件
3. 明确可重试 / 不可重试边界
4. 明确日志和查询口径

而不是过早做复杂调度或状态机。

### 3.3 同类坑只踩一次

Phase5 的目标不是完全不遇到异常，而是：

- 异常要能分类
- 命中后要尽快停批
- 同一异常目标不应在短时间内反复访问

### 3.4 Cookie 不是一次性黑箱

当前已经形成明确共识：

- Cookie 既是抓取凭证，也是运行资源
- 需要显式管理其可用性、轮换顺序和刷新流程
- 但 Cookie profile / 账号池状态机仍属于 Phase6

## 4. 详情抓取状态与停批规则

## 4.1 `jobs.detail_status`

当前 `jobs.detail_status` 固定为：

- `pending`
- `success`
- `expired`
- `wrong_page`
- `login_required`
- `blocked`
- `parse_failed`

约定如下：

- 只有 `pending` 会进入主抓取队列。
- 其他状态不自动重新进入 `detail`。

## 4.2 终端日志口径

### `list`

- `list-success`
- `list-stop`
- `list-failed`

### `detail`

- `detail-success`
- `detail-stop`
- `detail-failed`

其中：

- `detail-stop`
  - `blocked`
  - `login_required`
  - `expired`
  - `wrong_page`
- `detail-failed`
  - `parse_failed`
  - 其他未分类异常

## 4.3 详情阶段停批条件

当前阶段，以下情况都视为立即停批信号：

1. `blocked`
2. `login_required`
3. `expired`
4. `wrong_page`

其中前两类属于显式风控，后两类在当前阶段按“高风险前兆”处理。

原因是实测已经证明：

- `expired / wrong_page` 之后继续跑，极容易在后续请求中转成 `blocked`
- 异常职位不是普通业务脏数据，而是会抬高当前 Cookie 风险

## 4.4 `parse_failed`

`parse_failed` 当前不按显式风控处理，但必须：

- 保留调试产物
- 保留失败状态
- 后续人工分析

它属于“页面已打开，但解析层不兼容”的问题，不应和 `blocked/login_required` 混淆。

## 5. Cookie 与轮换结论

## 5.1 已确认的工具闭环

当前 Cookie 维护流程已形成闭环：

1. `tools/refresh_liepin_cookies.py`
2. 人工完成短信验证码 / 滑块 / 确认步骤
3. 自动导出 Cookie 到 `cookies/`
4. 自动导出消息接口上下文文件
5. `check_liepin_messages.py` 验证消息接口是否可用
6. `main.py` / `rotate_liepin_cookies.py` 消费该 Cookie

## 5.2 今天的实测结论

截至今天，新的关键实测结论是：

1. 使用多 Cookie 顺序切换，累计 `75` 条 detail 全部抓取成功。
2. 在这 `75` 条之后，重新拿第一个 Cookie 再跑 `25` 条 detail，仍然成功。

这说明至少在当前样本下，以下结论成立：

- “一次性顺序切换”已经被验证可行。
- “同日复用同一 Cookie”并非天然不可行。
- 只要前一轮没有进入明显高危状态，Cookie 在同日后续再次投入使用是有可能稳定工作的。

## 5.3 当前阶段的稳定结论

截至 Phase5 结束，关于 Cookie 的结论应表述为：

- 单 Cookie 不应无限连续长跑。
- 多 Cookie 顺序切换可行，已经有 `75` 条成功样本。
- 第一份 Cookie 在后续再次投入并再跑 `25` 条成功，说明“冷却后复用”至少具备可行性。
- 但 Cookie 的正式状态管理、是否需要显式 cooldown 标记、复用阈值模型，仍放在 Phase6 处理。

也就是说，Phase5 已经从“完全不知道能不能复用”推进到：

- **顺序切换已验证**
- **同日复用已有正样本**

## 5.4 当前仍需保守的地方

虽然今天结果很好，但当前阶段仍不应把策略写死成激进配置。原因是：

- 单轮成功不代表长期稳定阈值已经完全明确
- 地雷职位、错页、失效页仍可能突然抬高风险
- `C 类` 事件恢复流程还没有正式建设

因此 Phase5 的正确结论不是“已经彻底安全”，而是：

- 现有链路已经进入可批量联调阶段
- 但仍需围绕低风险稳定运行继续保守推进

## 6. 消息接口凭证方案

本阶段新增了一条重要能力：登录脚本在导出 Cookie 的同时，也导出一份消息接口请求上下文。

输出物包括：

- `cookie_..._liepin.json`
- `cookie_..._liepin_message_context.json`

其中上下文文件包含：

- `origin`
- `referer`
- `user_agent`
- `accept_language`
- `sec-ch-ua*`
- `x-client-type`
- `x-fscp-fe-version`
- `x-fscp-std-info`
- `x-fscp-version`

运行时由 `check_liepin_messages.py` 再动态生成：

- `X-Fscp-Trace-Id`
- `X-Fscp-Bi-Stat`

这套方案的意义是：

- 登录脚本不只导出 Cookie
- 同时导出调用消息接口所需的请求上下文
- 后续不需要手工抄浏览器请求头

## 7. 字段与查询结构

## 7.1 `jobs`

Phase5 对 `jobs` 的核心要求是补齐详情抓取状态字段：

- `detail_status`
- `detail_error_message`
- `detail_last_attempt_at`

这些字段只描述详情抓取阶段，不与清洗、增强、评分混成总状态机。

## 7.2 `jobs_cleaned`

当前主要依赖：

- `clean_status`
- `score_status`
- `need_company_check`
- `company_check_status`
- `company_check_reasons_json`

## 7.3 `company_enriched`

当前主要依赖：

- `status`
- `risk_level`
- `zhihu_filtered_results_json`
- `last_checked_at`

## 7.4 `scores`

当前主要依赖：

- `total`
- `verdict`
- `score_status`
- `scored_at`

## 7.5 查询目标

Phase5 阶段需要支持三类查询：

1. 失败分类统计
2. 待处理队列统计
3. 最终结果联表查看

相关补充文档：

- [phase5_fields_and_sql.md](/abs/path/D:/channel/PythonProject2/docs/phase5_fields_and_sql.md)
- [phase5_status_mapping.md](/abs/path/D:/channel/PythonProject2/docs/phase5_status_mapping.md)

## 8. 风险边界与剩余问题

## 8.1 Phase5 已解决的问题

- 详情抓取状态不再靠隐式字段反推
- `expired / wrong_page` 已纳入停批逻辑
- 隐藏职位卡已纳入排雷范围
- Cookie 半自动刷新链路已打通
- 消息接口校验脚本已打通
- 多 Cookie 顺序切换已拿到成功样本
- 同日复用已拿到成功样本

## 8.2 Phase5 未解决的问题

以下内容仍不在 Phase5 内闭合：

- `C 类` 高危事件后的人工验证闭环
- Cookie profile 的正式状态管理
- 冷却时间、可复用阈值的正式策略模型
- 账号池管理与前端人工恢复视图
- 更大样本下的长期稳定上限

这些统一进入 Phase6。

## 9. 阶段验收结论

Phase5 结束时，项目已经从“单链路原型联调”进入“可批量稳定运行验证”阶段。

截至当前，最重要的验收结论是：

1. 主链路结构已经稳定：
   - `jobs -> jobs_cleaned -> company_enriched -> scores`
2. 详情抓取失败分类和停批边界已经明确。
3. Cookie 刷新、消息校验、顺序切换工具链已经打通。
4. 今日实测已确认：
   - `75` 条 detail 全部成功
   - 之后首个 Cookie 再跑 `25` 条也成功
5. 因此，Phase5 可以视为已经完成“稳定性强化与批量运行”的阶段目标。

## 10. 与 Phase6 的边界

Phase5 的最终边界明确为：

- Phase5 解决“尽量少触发风险，并在风险前兆时及时停批”
- Phase6 解决“如果已经触发高危事件，如何恢复 Cookie / 账号池并继续运行”

因此后续进入 Phase6 时，应从以下问题展开：

1. Cookie profile 正式建模
2. `ready / cooldown / needs_manual_verify / disabled`
3. `crawl_log.cookie_profile_id`
4. `C 类` 事件后的人工恢复闭环
5. Cookie 轮换、冷却、复用策略正式化

---

## 附注

本文件是 Phase5 的最终收敛版。

过程性试探、历史假设、阶段内中间判断，保留在：

- [phase5_issue_log.md](/abs/path/D:/channel/PythonProject2/docs/phase5_issue_log.md)

后续若与本文件冲突，以本文件为准。
