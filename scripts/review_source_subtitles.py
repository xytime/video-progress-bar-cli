"""在选题入库前只读审查 YouTube 英文源字幕。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-14 | Codex | 新增选题审核前字幕 fail-closed 命令。 |
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.utils.source_subtitle_screening import screen_youtube_source_subtitles  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="只读审查选题候选的英文源字幕")
    parser.add_argument("url", help="YouTube 视频 URL")
    args = parser.parse_args()
    try:
        screening = screen_youtube_source_subtitles(args.url)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"passed": False, "reason": f"元数据读取失败：{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps(screening.to_dict(), ensure_ascii=False))
    return 0 if screening.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
