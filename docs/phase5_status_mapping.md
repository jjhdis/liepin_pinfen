# Phase5 状态与日志映射

## 目标

统一三件事的口径：

1. `jobs.detail_status`
2. 终端日志前缀
3. `crawl_log` 的历史事件记录

当前原则：

- `jobs` 保存“当前状态快照”
- `crawl_log` 保存“某次请求发生了什么”
- 终端日志直接复用同一套状态词

---

## 一、详情抓取状态

`jobs.detail_status` 当前固定为：

- `pending`
  - 还没抓详情
- `success`
  - 详情页抓取成功并写回 `jobs`
- `expired`
  - 职位已关闭 / 失效
- `wrong_page`
  - 落到非目标详情页
- `login_required`
  - 被登录拦截
- `blocked`
  - 验证码 / 安全中心 / 风控页
- `parse_failed`
  - 页面打开了，但解析失败

当前约定：

- `pending` 之外的状态，不自动再次进入主抓取队列
- 主抓取队列现在只消费 `detail_status = 'pending'`

---

## 二、终端日志口径

### `list`

- `list-success`
  - 列表页访问成功，或成功写入 stub
- `list-stop`
  - 列表页触发风控 / 登录拦截，当前批次停止
- `list-failed`
  - 其他异常，或提取不到 job id

### `detail`

- `detail-success`
  - 当前 job 详情抓取成功
- `detail-stop`
  - `blocked` / `login_required`
  - `expired` / `wrong_page`
  - 当前批次立即停止
- `detail-failed`
  - `parse_failed` 或其他未分类异常

---

## 三、异常到状态的映射

### `detail`

- `DetailPageBlockedError`
  - `detail_status = 'blocked'`
  - 终端日志：`detail-stop`
- `DetailPageLoginRequiredError`
  - `detail_status = 'login_required'`
  - 终端日志：`detail-stop`
- `DetailPageExpiredError`
  - `detail_status = 'expired'`
  - 终端日志：`detail-stop`
- `DetailPageMismatchError`
  - `detail_status = 'wrong_page'`
  - 终端日志：`detail-stop`
- 其他异常
  - `detail_status = 'parse_failed'`
  - 终端日志：`detail-failed`

### `list`

`list` 当前不写职位级状态字段，因为它面对的是“列表页请求”，不是单个 job。

当前只保留：

- `crawl_log.success`
- `crawl_log.error_message`
- 终端日志前缀

也就是说：

- `list` 负责生产 `jobs` stub
- `detail` 负责给具体 job 写状态

---

## 四、`crawl_log` 的用途

当前明确：

- `jobs.detail_status`
  - 查当前 job 现在是什么状态
- `crawl_log`
  - 查某次请求的历史事件

因此后续查询建议：

- 看“当前爬取状况”优先查 `jobs`
- 看“失败历史和频次”查 `crawl_log`

不要再用：

- `title 是否为空`
- `crawl_log.error_message`

去间接反推当前状态。

---

## 五、当前主链路行为

当前主链路的实际行为收敛为：

1. `list` 抓列表页并写入 `jobs` stub
2. stub 默认状态为 `pending`
3. `detail` 只抓 `pending`
4. 抓成功写 `success`
5. `expired / wrong_page` 直接剔除当前原始 job，并立即停当前批次
6. `blocked / login_required` 立即停当前批次
7. `parse_failed` 保留失败状态，后续人工分析
