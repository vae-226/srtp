# -*- coding: utf-8 -*-
import asyncio
import json
import re
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

from scrape_creator_api_json import scrape as scrape_creator


ROOT = Path(__file__).resolve().parent
DOUYIN_SIGN_JS = (ROOT / "libs" / "douyin.js").read_text(encoding="utf-8-sig")
CRAWL_LOCK = threading.Lock()


def parse_video_id(url_or_id: str) -> str:
    value = url_or_id.strip()
    if value.isdigit():
        return value
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    modal_id = (query.get("modal_id") or [""])[0]
    if modal_id:
        return modal_id
    match = re.search(r"/video/(\d+)", value)
    if match:
        return match.group(1)
    raise ValueError("无法从输入中识别视频 ID；请使用 /video/ 链接、带 modal_id 的链接或纯数字 ID。")


def detect_mode(url_or_id: str, requested_mode: str) -> str:
    if requested_mode in {"creator", "detail"}:
        return requested_mode
    value = url_or_id.strip()
    if "/user/" in value and "modal_id=" not in value:
        return "creator"
    return "detail"


def normalize_detail_aweme(aweme: Dict[str, Any]) -> Dict[str, Any]:
    stats = aweme.get("statistics") or {}
    author = aweme.get("author") or {}
    aweme_id = aweme.get("aweme_id", "")
    return {
        "aweme_id": aweme_id,
        "desc": aweme.get("desc", ""),
        "create_time": aweme.get("create_time"),
        "video_url": f"https://www.douyin.com/video/{aweme_id}",
        "digg_count": stats.get("digg_count"),
        "comment_count": stats.get("comment_count"),
        "collect_count": stats.get("collect_count"),
        "share_count": stats.get("share_count"),
        "author_nickname": author.get("nickname"),
        "author_unique_id": author.get("unique_id") or author.get("short_id"),
        "raw": aweme,
    }


async def fetch_detail(page, aweme_id: str) -> Dict[str, Any]:
    result = await page.evaluate(
        """async ([signSource, awemeId]) => {
            if (!window.__douyinSignLoaded) {
                const script = document.createElement("script");
                script.textContent = signSource;
                document.documentElement.appendChild(script);
                script.remove();
                window.__douyinSignLoaded = true;
            }

            const ua = navigator.userAgent;
            const local = window.localStorage || {};
            const params = {
                aweme_id: awemeId,
                device_platform: "webapp",
                aid: "6383",
                channel: "channel_pc_web",
                version_code: "190600",
                version_name: "19.6.0",
                update_version_code: "170400",
                pc_client_type: "1",
                cookie_enabled: "true",
                browser_language: navigator.language || "zh-CN",
                browser_platform: navigator.platform || "Win32",
                browser_name: "Chrome",
                browser_version: "125.0.0.0",
                browser_online: String(navigator.onLine),
                engine_name: "Blink",
                os_name: "Windows",
                os_version: "10",
                cpu_core_num: String(navigator.hardwareConcurrency || 8),
                device_memory: String(navigator.deviceMemory || 8),
                engine_version: "109.0",
                platform: "PC",
                screen_width: String(screen.width || 1440),
                screen_height: String(screen.height || 1200),
                effective_type: "4g",
                round_trip_time: "50",
                webid: String(Date.now()).slice(0, 19),
                msToken: local.xmst || ""
            };
            const query = new URLSearchParams(params).toString();
            params.a_bogus = window.sign_datail(query, ua);
            const url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?" + new URLSearchParams(params).toString();
            const resp = await fetch(url, {
                method: "GET",
                credentials: "include",
                headers: {
                    "accept": "application/json, text/plain, */*",
                    "referer": location.href
                }
            });
            const text = await resp.text();
            return {status: resp.status, text};
        }""",
        [DOUYIN_SIGN_JS, aweme_id],
    )
    if result["status"] != 200 or not result["text"].strip():
        raise RuntimeError(f"视频详情接口返回异常: HTTP {result['status']}")
    data = json.loads(result["text"])
    aweme = data.get("aweme_detail") or {}
    if not aweme:
        raise RuntimeError("没有拿到视频详情，可能链接失效、未登录或被风控。")
    return normalize_detail_aweme(aweme)


