"""从浏览器导出 YouTube Cookie 到静态文件，避免 yt-dlp 每次读取浏览器 Cookie 触发 YouTube 轮转。

默认从 **Chrome** 导出（2026-06-25 起）：实测本机 Safari 未登录 YouTube，导出的只有匿名
cookie（VISITOR_INFO1_LIVE/PREF/YSC…），缺少 SID/SAPISID/LOGIN_INFO 等登录态 cookie，
导致 yt-dlp 以游客身份访问 → 触发「Sign in to confirm you're not a bot」风控。Chrome 已
登录，含完整登录态 cookie。可用第一个命令行参数覆盖浏览器（safari/chrome/firefox/edge…）。

导出后会**校验登录态 cookie 是否存在**，缺失则报错退出（杜绝静默导出匿名 cookie 的陷阱）。

# Modification History
| Version | Date       | Author          | Description |
|---------|------------|-----------------|-------------|
| 1.0.0   | 2026-06-11 | Claude_Opus_4.8 | 初始创建（从 Safari 导出） |
| 2.0.0   | 2026-06-25 | Claude_Opus_4.8 | 默认源改为 Chrome（Safari 未登录→只导出匿名 cookie→触发 bot 风控）；浏览器可经 argv[1] 覆盖；新增导出后登录态 cookie 校验，缺失即报错退出 |

用法：
    .venv/bin/python scripts/refresh_yt_cookies.py            # 默认从 Chrome 导出
    .venv/bin/python scripts/refresh_yt_cookies.py safari     # 指定浏览器

执行后将浏览器中的 YouTube Cookie 导出到 output/youtube_cookies.txt（Netscape 格式）。
之后在 .env 中设置：
    YOUTUBE_COOKIES_FILE=output/youtube_cookies.txt
即可让 pipeline 和 monitor 使用静态文件，不再每次读取浏览器，避免 Cookie 轮转。
"""
import sys
import subprocess
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_YTDLP = str(_ROOT / ".venv" / "bin" / "yt-dlp")
_OUT_DIR = _ROOT / "output"
_COOKIES_FILE = _OUT_DIR / "youtube_cookies.txt"

# 登录态 cookie：缺少其中任意核心项即说明浏览器未登录 YouTube，导出无意义。
_AUTH_COOKIES = {"SID", "SAPISID", "__Secure-3PSID", "LOGIN_INFO",
                 "HSID", "SSID", "APISID", "__Secure-1PSID"}

_BROWSER = sys.argv[1] if len(sys.argv) > 1 else "chrome"

_OUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"正在从 {_BROWSER} 导出 YouTube Cookie → {_COOKIES_FILE}")
print(f"请确保 {_BROWSER} 已登录 YouTube...\n")

# 用一个轻量请求（YouTube 首页，--print 仅打印元数据，不实际下载）
# --cookies FILE 会在请求完成后把更新后的 Cookie 写入文件
result = subprocess.run(
    [
        _YTDLP,
        "--cookies-from-browser", _BROWSER,
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

if not (_COOKIES_FILE.exists() and _COOKIES_FILE.stat().st_size > 100):
    print("✗ 导出失败，文件不存在或为空")
    if result.stderr:
        print(f"错误信息：{result.stderr.strip()[:300]}")
    sys.exit(1)

# 校验登录态 cookie 是否存在（避免静默导出匿名 cookie，那会让 yt-dlp 触发 bot 风控）
found = set()
for line in _COOKIES_FILE.read_text(errors="ignore").splitlines():
    if line.startswith("#") or not line.strip():
        continue
    parts = line.split("\t")
    if len(parts) >= 7 and parts[5] in _AUTH_COOKIES:
        found.add(parts[5])

if not found:
    print(f"✗ 导出的 Cookie 中【没有登录态 cookie】（{', '.join(sorted(_AUTH_COOKIES))} 全部缺失）。")
    print(f"  说明 {_BROWSER} 未登录 YouTube，导出的是匿名 cookie，会触发「Sign in to confirm you're not a bot」。")
    print(f"  请在 {_BROWSER} 中登录 YouTube 后重试，或换浏览器：")
    print(f"    .venv/bin/python scripts/refresh_yt_cookies.py chrome")
    sys.exit(2)

size_kb = _COOKIES_FILE.stat().st_size // 1024
print(f"✓ Cookie 已导出：{_COOKIES_FILE}（{size_kb} KB）")
print(f"✓ 登录态 cookie 校验通过：{', '.join(sorted(found))}")
print()
print("下一步：确认 .env 中已有以下行，然后重启 pipeline：")
print("  YOUTUBE_COOKIES_FILE=output/youtube_cookies.txt")
