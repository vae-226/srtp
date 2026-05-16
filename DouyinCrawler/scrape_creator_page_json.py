# -*- coding: utf-8 -*-
import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from playwright.async_api import async_playwright


VIDEO_PATTERN = re.compile(r"/video/(\d+)")


def dedupe(items: List[Dict]) -> List[Dict]:
    seen = set()
    result = []
    for item in items:
        video_id = item.get("video_id")
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        result.append(item)
    return result


async def collect_visible_videos(page) -> List[Dict]:
    rows = await page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/video/"]')).map((a) => {
            const href = new URL(a.getAttribute('href'), location.href).href.split('?')[0];
            const match = href.match(/\\/video\\/(\\d+)/);
            const img = a.querySelector('img');
            const textParts = [
                a.innerText,
                a.getAttribute('aria-label'),
                a.getAttribute('title'),
                img && img.getAttribute('alt')
            ].filter(Boolean).map((v) => String(v).trim()).filter(Boolean);
            const rect = a.getBoundingClientRect();
            return {
                video_id: match ? match[1] : "",
                video_url: href,
                title: textParts[0] || "",
                x: Math.round(rect.x),
                y: Math.round(rect.y)
            };
        })"""
    )
    return rows


async def scrape_creator(url: str, count: int, headless: bool) -> Dict:
    root = Path.cwd()
    user_data_dir = root / "browser_data" / "dy_user_data_dir"
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel="msedge",
            headless=headless,
            viewport={"width": 1440, "height": 1200},
            accept_downloads=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        all_items: List[Dict] = []
        stable_rounds = 0
        last_count = 0

        for _ in range(120):
            all_items = dedupe(all_items + await collect_visible_videos(page))
            if len(all_items) >= count:
                break

            if len(all_items) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = len(all_items)
            if stable_rounds >= 12:
                break

            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(1200)

        creator_name = ""
        try:
            creator_name = (await page.locator("h1").first.inner_text(timeout=2000)).strip()
        except Exception:
            pass

        await context.close()

    return {
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "crawl_mode": "creator_page_browser",
        "source_url": url,
        "target_count": count,
        "actual_count": len(all_items[:count]),
        "creator": {"nickname": creator_name},
        "videos": all_items[:count],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("-n", "--count", type=int, default=120)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    data = asyncio.run(scrape_creator(args.url, args.count, args.headless))
    out_dir = Path.cwd() / "data" / "douyin"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"creator_page_{timestamp}_{data['actual_count']}_videos.json"
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_file))
    print(f"actual_count={data['actual_count']}")


if __name__ == "__main__":
    main()