async def scrape_detail(url_or_id: str, headless: bool) -> Dict[str, Any]:
    root = Path.cwd()
    user_data_dir = root / "browser_data" / "dy_user_data_dir"
    source_url = url_or_id.strip()
    initial_url = source_url if source_url.startswith("http") else "https://www.douyin.com"

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel="msedge",
            headless=headless,
            viewport={"width": 1440, "height": 1200},
            accept_downloads=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(initial_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        final_url = page.url
        aweme_id = parse_video_id(final_url if "v.douyin.com" in source_url else source_url)
        video = await fetch_detail(page, aweme_id)
        await context.close()

    return {
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "crawl_mode": "detail_api_browser_fetch",
        "source_url": source_url,
        "actual_count": 1,
        "videos": [video],
    }


def compact_for_web(data: Dict[str, Any]) -> Dict[str, Any]:
    videos = data.get("videos", [])
    rows = []
    for item in videos:
        rows.append(
            {
                "aweme_id": item.get("aweme_id", ""),
                "标题": item.get("desc", ""),
                "作者": item.get("author_nickname", ""),
                "发布时间": format_time(item.get("create_time")),
                "点赞": item.get("digg_count", 0),
                "评论": item.get("comment_count", 0),
                "收藏": item.get("collect_count", 0),
                "分享": item.get("share_count", 0),
                "链接": item.get("video_url", ""),
            }
        )
    return {
        "crawl_time": data.get("crawl_time", ""),
        "crawl_mode": data.get("crawl_mode", ""),
        "source_url": data.get("source_url", ""),
        "sec_user_id": data.get("sec_user_id", ""),
        "target_count": data.get("target_count", ""),
        "actual_count": data.get("actual_count", len(rows)),
        "rows": rows,
    }


def format_time(value: Any) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def write_output(data: Dict[str, Any], mode: str) -> str:
    out_dir = ROOT / "data" / "douyin" / "web"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"{mode}_{timestamp}_{data.get('actual_count', 0)}.json"
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out_file)


