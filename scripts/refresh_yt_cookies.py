"""安全刷新生产 YouTube Cookie，并以真实元数据请求验收。

旧脚本只检查 Cookie 名称，且直接覆盖生产文件；这会让已经失效或半写入的
Cookie 被误报为可用。此入口先在临时文件完成浏览器导出和独立探针，再原子替换。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-06-11 | Claude_Opus_4.8 | 初始创建（从 Safari 导出）。 |
| 2.0.0 | 2026-06-25 | Claude_Opus_4.8 | 默认源改为 Chrome，并拒绝匿名 Cookie。 |
| 3.0.0 | 2026-08-26 | Codex | 临时导出、真实视频探针复验与原子替换；失败保留旧生产 Cookie。 |

用法：
    .venv/bin/python scripts/refresh_yt_cookies.py            # 默认从 Chrome 安全刷新
    .venv/bin/python scripts/refresh_yt_cookies.py safari     # 指定浏览器
    .venv/bin/python scripts/refresh_yt_cookies.py --check    # 只验收当前生产 Cookie
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from config.settings import settings
from video_processing.utils.youtube_auth import (
    refresh_youtube_cookie_file,
    validate_youtube_cookie_file,
)


def main(argv: list[str]) -> int:
    """运行受控刷新或只读验证，不泄露 Cookie 内容。"""
    cookie_file = Path(settings.youtube_cookies_file or ROOT / "output" / "youtube_cookies.txt")
    probe_url = settings.youtube_auth_probe_url
    if argv and argv[0] == "--check":
        result = validate_youtube_cookie_file(
            cookie_file,
            probe_url=probe_url,
            ytdlp_path=settings.ytdlp_path,
        )
    else:
        browser = argv[0] if argv else settings.youtube_cookie_browser
        result = refresh_youtube_cookie_file(
            cookie_file,
            browser=browser,
            probe_url=probe_url,
            ytdlp_path=settings.ytdlp_path,
        )
    print(f"YouTube Cookie {result.code}")
    if result.detail:
        print(result.detail)
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
