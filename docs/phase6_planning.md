# Phase6 规划

## 目标定位

Phase6 不再只讨论“低风险稳定运行”，而是进入更明确的账号与风控恢复管理。

这一阶段处理的是：

- `C 类` 高危事件触发后的人工验证流程
- Cookie / 账号池恢复流程
- 被要求手机号验证后的处置策略
- 长时间不验证可能导致封禁的风险控制

## 与 Phase5 的边界

Phase5 的目标是：

- 尽量不要触发 `C 类`
- 通过保守节奏、异常计数、提前停机来降低风险
- 不把系统设计建立在“触发后再补救”上

Phase6 才处理：

- 一旦触发 `C 类`，如何尽快人工验证
- 验证后如何恢复 Cookie
- 哪些账号继续使用，哪些账号进入停用/观察

## 结论

当前明确约定：

- `C 类` 事件不是当前 Phase5 的主处理对象
- 因为一旦触发 `C 类`，往往已经进入需要尽快人工验证的阶段
- 如果长时间不验证，账号存在进一步受限甚至被封的风险

因此后续统一放到 Phase6 处理。

## Phase6 需要覆盖的内容

### 1. `C 类` 事件定义

包括但不限于：

- `captcha`
- `blocked`
- `login_required`
- 安全中心
- 手机号验证页

### 2. 人工验证闭环

- 触发后立即停用当前 Cookie
- 标记为“待人工验证”
- 人工完成验证
- 刷新 Cookie
- 验证恢复是否成功

### 3. Cookie / 账号池状态

建议后续至少区分：

- `ready`
- `cooldown`
- `needs_manual_verify`
- `disabled`

### 3.1 Cookie Profile 设计占位

Phase6 正式推进前，当前已经明确后续需要引入 `cookie profile` 概念。

最小设计原则：

- 一个 Cookie 不再只是一份匿名 `cookies.json`
- 后续每次请求都应能追溯“是哪个 profile 在跑”
- 这部分优先从日志层面落地，而不是先做复杂切换系统

当前建议的最小字段：

- `crawl_log.cookie_profile_id`

字段含义：

- 标记这次请求使用的是哪个 Cookie profile
- 例如：
  - `liepin_a`
  - `liepin_b`
  - `liepin_c`

当前为什么优先放在 `crawl_log`：

- `crawl_log` 本来就是单次请求历史
- `cookie_profile_id` 也属于单次请求上下文
- 语义一致

后续如果再扩展：

- 再考虑是否需要在 `jobs` 中保留 `last_cookie_profile_id`
- 但这不是当前最小必要项

### 4. 账号恢复策略

- 验证后立即恢复还是观察一段时间
- 同一账号当天是否继续跑
- 多次进入 `needs_manual_verify` 的账号是否降权或停用

### 5. 前端管理要求

Phase6 的前端或管理页需要能看到：

- 当前哪个账号触发了 `C 类`
- 触发时间
- 触发原因
- 是否已人工验证
- 最新 Cookie 更新时间
- 当前是否允许继续使用

## 当前明确放到 Phase6 的事项

以下内容不在当前 Phase5 里实现，统一放到 Phase6：

1. `C 类` 事件触发后的人工验证与恢复流程
2. Cookie profile 的正式引入和管理
3. `crawl_log.cookie_profile_id` 等多 Cookie 追踪字段
4. Cookie 池状态管理：
   - `ready`
   - `cooldown`
   - `needs_manual_verify`
   - `disabled`
5. Cookie 切换、冷却、恢复和账号策略
6. 前端中的 Cookie profile 管理与人工恢复视图