async def run_crawl(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ValueError("请输入抖音主页链接、视频链接或视频 ID。")
    mode = detect_mode(url, str(payload.get("mode") or "auto"))
    count = int(payload.get("count") or 20)
    count = max(1, min(count, 200))
    headless = bool(payload.get("headless", True))

    if mode == "creator":
        raw = await scrape_creator(url, count=count, headless=headless)
    else:
        raw = await scrape_detail(url, headless=headless)
    output_file = write_output(raw, mode)
    return {"mode": mode, "output_file": output_file, "summary": compact_for_web(raw), "raw": raw}


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Douyin Crawler Console</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #e83e6b;
      --accent-dark: #c92f58;
      --chip: #eef2f7;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      padding: 24px 32px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 14px; }
    main { max-width: 1280px; margin: 0 auto; padding: 24px; }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) 150px 120px 132px;
      gap: 12px;
      align-items: end;
      padding: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }
    input, select, button {
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 12px;
      font-size: 14px;
      background: #fff;
      color: var(--text);
    }
    button {
      border: 0;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover { background: var(--accent-dark); }
    button:disabled { opacity: .6; cursor: wait; }
    .status {
      margin: 14px 0;
      min-height: 22px;
      color: var(--muted);
      font-size: 14px;
    }
    .summary {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }
    .chip {
      padding: 7px 10px;
      border-radius: 999px;
      background: var(--chip);
      color: #344054;
      font-size: 13px;
    }
    .grid {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
    th { background: #f2f4f7; color: #475467; font-weight: 700; white-space: nowrap; }
    td.title { min-width: 320px; line-height: 1.45; }
    a { color: #175cd3; text-decoration: none; }
    a:hover { text-decoration: underline; }
    details {
      margin-top: 16px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    pre {
      overflow: auto;
      max-height: 520px;
      padding: 12px;
      background: #101828;
      color: #e6edf3;
      border-radius: 6px;
      font-size: 12px;
    }
    @media (max-width: 860px) {
      header { padding: 18px; }
      main { padding: 16px; }
      .toolbar { grid-template-columns: 1fr; }
      .grid { overflow-x: auto; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Douyin Crawler Console</h1>
    <div class="sub">输入主页链接抓 creator，输入视频链接或 ID 抓 detail；结果会同时保存为 JSON。</div>
  </header>
  <main>
    <form class="toolbar" id="crawlForm">
      <div>
        <label for="url">抖音链接或 ID</label>
        <input id="url" name="url" placeholder="https://www.douyin.com/user/... 或 https://www.douyin.com/video/..." required />
      </div>
      <div>
        <label for="mode">模式</label>
        <select id="mode" name="mode">
          <option value="auto">自动</option>
          <option value="creator">creator</option>
          <option value="detail">detail</option>
        </select>
      </div>
      <div>
        <label for="count">主页数量</label>
        <input id="count" name="count" type="number" min="1" max="200" value="20" />
      </div>
      <button id="submitBtn" type="submit">开始爬取</button>
    </form>
    <div class="status" id="status"></div>
    <section class="summary" id="summary"></section>
    <section class="grid" id="tableWrap" hidden>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>标题</th><th>作者</th><th>发布时间</th><th>点赞</th><th>评论</th><th>收藏</th><th>分享</th><th>链接</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </section>
    <details id="rawBox" hidden>
      <summary>原始 JSON</summary>
      <pre id="rawJson"></pre>
    </details>
  </main>
  <script>
    const form = document.getElementById('crawlForm');
    const statusEl = document.getElementById('status');
    const summaryEl = document.getElementById('summary');
    const rowsEl = document.getElementById('rows');
    const tableWrap = document.getElementById('tableWrap');
    const rawBox = document.getElementById('rawBox');
    const rawJson = document.getElementById('rawJson');
    const submitBtn = document.getElementById('submitBtn');

    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      submitBtn.disabled = true;
      statusEl.textContent = '正在爬取，浏览器会在后台工作。抖音偶尔有点慢，先让它跑完。';
      summaryEl.innerHTML = '';
      rowsEl.innerHTML = '';
      tableWrap.hidden = true;
      rawBox.hidden = true;

      const payload = {
        url: form.url.value.trim(),
        mode: form.mode.value,
        count: Number(form.count.value || 20),
        headless: true
      };

      try {
        const resp = await fetch('/api/crawl', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '请求失败');

        const s = data.summary;
        statusEl.textContent = `完成，结果已保存：${data.output_file}`;
        summaryEl.innerHTML = [
          ['模式', data.mode],
          ['数量', s.actual_count],
          ['时间', s.crawl_time],
          ['sec_user_id', s.sec_user_id || '-']
        ].map(([k, v]) => `<span class="chip">${esc(k)}：${esc(v)}</span>`).join('');

        rowsEl.innerHTML = s.rows.map(row => `
          <tr>
            <td>${esc(row.aweme_id)}</td>
            <td class="title">${esc(row['标题'])}</td>
            <td>${esc(row['作者'])}</td>
            <td>${esc(row['发布时间'])}</td>
            <td>${esc(row['点赞'])}</td>
            <td>${esc(row['评论'])}</td>
            <td>${esc(row['收藏'])}</td>
            <td>${esc(row['分享'])}</td>
            <td><a href="${esc(row['链接'])}" target="_blank">打开</a></td>
          </tr>
        `).join('');
        tableWrap.hidden = false;
        rawJson.textContent = JSON.stringify(data.raw, null, 2);
        rawBox.hidden = false;
      } catch (err) {
        statusEl.textContent = `失败：${err.message}`;
      } finally {
        submitBtn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/crawl":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not CRAWL_LOCK.acquire(blocking=False):
                raise RuntimeError("已有爬取任务正在运行，请稍后再试。")
            try:
                result = asyncio.run(run_crawl(payload))
            finally:
                CRAWL_LOCK.release()
            self.send_json(result)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    print(f"Douyin crawler web app: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
