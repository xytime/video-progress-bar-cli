"""频道 URL 验证与批准；同一有限操作在维护关闭前准入并持有至回写结束。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | vpanel 添加频道接入维护门面，去除 shell 内联数据插值 |
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config.settings import settings
from video_processing.core.maintenance_child import single_script
from video_processing.db.database import PipelineDB


@single_script
def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    args = parser.parse_args()
    result = subprocess.run([
        settings.ytdlp_path, "--flat-playlist", "--playlist-items", "1", "--no-warnings",
        "--print", "playlist:%(channel_id,id)s|%(channel,title)s",
        "--print", "%(playlist_channel_id,channel_id,uploader_id)s|%(playlist_channel,channel,uploader,playlist_title)s",
        *settings.get_yt_cookie_args(), args.url,
    ], capture_output=True, text=True, timeout=60)
    rows = [line.split("|", 1) for line in result.stdout.splitlines() if "|" in line]
    row = next((value for value in rows if re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", value[0])), None)
    if result.returncode or not row:
        print("频道验证失败；没有写入白名单。")
        return 2
    db = PipelineDB()
    ok = db.add_channel(row[0], row[1], status="APPROVED", reason="Added via vpanel job add-channel")
    print("已添加并批准" if ok else "已存在，记录已更新")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
