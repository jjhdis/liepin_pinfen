# 知乎爬虫策略文档（保守高成功率版）

## 当前定位

这份文档当前对应第四阶段“企业可靠性增强”的下一步实现方案。

目前项目已经先落地了：

- `jobs_cleaned` 中的企业检查判定字段
- `company_enriched` 公司级缓存表
- 清洗阶段的 `need_company_check` 判定逻辑

下一步会新增独立入口（如 `company_enrich.py`），再按这份文档尝试知乎抓取。

当前还没有把知乎请求直接接进：

- `clean_jobs.py`
- `score_jobs.py`

这样做是为了避免知乎抓取拖慢清洗和评分主流程。

## 核心原则

> 不模拟 DOM 操作，不用 Selenium，纯 HTTP 请求 + 真实 Cookie，最低风险。

---

## 环境依赖

```bash
pip install curl_cffi
```

`curl_cffi` 替代 `requests`，TLS 指纹与真实 Chrome 一致，是成功率最关键的一步。

---

## 第一步：Cookie 获取策略

**唯一推荐方式：手动登录 + 浏览器导出**

1. 正常登录 zhihu.com
2. 打开 DevTools → Application → Cookies
3. 重点保存以下字段：

| Cookie 字段 | 作用 |
|------------|------|
| `z_c0` | 身份认证，最核心 |
| `_zap` | 行为追踪 session，建议保留 |
| `_xsrf` | CSRF token |
| `tst` | 设备信任标记，可选 |

保存为 `cookies.json`，格式：
```json
{
  "z_c0": "xxxxxx",
  "_xsrf": "xxxxxx",
  "_zap": "xxxxxx",
  "tst": "xxxxxx"
}
```

**Cookie 有效期约 7~30 天**，过期重新导出即可。

---

## 第二步：请求头策略

从浏览器 Network 面板直接复制真实请求头，重点字段：

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.zhihu.com/search?q={keyword}&type=content",
    "Origin": "https://www.zhihu.com",
    "x-requested-with": "fetch",
    "x-zse-93": "101_3_3.0",
    "x-ab-param": "",   # 从真实请求抄，或留空
}
```

---

## 第三步：搜索 API

```
GET https://www.zhihu.com/api/v4/search_v3
    ?t=general
    &q={公司名}
    &offset=0
    &limit=10
```

返回结构中：
- `data[].type` → `answer` / `article` / `question`
- `data[].object.id` → 用于下一步拉全文
- `data[].object.excerpt` → 摘要，不够时才拉全文

---

## 第四步：全文 API

```
# 答案全文
GET https://www.zhihu.com/api/v4/answers/{answer_id}
    ?include=content,voteup_count

# 专栏文章全文
GET https://www.zhihu.com/api/v4/articles/{article_id}
    ?include=content
```

返回的 `content` 字段是 HTML，用 `BeautifulSoup` 提取纯文本。

---

## 第五步：频率控制策略（最保守）

```
搜索请求：间隔 5~10 秒随机
全文请求：间隔 3~6 秒随机
每次会话最多请求：20~30 次
每天总请求上限：50 次
连续运行后：休息 30 分钟以上
```

两次请求之间用 `time.sleep(random.uniform(min, max))` 实现。

---

## 第六步：异常处理策略

| 响应状态 | 含义 | 处理方式 |
|---------|------|---------|
| `200` | 正常 | 继续 |
| `401` | Cookie 失效 | 停止，重新导出 cookie |
| `403` | 签名或频率问题 | 停止，等待 1 小时以上 |
| `429` | 频率限制 | 立即停止，等待 2~4 小时 |
| `521` | 人机验证 | 停止，手动登录刷新 cookie |

遇到非 200 立即停止当次任务，不要重试。

---

## 关于 x-zse-93 签名

大部分情况下带着有效 `z_c0` cookie，签名校验不严格，直接用固定值 `101_3_3.0` 即可。

若返回 `400` 且提示签名错误，从最近一次真实浏览器请求中抄最新值覆盖。

---

## 整体流程图

```
加载 cookies.json
       ↓
构造 curl_cffi Session，注入 Cookie + Headers
       ↓
调用搜索 API，拿到结果列表
       ↓
取前 2~3 条（type=answer 优先）
       ↓
逐条调用全文 API（每次随机延迟）
       ↓
BeautifulSoup 提取纯文本
       ↓
输出文本，交给你的清洗/分析模块
```

---

## 成功率预估

| 条件 | 成功率 |
|------|------|
| curl_cffi + 有效 z_c0 + 保守频率 | ~90% |
| requests + 有效 z_c0 + 保守频率 | ~70% |
| 无 Cookie 任何方案 | <20% |
