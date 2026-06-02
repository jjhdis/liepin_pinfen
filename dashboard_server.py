import argparse
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import PATHS


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jobs Dashboard</title>
  <style>
    :root {
      --bg: #f4f0e8;
      --panel: #fffaf2;
      --line: #d9cdb8;
      --text: #1f1a14;
      --muted: #6e6357;
      --accent: #165d52;
      --warn: #9a5b00;
      --danger: #a13131;
      --ok: #2f6b2f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, #efe4d3 0, transparent 28%),
        linear-gradient(180deg, #f7f1e7 0%, #f1eadf 100%);
      color: var(--text);
    }
    .wrap { max-width: 1480px; margin: 0 auto; padding: 24px; }
    .topbar {
      display: flex; justify-content: space-between; align-items: end; gap: 16px;
      margin-bottom: 20px;
    }
    .nav {
      display: flex;
      gap: 8px;
      margin: 0 0 16px 0;
      flex-wrap: wrap;
    }
    .nav a {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--text);
      text-decoration: none;
      background: rgba(255,250,242,.9);
      font-size: 13px;
    }
    .nav a.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    h1 { margin: 0; font-size: 30px; letter-spacing: .02em; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
    .meta { color: var(--muted); font-size: 13px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }
    .card, .panel {
      background: rgba(255,250,242,.96);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(64, 44, 17, 0.07);
    }
    .card { padding: 16px; min-height: 110px; }
    .k { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    .v { font-size: 34px; font-weight: 700; margin-top: 10px; }
    .note { margin-top: 8px; color: var(--muted); font-size: 12px; }
    .sections {
      display: grid;
      grid-template-columns: 1.15fr .85fr;
      gap: 14px;
      margin-bottom: 14px;
    }
    .panel { padding: 14px; overflow: hidden; }
    .panel h2 {
      margin: 0 0 10px 0;
      font-size: 16px;
      letter-spacing: .02em;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      border-top: 1px solid #eadfce;
      padding: 9px 8px;
      vertical-align: top;
      text-align: left;
      word-break: break-word;
    }
    thead th {
      border-top: none;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      padding: 2px 9px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      border: 1px solid currentColor;
      white-space: nowrap;
    }
    .chip.pending { color: #7d6200; background: #fff3cc; }
    .chip.success { color: #245d24; background: #def6de; }
    .chip.expired, .chip.wrong_page { color: #8a5410; background: #f7e4c7; }
    .chip.blocked, .chip.login_required { color: #8b2222; background: #f7d8d8; }
    .chip.parse_failed { color: #5a3f7b; background: #e6def6; }
    .chip.default { color: #555; background: #eee; }
    .mono { font-family: Consolas, "Courier New", monospace; font-size: 12px; }
    .muted { color: var(--muted); }
    .job-link {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .job-link:hover { text-decoration: underline; }
    .stack { display: grid; gap: 14px; }
    .wide { margin-top: 14px; }
    .controls {
      display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
      margin-bottom: 10px;
    }
    input, select, button {
      border: 1px solid var(--line);
      background: #fffdf8;
      color: var(--text);
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
    }
    button {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      cursor: pointer;
    }
    .empty { color: var(--muted); padding: 12px 2px 2px; }
    @media (max-width: 1100px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .sections { grid-template-columns: 1fr; }
    }
    @media (max-width: 700px) {
      .wrap { padding: 14px; }
      .grid { grid-template-columns: 1fr; }
      .topbar { flex-direction: column; align-items: start; }
      .v { font-size: 28px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <h1>Jobs Dashboard</h1>
        <div class="sub">仅观察详情抓取状态、失败分布和最近尝试情况</div>
      </div>
      <div class="meta" id="meta">loading...</div>
    </div>

    <div class="nav">
      <a class="active" href="/">抓取监控</a>
      <a href="/scores">Score 结果</a>
    </div>

    <div class="grid" id="cards"></div>

    <div class="sections">
      <div class="stack">
        <div class="panel">
          <h2>当前抓取状态</h2>
          <div id="status-table"></div>
        </div>
        <div class="panel">
          <h2>最近失败分类</h2>
          <div id="failures-table"></div>
        </div>
      </div>
      <div class="stack">
        <div class="panel">
          <h2>抓取概览</h2>
          <div id="queues-table"></div>
        </div>
        <div class="panel">
          <h2>最近失败 Jobs</h2>
          <div id="failed-jobs-table"></div>
        </div>
      </div>
    </div>

    <div class="panel wide">
      <h2>当前 Jobs</h2>
      <div class="controls">
        <select id="status-filter">
          <option value="">全部状态</option>
          <option value="pending">pending</option>
          <option value="success">success</option>
          <option value="expired">expired</option>
          <option value="wrong_page">wrong_page</option>
          <option value="blocked">blocked</option>
          <option value="login_required">login_required</option>
          <option value="parse_failed">parse_failed</option>
        </select>
        <input id="keyword-filter" placeholder="keyword 过滤，可留空">
        <button id="reload-btn">刷新</button>
      </div>
      <div id="jobs-table"></div>
    </div>

    <div class="panel wide">
      <h2>抓取监控视图</h2>
      <div id="final-table"></div>
    </div>
  </div>

  <script>
    const chipClass = (value) => {
      const known = ['pending','success','expired','wrong_page','blocked','login_required','parse_failed'];
      return known.includes(value) ? value : 'default';
    };

    const esc = (value) => {
      if (value === null || value === undefined) return '';
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    };

    const chip = (value) => `<span class="chip ${chipClass(value)}">${esc(value || '')}</span>`;

    const makeTable = (columns, rows, formatters = {}) => {
      if (!rows || !rows.length) return '<div class="empty">暂无数据</div>';
      const head = columns.map(col => `<th>${esc(col.label)}</th>`).join('');
      const body = rows.map(row => {
        return `<tr>${columns.map(col => {
          const raw = row[col.key];
          const html = formatters[col.key] ? formatters[col.key](raw, row) : esc(raw ?? '');
          return `<td>${html}</td>`;
        }).join('')}</tr>`;
      }).join('');
      return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    };

    async function getJson(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    }

    function renderCards(summary) {
      const cards = [
        ['待抓详情', summary.pending_detail, 'jobs.detail_status = pending'],
        ['抓取成功', summary.success_detail, 'jobs.detail_status = success'],
        ['抓取失败', summary.failed_detail, 'blocked / login_required / parse_failed'],
        ['当前总量', summary.jobs_total, '当前 jobs 表记录数'],
      ];
      document.getElementById('cards').innerHTML = cards.map(([k, v, note]) => `
        <div class="card">
          <div class="k">${esc(k)}</div>
          <div class="v">${esc(v)}</div>
          <div class="note">${esc(note)}</div>
        </div>
      `).join('');
    }

    async function loadDashboard() {
      const status = document.getElementById('status-filter').value;
      const keyword = document.getElementById('keyword-filter').value.trim();
      const qs = new URLSearchParams();
      if (status) qs.set('status', status);
      if (keyword) qs.set('keyword', keyword);

      const [summary, statuses, failures, failedJobs, jobs] = await Promise.all([
        getJson('/api/summary'),
        getJson('/api/detail-status'),
        getJson('/api/failures'),
        getJson('/api/failed-jobs'),
        getJson(`/api/jobs?${qs.toString()}`),
      ]);

      renderCards(summary);

      document.getElementById('status-table').innerHTML = makeTable(
        [
          { key: 'detail_status', label: '状态' },
          { key: 'cnt', label: '数量' },
        ],
        statuses,
        { detail_status: (v) => chip(v) }
      );

      document.getElementById('failures-table').innerHTML = makeTable(
        [
          { key: 'day', label: '日期' },
          { key: 'error_message', label: '错误' },
          { key: 'cnt', label: '次数' },
        ],
        failures
      );

      document.getElementById('queues-table').innerHTML = makeTable(
        [
          { key: 'name', label: '指标' },
          { key: 'value', label: '数量' },
        ],
        [
          { name: 'pending_detail', value: summary.pending_detail },
          { name: 'success_detail', value: summary.success_detail },
          { name: 'failed_detail', value: summary.failed_detail },
          { name: 'jobs_total', value: summary.jobs_total },
        ]
      );

      document.getElementById('failed-jobs-table').innerHTML = makeTable(
        [
          { key: 'job_id', label: 'job_id' },
          { key: 'detail_status', label: '状态' },
          { key: 'detail_error_message', label: '错误' },
          { key: 'detail_last_attempt_at', label: '最近尝试' },
        ],
        failedJobs,
        {
          detail_status: (v) => chip(v),
          job_id: (v) => `<span class="mono">${esc(v)}</span>`,
        }
      );

      document.getElementById('jobs-table').innerHTML = makeTable(
        [
          { key: 'job_id', label: 'job_id' },
          { key: 'keyword', label: 'keyword' },
          { key: 'title', label: 'title' },
          { key: 'detail_status', label: '状态' },
          { key: 'detail_error_message', label: '错误' },
          { key: 'detail_last_attempt_at', label: '最近尝试' },
          { key: 'updated_at', label: '更新时间' },
        ],
        jobs,
        {
          title: (v, row) => {
            if (!v) return '<span class="muted">-</span>';
            if (!row.detail_url) return esc(v);
            return `<a class="job-link" href="${esc(row.detail_url)}" target="_blank" rel="noreferrer">${esc(v)}</a>`;
          },
          detail_status: (v) => chip(v),
          job_id: (v) => `<span class="mono">${esc(v)}</span>`,
        }
      );

      document.getElementById('final-table').innerHTML = makeTable(
        [
          { key: 'job_id', label: 'job_id' },
          { key: 'keyword', label: 'keyword' },
          { key: 'detail_status', label: '状态' },
          { key: 'detail_error_message', label: '错误' },
          { key: 'detail_last_attempt_at', label: '最近尝试' },
          { key: 'updated_at', label: '更新时间' },
        ],
        jobs.slice(0, 120),
        {
          detail_status: (v) => chip(v),
          job_id: (v) => `<span class="mono">${esc(v)}</span>`,
        }
      );

      document.getElementById('meta').textContent = `自动刷新 30s | 最后刷新 ${new Date().toLocaleString()}`;
    }

    document.getElementById('reload-btn').addEventListener('click', loadDashboard);
    setInterval(loadDashboard, 30000);
    loadDashboard().catch(err => {
      document.getElementById('meta').textContent = `加载失败: ${err.message}`;
    });
  </script>
</body>
</html>
"""


SCORES_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Score Dashboard</title>
  <style>
    :root {
      --bg: #f2efe7;
      --panel: #fffdf7;
      --line: #ddd4c6;
      --text: #1f1b16;
      --muted: #6e6558;
      --accent: #204f77;
      --ok: #2f6b2f;
      --warn: #8b5b10;
      --danger: #8d2c2c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top right, #dfe8ef 0, transparent 26%),
        linear-gradient(180deg, #f7f3eb 0%, #f1ece3 100%);
    }
    .wrap { max-width: 1500px; margin: 0 auto; padding: 24px; }
    .topbar {
      display: flex; justify-content: space-between; align-items: end; gap: 16px;
      margin-bottom: 18px;
    }
    h1 { margin: 0; font-size: 30px; letter-spacing: .02em; }
    .sub, .meta { color: var(--muted); font-size: 13px; }
    .nav {
      display: flex; gap: 8px; margin: 0 0 16px 0; flex-wrap: wrap;
    }
    .nav a {
      display: inline-flex; align-items: center; padding: 8px 12px;
      border-radius: 999px; border: 1px solid var(--line); color: var(--text);
      text-decoration: none; background: rgba(255,253,247,.92); font-size: 13px;
    }
    .nav a.active {
      background: var(--accent); border-color: var(--accent); color: #fff;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .card, .panel {
      background: rgba(255,253,247,.96);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 12px 28px rgba(43, 37, 28, 0.06);
    }
    .card { padding: 16px; min-height: 108px; }
    .k { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    .v { font-size: 34px; font-weight: 700; margin-top: 10px; }
    .note { margin-top: 8px; color: var(--muted); font-size: 12px; }
    .panel { padding: 14px; overflow: hidden; margin-bottom: 14px; }
    .panel h2 { margin: 0 0 10px 0; font-size: 16px; }
    .controls {
      display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px;
    }
    input, select, button {
      border: 1px solid var(--line);
      background: #fffdfa;
      color: var(--text);
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
    }
    button {
      background: var(--accent); color: #fff; border-color: var(--accent); cursor: pointer;
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td {
      border-top: 1px solid #ece3d6;
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }
    thead th {
      border-top: none;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .chip {
      display: inline-flex; align-items: center; padding: 2px 9px; border-radius: 999px;
      font-size: 12px; font-weight: 600; border: 1px solid currentColor; white-space: nowrap;
    }
    .chip.apply { color: #245d24; background: #def6de; }
    .chip.apply_with_caution { color: #8b5b10; background: #f8e7c8; }
    .chip.skip { color: #8d2c2c; background: #f5dada; }
    .chip.none { color: #666; background: #efefef; }
    .chip.low { color: #2d5f7f; background: #dceefa; }
    .chip.medium { color: #8b5b10; background: #f8e7c8; }
    .chip.high { color: #8d2c2c; background: #f5dada; }
    .chip.pending { color: #7d6200; background: #fff3cc; }
    .chip.success { color: #245d24; background: #def6de; }
    .chip.expired, .chip.wrong_page { color: #8a5410; background: #f7e4c7; }
    .chip.blocked, .chip.login_required { color: #8b2222; background: #f7d8d8; }
    .chip.parse_failed { color: #5a3f7b; background: #e6def6; }
    .chip.default { color: #555; background: #eee; }
    .mono { font-family: Consolas, "Courier New", monospace; font-size: 12px; }
    .muted { color: var(--muted); }
    .job-link {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .job-link:hover { text-decoration: underline; }
    .empty { color: var(--muted); padding: 12px 2px 2px; }
    @media (max-width: 1100px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 700px) {
      .wrap { padding: 14px; }
      .grid { grid-template-columns: 1fr; }
      .topbar { flex-direction: column; align-items: start; }
      .v { font-size: 28px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <h1>Score Dashboard</h1>
        <div class="sub">展示评分结果、公司风险和抓取状态，服务最终投递判断</div>
      </div>
      <div class="meta" id="meta">loading...</div>
    </div>

    <div class="nav">
      <a href="/">抓取监控</a>
      <a class="active" href="/scores">Score 结果</a>
    </div>

    <div class="grid" id="cards"></div>

    <div class="panel">
      <h2>Score 结果表</h2>
      <div class="controls">
        <select id="verdict-filter">
          <option value="">全部建议</option>
          <option value="apply">apply</option>
          <option value="apply_with_caution">apply_with_caution</option>
          <option value="skip">skip</option>
        </select>
        <select id="detail-filter">
          <option value="">全部抓取状态</option>
          <option value="success">success</option>
          <option value="pending">pending</option>
          <option value="blocked">blocked</option>
          <option value="login_required">login_required</option>
          <option value="parse_failed">parse_failed</option>
          <option value="expired">expired</option>
          <option value="wrong_page">wrong_page</option>
        </select>
        <input id="keyword-filter" placeholder="keyword 过滤，可留空">
        <button id="reload-btn">刷新</button>
      </div>
      <div id="scores-table"></div>
    </div>
  </div>

  <script>
    const esc = (value) => {
      if (value === null || value === undefined) return '';
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    };

    const chip = (value) => {
      const v = value || 'none';
      return `<span class="chip ${esc(v)}">${esc(v)}</span>`;
    };

    const makeTable = (columns, rows, formatters = {}) => {
      if (!rows || !rows.length) return '<div class="empty">暂无数据</div>';
      const head = columns.map(col => `<th>${esc(col.label)}</th>`).join('');
      const body = rows.map(row => {
        return `<tr>${columns.map(col => {
          const raw = row[col.key];
          const html = formatters[col.key] ? formatters[col.key](raw, row) : esc(raw ?? '');
          return `<td>${html}</td>`;
        }).join('')}</tr>`;
      }).join('');
      return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    };

    async function getJson(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    }

    function renderCards(summary) {
      const cards = [
        ['已评分', summary.scored_total, 'scores 表记录数'],
        ['建议投递', summary.apply_count, 'verdict = apply'],
        ['谨慎投递', summary.caution_count, 'verdict = apply_with_caution'],
        ['跳过', summary.skip_count, 'verdict = skip'],
      ];
      document.getElementById('cards').innerHTML = cards.map(([k, v, note]) => `
        <div class="card">
          <div class="k">${esc(k)}</div>
          <div class="v">${esc(v)}</div>
          <div class="note">${esc(note)}</div>
        </div>
      `).join('');
    }

    async function loadScores() {
      const verdict = document.getElementById('verdict-filter').value;
      const detail = document.getElementById('detail-filter').value;
      const keyword = document.getElementById('keyword-filter').value.trim();
      const qs = new URLSearchParams();
      if (verdict) qs.set('verdict', verdict);
      if (detail) qs.set('detail_status', detail);
      if (keyword) qs.set('keyword', keyword);

      const [summary, rows] = await Promise.all([
        getJson('/api/score-summary'),
        getJson(`/api/score-results?${qs.toString()}`),
      ]);

      renderCards(summary);

      document.getElementById('scores-table').innerHTML = makeTable(
        [
          { key: 'source_name', label: '来源' },
          { key: 'title', label: 'title' },
          { key: 'company_name', label: 'company' },
          { key: 'risk_level', label: '企业风险' },
          { key: 'total', label: '总分' },
          { key: 'verdict', label: '建议' },
          { key: 'red_flags_json', label: '风险标记' },
          { key: 'reasoning', label: '理由' },
          { key: 'scored_at', label: '评分时间' },
        ],
        rows,
        {
          title: (v, row) => {
            if (!v) return '<span class="muted">-</span>';
            if (!row.detail_url) return esc(v);
            return `<a class="job-link" href="${esc(row.detail_url)}" target="_blank" rel="noreferrer">${esc(v)}</a>`;
          },
          source_name: (v) => `<span class="mono">${esc(v)}</span>`,
          verdict: (v) => chip(v),
          risk_level: (v) => chip(v),
          total: (v) => `<strong>${esc(v)}</strong>`,
          red_flags_json: (v) => {
            try {
              const arr = JSON.parse(v || '[]');
              if (!Array.isArray(arr) || !arr.length) return '<span class="muted">-</span>';
              return `<span class="mono">${arr.length} 项</span>`;
            } catch {
              return '<span class="muted">-</span>';
            }
          },
          reasoning: (v) => {
            const text = String(v || '');
            if (!text) return '<span class="muted">-</span>';
            return esc(text.length > 80 ? `${text.slice(0, 80)}...` : text);
          },
        }
      );

      document.getElementById('meta').textContent = `自动刷新 30s | 最后刷新 ${new Date().toLocaleString()}`;
    }

    document.getElementById('reload-btn').addEventListener('click', loadScores);
    setInterval(loadScores, 30000);
    loadScores().catch(err => {
      document.getElementById('meta').textContent = `加载失败: ${err.message}`;
    });
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal local dashboard for jobs.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(PATHS["database"]))
    return parser.parse_args()


class DashboardData:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def fetch_one(self, sql: str, params: tuple = ()) -> dict:
        with closing(self.connect()) as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else {}

    def summary(self) -> dict:
        return self.fetch_one(
            """
            select
              count(*) as jobs_total,
              sum(case when detail_status = 'pending' then 1 else 0 end) as pending_detail,
              sum(case when detail_status = 'success' then 1 else 0 end) as success_detail,
              sum(case when detail_status in ('blocked', 'login_required', 'parse_failed') then 1 else 0 end) as failed_detail
            from jobs
            """
        )

    def detail_status(self) -> list[dict]:
        return self.fetch_all(
            """
            select detail_status, count(*) as cnt
            from jobs
            group by detail_status
            order by cnt desc, detail_status asc
            """
        )

    def failures(self) -> list[dict]:
        return self.fetch_all(
            """
            select
              date(created_at) as day,
              coalesce(error_message, 'UNKNOWN') as error_message,
              count(*) as cnt
            from crawl_log
            where success = 0
            group by date(created_at), coalesce(error_message, 'UNKNOWN')
            order by day desc, cnt desc
            limit 100
            """
        )

    def failed_jobs(self) -> list[dict]:
        return self.fetch_all(
            """
            select
              job_id,
              keyword,
              detail_url,
              detail_status,
              detail_error_message,
              detail_last_attempt_at,
              updated_at
            from jobs
            where detail_status in ('blocked', 'login_required', 'parse_failed')
            order by detail_last_attempt_at desc, updated_at desc
            limit 100
            """
        )

    def jobs(self, *, status: str = "", keyword: str = "") -> list[dict]:
        sql = """
        select
          job_id,
          keyword,
          title,
          detail_url,
          detail_status,
          detail_error_message,
          detail_last_attempt_at,
          created_at,
          updated_at
        from jobs
        where 1 = 1
        """
        params: list[str] = []
        if status:
            sql += " and detail_status = ?"
            params.append(status)
        if keyword:
            sql += " and keyword = ?"
            params.append(keyword)
        sql += """
        order by
          case when detail_last_attempt_at is null then 1 else 0 end asc,
          detail_last_attempt_at desc,
          updated_at desc
        limit 300
        """
        return self.fetch_all(sql, tuple(params))

    def score_summary(self) -> dict:
        return self.fetch_one(
            """
            select
              count(*) as scored_total,
              sum(case when verdict = 'apply' then 1 else 0 end) as apply_count,
              sum(case when verdict = 'apply_with_caution' then 1 else 0 end) as caution_count,
              sum(case when verdict = 'skip' then 1 else 0 end) as skip_count
            from scores
            """
        )

    def score_results(
        self,
        *,
        verdict: str = "",
        detail_status: str = "",
        keyword: str = "",
    ) -> list[dict]:
        sql = """
        select
          s.job_id,
          c.keyword,
          '猎聘' as source_name,
          c.title,
          c.detail_url,
          c.company_name,
          j.detail_status,
          ce.risk_level,
          s.total,
          s.verdict,
          s.red_flags_json,
          s.reasoning,
          s.scored_at
        from scores s
        left join jobs_cleaned c on c.job_id = s.job_id
        left join jobs j on j.job_id = s.job_id
        left join company_enriched ce on ce.company_name_norm = c.company_name_norm
        where 1 = 1
        """
        params: list[str] = []
        if verdict:
            sql += " and s.verdict = ?"
            params.append(verdict)
        if detail_status:
            sql += " and j.detail_status = ?"
            params.append(detail_status)
        if keyword:
            sql += " and c.keyword = ?"
            params.append(keyword)
        sql += """
        order by
          s.total desc,
          s.scored_at desc
        limit 300
        """
        return self.fetch_all(sql, tuple(params))

def make_handler(data: DashboardData):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, body: str, status: int = 200) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/":
                    self._html(HTML_PAGE)
                    return
                if parsed.path == "/scores":
                    self._html(SCORES_PAGE)
                    return
                if parsed.path == "/api/summary":
                    self._json(data.summary())
                    return
                if parsed.path == "/api/detail-status":
                    self._json(data.detail_status())
                    return
                if parsed.path == "/api/failures":
                    self._json(data.failures())
                    return
                if parsed.path == "/api/failed-jobs":
                    self._json(data.failed_jobs())
                    return
                if parsed.path == "/api/jobs":
                    self._json(
                        data.jobs(
                            status=(query.get("status") or [""])[0],
                            keyword=(query.get("keyword") or [""])[0],
                        )
                    )
                    return
                if parsed.path == "/api/score-summary":
                    self._json(data.score_summary())
                    return
                if parsed.path == "/api/score-results":
                    self._json(
                        data.score_results(
                            verdict=(query.get("verdict") or [""])[0],
                            detail_status=(query.get("detail_status") or [""])[0],
                            keyword=(query.get("keyword") or [""])[0],
                        )
                    )
                    return
                self._json({"error": "not found"}, status=404)
            except sqlite3.OperationalError as exc:
                self._json({"error": f"database error: {exc}"}, status=500)
            except Exception as exc:
                self._json({"error": f"server error: {exc}"}, status=500)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def main() -> None:
    args = parse_args()
    data = DashboardData(Path(args.db))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(data))
    print(f"[dashboard] serving http://{args.host}:{args.port}")
    print(f"[dashboard] database={Path(args.db).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
