# -*- coding: utf-8 -*-
import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from playwright.async_api import async_playwright


DOUYIN_SIGN_JS = Path("libs/douyin.js").read_text(encoding="utf-8-sig")


def parse_sec_user_id(url_or_id: str) -> str:
    if not url_or_id.startswith("http"):
        return url_or_id
    match = re.search(r"/user/([^/?]+)", url_or_id)
    if not match:
        raise ValueError(f"Unable to parse sec_user_id from: {url_or_id}")
    return match.group(1)


def normalize_aweme(aweme: Dict) -> Dict:
    stats = aweme.get("statistics") or {}
    author = aweme.get("author") or {}
    return {
        "aweme_id": aweme.get("aweme_id"),
        "desc": aweme.get("desc", ""),
        "create_time": aweme.get("create_time"),
        "video_url": f"https://www.douyin.com/video/{aweme.get('aweme_id')}",
        "digg_count": stats.get("digg_count"),
        "comment_count": stats.get("comment_count"),
        "collect_count": stats.get("collect_count"),
        "share_count": stats.get("share_count"),
        "author_nickname": author.get("nickname"),
        "raw": aweme,
    }


async def fetch_page(page, sec_user_id: str, max_cursor: str) -> Dict:
    return await page.evaluate(
        """async ([signSource, secUserId, maxCursor]) => {
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
                sec_user_id: secUserId,
                count: "18",
                max_cursor: maxCursor || "",
                locate_query: "false",
                publish_video_strategy_type: "2",
                verifyFp: "verify_ma3hrt8n_q2q2HyYA_uLyO_4N6D_BLvX_E2LgoGmkA1BU",
                fp: "verify_ma3hrt8n_q2q2HyYA_uLyO_4N6D_BLvX_E2LgoGmkA1BU",
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
            const url = "https://www.douyin.com/aweme/v1/web/aweme/post/?" + new URLSearchParams(params).toString();
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
        [DOUYIN_SIGN_JS, sec_user_id, str(max_cursor or "")],
    )


async def scrape(url_or_id: str, count: int, headless: bool) -> Dict:
    sec_user_id = parse_sec_user_id(url_or_id)
    root = Path.cwd()
    user_data_dir = root / "browser_data" / "dy_user_data_dir"
    source_url = url_or_id if url_or_id.startswith("http") else f"https://www.douyin.com/user/{sec_user_id}"

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel="msedge",
            headless=headless,
            viewport={"width": 1440, "height": 1200},
            accept_downloads=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        videos: List[Dict] = []
        seen = set()
        max_cursor = ""
        has_more = 1
        raw_pages = []

        while has_more and len(videos) < count:
            result = await fetch_page(page, sec_user_id, max_cursor)
            if result["status"] != 200 or not result["text"].strip():
                raw_pages.append({"status": result["status"], "text": result["text"][:500]})
                break
            data = json.loads(result["text"])
            raw_pages.append({
                "status": result["status"],
                "has_more": data.get("has_more"),
                "max_cursor": data.get("max_cursor"),
                "aweme_count": len(data.get("aweme_list") or []),
            })
            for aweme in data.get("aweme_list") or []:
                aweme_id = aweme.get("aweme_id")
                if aweme_id and aweme_id not in seen:
                    seen.add(aweme_id)
                    videos.append(normalize_aweme(aweme))
            has_more = data.get("has_more", 0)
            max_cursor = data.get("max_cursor") or ""
            await page.wait_for_timeout(1500)

        await context.close()

    return {
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "crawl_mode": "creator_api_browser_fetch",
        "source_url": source_url,
        "sec_user_id": sec_user_id,
        "target_count": count,
        "actual_count": len(videos[:count]),
        "request_pages": raw_pages,
        "videos": videos[:count],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url_or_id")
    parser.add_argument("-n", "--count", type=int, default=120)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    data = asyncio.run(scrape(args.url_or_id, args.count, args.headless))
    out_dir = Path.cwd() / "data" / "douyin"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"creator_api_{timestamp}_{data['actual_count']}_videos.json"
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_file))
    print(f"actual_count={data['actual_count']}")


if __name__ == "__main__":
    main()
