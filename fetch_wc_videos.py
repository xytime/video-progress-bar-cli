"""
Fetch World Cup 2026 video metadata from YouTube.
Uses yt-dlp with browser cookies to get view counts, likes, and upload dates.

Modification History:
| Date       | Author                              | Change Description                |
|------------|-------------------------------------|-----------------------------------|
| 2026-06-15 | Claude_Opus_4.6_Thinking_planning   | Initial creation                  |
"""

import json
import subprocess
import sys


def fetch_videos_via_ytdlp():
    """Use yt-dlp CLI to fetch video metadata with cookies."""
    
    # Video IDs from our earlier search
    video_ids = [
        "Ky4KeKGNtjw",  # Netherlands vs Japan 2-2
        "NVp8z0s-MSM",  # Germany 7-1 Curacao
        "zCNXtWLuF0g",  # Sweden vs Tunisia
        "TcCufmPCsu4",  # Haiti 0-1 Scotland
        "t7tQRp1emtk",  # Brazil vs Morocco
        "73AbKWJaeMA",  # Brazil vs Morocco 1-1
        "1hDLe88KH3M",  # Japan 2-2 Netherlands drama
        "Iu4MT0RZcIk",  # Japan vs Netherlands
        "-npdYIop38M",  # Japan vs Netherlands
        "AHO9V_bxd2U",  # Germany vs Curacao goals
        "3zaxs5SAEDI",  # Haiti vs Scotland full
        "QxmtSES3frI",  # Haiti vs Scotland 0-1
        "Fhta-D1tqEg",  # Isak Goal
        "MhQiCMG5XsY",  # Rekik Goal
        "ohzSCcQadPY",  # Ayari Goal
        "RsZmwx86BYE",  # Isak Goal + Gyokeres assist
        "jF8E81L2jaQ",  # Germany 7-1 shorts
        "eXiRmWTC10I",  # Opening ceremony
        "szSsFdsKm5s",  # Zlatan + IShowSpeed
        "bHAkyoSjAME",  # World Cup crazy shorts
        "PecAg4ZkA6g",  # Goals everyone talking about
        "23Ra49ERvGM",  # Mexico vs South Africa
        "kyfqew-yqBw",  # Sweden first goal
    ]

    results = []
    
    for vid in video_ids:
        url = f"https://www.youtube.com/watch?v={vid}"
        cmd = [
            "yt-dlp",
            "--cookies-from-browser", "chrome",
            "--no-download",
            "--no-warnings",
            "--print", json.dumps({
                "id": "%(id)s",
                "title": "%(title)s",
                "view_count": "%(view_count)s",
                "like_count": "%(like_count)s",
                "duration_string": "%(duration_string)s",
                "upload_date": "%(upload_date>%Y-%m-%d)s",
                "channel": "%(channel)s",
            }),
            url,
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                results.append(data)
                
                # Calculate like ratio
                views = int(data.get("view_count", 0) or 0)
                likes = int(data.get("like_count", 0) or 0)
                like_ratio = f"{(likes/views*100):.1f}%" if views > 0 else "N/A"
                
                print(f"✅ {data['title'][:60]}")
                print(f"   👁 {views:,} views | 👍 {likes:,} likes ({like_ratio}) | 📅 {data['upload_date']} | 📺 {data['channel']}")
                print()
            else:
                print(f"❌ Failed: {vid} - {result.stderr[:100]}")
        except Exception as e:
            print(f"❌ Error: {vid} - {e}")
    
    return results


def format_as_table(results):
    """Format results as a markdown table."""
    print("\n" + "=" * 120)
    print("MARKDOWN TABLE OUTPUT")
    print("=" * 120)
    
    print("| # | 标题 | 时长 | 👁 观看数 | 👍 点赞 | 点赞率 | 📅 发布日期 | 📺 频道 |")
    print("|---|------|------|----------|--------|--------|------------|--------|")
    
    # Sort by view count descending
    sorted_results = sorted(results, key=lambda x: int(x.get("view_count", 0) or 0), reverse=True)
    
    for i, r in enumerate(sorted_results, 1):
        views = int(r.get("view_count", 0) or 0)
        likes = int(r.get("like_count", 0) or 0)
        like_ratio = f"{(likes/views*100):.1f}%" if views > 0 else "N/A"
        
        # Human readable view count
        if views >= 1_000_000:
            views_str = f"{views/1_000_000:.1f}M"
        elif views >= 1_000:
            views_str = f"{views/1_000:.1f}K"
        else:
            views_str = str(views)
        
        if likes >= 1_000:
            likes_str = f"{likes/1_000:.1f}K"
        else:
            likes_str = str(likes)
            
        title = r.get("title", "")[:65]
        dur = r.get("duration_string", "")
        date = r.get("upload_date", "")
        channel = r.get("channel", "")[:20]
        vid = r.get("id", "")
        
        print(f"| {i} | [{title}](https://youtube.com/watch?v={vid}) | {dur} | {views_str} | {likes_str} | {like_ratio} | {date} | {channel} |")


if __name__ == "__main__":
    print("🏆 Fetching World Cup 2026 Video Stats...\n")
    results = fetch_videos_via_ytdlp()
    if results:
        format_as_table(results)
    else:
        print("No results obtained. YouTube may be blocking requests.")
        print("Try: yt-dlp --cookies-from-browser chrome ...")
