import sys
import os
import subprocess
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src"))
from video_processing.db import PipelineDB

db = PipelineDB()

with db.get_connection() as conn:
    cursor = conn.execute("SELECT youtube_id FROM processed_videos WHERE duration_sec IS NULL")
    ids = [r['youtube_id'] for r in cursor.fetchall()]

print(f"Found {len(ids)} videos to backfill.")

for yid in ids:
    url = f"https://www.youtube.com/watch?v={yid}"
    cmd = [
        "yt-dlp",
        "--print", "%(duration)s|%(view_count)s|%(like_count)s|%(upload_date)s",
        "--no-playlist",
        "--no-warnings",
        "--cookies-from-browser", "safari",
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = res.stdout.strip().split("\n")[0]
        if out and "|" in out:
            parts = out.split("|")
            def _int(v):
                try: return int(v)
                except: return None
            duration_sec = _int(parts[0]) if len(parts) > 0 else None
            view_count = _int(parts[1]) if len(parts) > 1 else None
            like_count = _int(parts[2]) if len(parts) > 2 else None
            upload_date = parts[3].strip() if len(parts) > 3 and parts[3].strip() not in ("NA", "") else None
            
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE processed_videos SET duration_sec=?, view_count=?, like_count=?, upload_date=? WHERE youtube_id=?",
                    (duration_sec, view_count, like_count, upload_date, yid)
                )
                conn.commit()
            print(f"Updated {yid}: duration={duration_sec}, views={view_count}, likes={like_count}, date={upload_date}")
        else:
            print(f"Failed to fetch {yid}")
    except Exception as e:
        print(f"Error on {yid}: {e}")
