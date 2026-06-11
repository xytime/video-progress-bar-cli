"""从 Safari 导出 YouTube Cookie 到静态文件，避免 yt-dlp 每次读取 Safari Cookie 触发 YouTube 轮转。

# Modification History
| Version | Date       | Author          | Description |
|---------|------------|-----------------|-------------|
| 1.0.0   | 2026-06-11 | Claude_Opus_4.8 | 初始创建 |

用法：
    .venv/bin/python scripts/refresh_yt_cookies.py

执行后将 Safari 中的 YouTube Cookie 导出到 output/youtube_cookies.txt（Netscape 格式）。
之后在 .env 中设置：
    YOUTUBE_COOKIES_FILE=output/youtube_cookies.txt
即可让 pipeline 和 monitor 使用静态文件，不再每次读取 Safari，避免 Cookie 轮转。
"""
import sys
import subprocess
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_YTDLP = str(_ROOT / ".venv" / "bin" / "yt-dlp")
_OUT_DIR = _ROOT / "output"
_COOKIES_FILE = _OUT_DIR / "youtube_cookies.txt"

_OUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"正在从 Safari 导出 YouTube Cookie → {_COOKIES_FILE}")
print("请确保 Safari 已打开且已登录 YouTube...\n")

# 用一个轻量请求（YouTube 首页，--print 仅打印元数据，不实际下载）
# --cookies FILE 会在请求完成后把更新后的 Cookie 写入文件
result = subprocess.run(
    [
        _YTDLP,
        "--cookies-from-browser", "safari",
        "--cookies", str(_COOKIES_FILE),
        "--print", "%(webpage_url)s",
        "--playlist-end", "1",
        "--no-warnings",
        "https://www.youtube.com/feed/trending",
    ],
    capture_output=True,
    text=True,
    cwd=str(_ROOT),
)

if _COOKIES_FILE.exists() and _COOKIES_FILE.stat().st_size > 100:
    size_kb = _COOKIES_FILE.stat().st_size // 1024
    print(f"✓ Cookie 已导出：{_COOKIES_FILE}（{size_kb} KB）")
    print()
    print("下一步：在 .env 中添加以下行，然后重启 pipeline：")
    print(f"  YOUTUBE_COOKIES_FILE=output/youtube_cookies.txt")
else:
    print(f"✗ 导出失败，文件不存在或为空")
    if result.stderr:
        print(f"错误信息：{result.stderr.strip()[:300]}")
    sys.exit(1)
