# -*- coding: utf-8 -*-
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "douyin" / "creator_api_20260515_214108_120_videos.json"
OUTPUT = ROOT / "data" / "douyin" / "creator_四川文旅_20260515_214108_120_clean.json"


def format_time(value):
    if not value:
        return ""
    return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")


def main():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    videos = source.get("videos", [])

    author = {}
    if videos:
        raw_author = videos[0].get("raw", {}).get("author", {}) or {}
        author = {
            "昵称": raw_author.get("nickname") or videos[0].get("author_nickname", ""),
            "抖音号": raw_author.get("unique_id", ""),
            "简介": raw_author.get("signature", ""),
            "IP属地": raw_author.get("ip_location", ""),
            "粉丝数": raw_author.get("follower_count", ""),
            "关注数": raw_author.get("following_count", ""),
            "获赞总数": raw_author.get("total_favorited", ""),
            "作品数": raw_author.get("aweme_count", ""),
            "user_id": raw_author.get("uid", ""),
            "sec_uid": source.get("sec_user_id", ""),
            "主页链接": source.get("source_url", ""),
        }

    clean = {
        "爬取时间": source.get("crawl_time", ""),
        "爬取模式": "creator",
        "作者": author,
        "视频列表": [
            {
                "标题": item.get("desc", ""),
                "发布时间": format_time(item.get("create_time")),
                "视频链接": item.get("video_url", ""),
                "点赞数": item.get("digg_count", 0),
                "收藏数": item.get("collect_count", 0),
                "评论数": item.get("comment_count", 0),
                "分享数": item.get("share_count", 0),
            }
            for item in videos
        ],
    }

    OUTPUT.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)
    print(f"videos={len(clean['视频列表'])}")


if __name__ == "__main__":
    main()
