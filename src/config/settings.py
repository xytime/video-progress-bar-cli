"""配置管理模块 — 全局唯一配置真相来源 (Single Source of Truth)

所有环境变量必须在此处声明。
禁止在业务模块中直接调用 os.getenv / os.environ。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-20 | Gemini_3.1_Pro_High_planning | 初始创建 Settings 类 |
| 2.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 重构为 pydantic-settings BaseSettings，收口全部环境变量，消灭散落的 os.getenv |
| 2.1.0 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | v7.0 Feature Flags：新功能开关，默认全部关闭，保护生产环境稳定性 |
| 2.2.0 | 2026-05-28 | Gemini_2.5_Pro_planning | 新增 dashscope_api_key，支持阿里云百炼 CosyVoice TTS 集成 |
| 2.3.0 | 2026-06-01 | Gemini_2.5_Flash_planning | 新增 enable_channel_policy_filter：频道内容策略层独立开关 |
| 2.4.0 | 2026-06-07 | Gemini_3.5_Flash_High_planning | 新增 enable_dynamic_keywords 与 hn_top_n 配置，支持动态热词注入 |
| 2.5.0 | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | [BugFix] env_file 改为绝对路径，修复 cwd != project_root 时 .env 无法加载导致 Feature Flag 全部回退的根因；新增 get_active_proxies() 动态检测系统代理连通性 |
| 2.6.0 | 2026-06-08 | Gemini_3.5_Flash_planning           | 新增 wechat_headless 配置项及 active_telegram_chat_id 动态计算属性 |
| 2.7.0 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 新增 wechat_keepalive_* 看门狗配置项，支持定期刷新 Session 防止闲置掉线 |
| 2.8.0 | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | 新增 aliyun_mt_access_key_id/secret，支持阿里云机器翻译通用版作为 Gemini 限流时的二级 fallback |
| 2.9.0 | 2026-06-09 | Claude_Sonnet_4.6_Thinking_planning | 新增 Clash Mi API 配置及 clash_switch_node() 上下文管理器：下载前自动切到日本节点，完成后还原。Clash Mi Network Extension 架构下唯一可行的进程级优化方案 |
| 3.0.0 | 2026-06-11 | Claude_Opus_4.8                     | 新增 youtube_cookies_file：Cookie 文件路径，优先级高于 --cookies-from-browser safari；避免 YouTube 频繁轮转 Cookie |
"""
import json
import socket
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# [Claude_Sonnet_4.6_Thinking_planning] 项目根目录的绝对路径，在模块加载时确定
# 用于 env_file 绝对路径，避免 cwd 不同时 .env 加载失败的根因
_PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """
    应用全局配置。
    字段来源优先级：环境变量 > .env 文件 > 字段默认值。
    """

    model_config = SettingsConfigDict(
        # [Claude_Sonnet_4.6_Thinking_planning] v2.5.0: 使用绝对路径
        # 修复根因：相对路径 ".env" 依赖于进程的 cwd。当 _run_pipeline_manager()
        # 以 cwd=src 启动子进程时，Python 在 src/.env 找不到文件，导致所有
        # Feature Flags 回退为 False（enable_sigterm_kill=False 等），API 密钥全失效。
        # 使用绝对路径后，无论从哪个工作目录启动均能正确加载项目根的 .env。
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,   # 环境变量大小写不敏感
        extra="ignore",         # 忽略 .env 中未声明的多余字段
    )

    # -------------------------------------------------------------------------
    # 运行时环境变量 (Runtime Env Vars) — 从 .env 或系统 environment 注入
    # -------------------------------------------------------------------------

    # 日志级别
    log_level: str = "INFO"

    # FFmpeg 可执行文件路径（留空则使用系统 PATH 中的默认值）
    ffmpeg_path: Optional[str] = None

    # Telegram 通知 Bot 配置
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_admin_ids: Optional[str] = None  # [Gemini_3.5_Flash_planning] 管理员 ID 列表

    # 微信上传是否使用无头模式，默认开启
    wechat_headless: bool = True  # [Gemini_3.5_Flash_planning]

    # [Claude_Sonnet_4.6_Thinking_planning] v2.7.0: WeChat Session 看门狗配置
    # 看门狗会定期（每 min~max 分钟随机一次）在后台静默访问微信发布页，
    # 维持 Cookie 活跃，防止长时间无发布任务时 Session 闲置过期。
    wechat_keepalive_enabled: bool = False          # 默认关闭，需在 .env 中显式设置 WECHAT_KEEPALIVE_ENABLED=true
    wechat_keepalive_min_interval: int = 50         # 最短触发间隔（分钟）
    wechat_keepalive_max_interval: int = 65         # 最长触发间隔（分钟）
    wechat_keepalive_dwell: int = 15                # 停留时长（秒），供微信记录活跃请求


    # Google Gemini API Key
    gemini_api_key: Optional[str] = None

    # 阿里云百炼 (DashScope / Model Studio) API Key — 用于 CosyVoice TTS
    # 获取地址：https://bailian.console.aliyun.com/ → API-KEY 管理
    dashscope_api_key: Optional[str] = None  # [Gemini_2.5_Pro_planning]

    # [Claude_Sonnet_4.6_Thinking_planning] v2.8.0 阿里云机器翻译通用版 AccessKey
    # 申请地址：https://www.aliyun.com/product/ai/alimt
    # 在「RAM 访问控制」创建子账号后，授权 AliyunMTFullAccess 策略，并获取 AccessKey ID 和 Secret。
    # Gemini API 触发 429 限流时，自动降级使用阿里云 MT（QPS 50，每月 100 万字符免费额度）。
    aliyun_mt_access_key_id: Optional[str] = None
    aliyun_mt_access_key_secret: Optional[str] = None

    # [Claude_Sonnet_4.6_Thinking_planning] v2.9.0: Clash Mi 下载节点切换配置
    # 架构背景：Clash Mi 使用 macOS Network Extension，系统扩展不允许动态开放任意端口，
    # 因此无法通过 listeners 实现真正的进程级隔离。唯一可行的优化方案是:
    # 下载前通过 API 将代理组切换到日本节点，完成后自动还原。
    # 影响范围：仅在实际下载期间（约 5-15 分钟）全局流量临时走日本，签出后自动还原。
    clash_api_url: str = "http://127.0.0.1:9090"   # Clash 外部控制器地址
    clash_api_secret: Optional[str] = None          # CLASH_API_SECRET=...
    clash_proxy_group: str = "🌍 国外网站"           # 要切换的代理组
    clash_download_node: Optional[str] = None       # 下载时使用的节点（None=不切换）
                                                    # 示例: CLASH_DOWNLOAD_NODE=🏯🇵 日本下载专用

    # [Claude_Opus_4.8] v3.0.0: YouTube Cookie 文件路径
    # 优先使用静态 Cookie 文件，避免 --cookies-from-browser safari 在每次调用后触发 YouTube 轮转
    # 留空("")则回退到 --cookies-from-browser safari
    # 使用 scripts/refresh_yt_cookies.py 从 Safari 导出并保存到此文件
    youtube_cookies_file: str = ""

    # -------------------------------------------------------------------------
    # v7.0 Feature Flags — 新功能灰度开关 [Claude_Sonnet_4.6_Thinking_planning]
    # 默认全部 False，保证 feature 分支代码 merge 后对生产环境零影响。
    # 验证通过后，在 .env 中逐条设置为 true 开启对应功能。
    # 开启顺序建议：blacklist → manual_score_lock → censorship → sigterm_kill
    # -------------------------------------------------------------------------

    # 黑名单墓碑防重抓（删除/打0分的视频不再被爬虫二次拉取）
    enable_blacklist_tombstone: bool = False

    # 人工评分锁（手动打分后，自动算分不覆盖）
    enable_manual_score_lock: bool = False

    # 内容安全审查引擎（双语双通道 P0/P1/P2 违禁拦截）
    enable_censorship_engine: bool = False

    # 频道内容策略过滤层（运营层，独立于违法内容拦截，默认关闭）
    # [Gemini_2.5_Flash_planning] 开启后，视频标题/文案命中「频道策略词库」时标记 FAILED + Telegram 警告。
    # 触发词由 censor_engine._CHANNEL_POLICY 定义，用户可按需调整。
    enable_channel_policy_filter: bool = False  # [Gemini_2.5_Flash_planning]

    # SIGTERM 阶梯强杀机制（删除活跃任务时优雅终止底层进程）
    enable_sigterm_kill: bool = False

    # 动态热词注入开关 [Gemini_3.5_Flash_High_planning]
    enable_dynamic_keywords: bool = False
    hn_top_n: int = 30

    # -------------------------------------------------------------------------
    # 静态配置常量 (Static Constants) — 固定值，不依赖环境
    # -------------------------------------------------------------------------

    # 视频编码默认值
    default_video_format: str = "mp4"
    default_video_codec: str = "libx264"
    default_audio_codec: str = "aac"

    # 字体路径（用于视频文字渲染）
    default_font_path: str = "/Library/Fonts/TianYingZhang.ttf"

    # 进度条字体与尺寸默认配置
    default_bar_font_size: int = 28      # 底部进度条章节标题字号
    default_title_font_size: int = 72    # 左上角大标题字号
    default_bar_height: int = 80         # 进度条高度（像素）

    # -------------------------------------------------------------------------
    # 计算型路径 (Computed Paths) — 基于项目结构自动推导，不来自环境变量
    # 注意：必须用 @computed_field 而非类属性，否则 pydantic 会尝试从环境注入
    # -------------------------------------------------------------------------

    @computed_field  # type: ignore[misc]
    @property
    def active_telegram_chat_id(self) -> Optional[str]:
        """[Gemini_3.5_Flash_planning] 获取当前活跃的 Telegram Chat ID。
        若显式配置了 telegram_chat_id 则优先使用；否则从 telegram_admin_ids 中提取第一个管理员 ID 作为 fallback。
        """
        if self.telegram_chat_id:
            return self.telegram_chat_id
        if self.telegram_admin_ids:
            return self.telegram_admin_ids.split(",")[0].strip()
        return None

    @computed_field  # type: ignore[misc]
    @property
    def project_root(self) -> Path:
        """项目根目录（settings.py 向上三级：config/ → src/ → project root）"""
        return Path(__file__).parent.parent.parent

    @computed_field  # type: ignore[misc]
    @property
    def default_output_dir(self) -> Path:
        """默认输出目录"""
        return self.project_root / "output"

    @computed_field  # type: ignore[misc]
    @property
    def log_dir(self) -> Path:
        """日志目录"""
        return self.project_root / "logs"

    # -------------------------------------------------------------------------
    # 工具方法
    # -------------------------------------------------------------------------

    def ensure_directories(self) -> None:
        """确保运行时必要的目录存在"""
        self.default_output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def get_yt_cookie_args(self) -> list[str]:
        """返回 yt-dlp 的 Cookie 参数列表。
        优先使用静态 Cookie 文件（避免每次调用触发 YouTube 轮转）；
        文件不存在或未配置时回退到 --cookies-from-browser safari。
        """
        if self.youtube_cookies_file:
            p = Path(self.youtube_cookies_file).expanduser()
            if p.exists():
                return ["--cookies", str(p)]
        return ["--cookies-from-browser", "safari"]

    def get_active_proxies(self) -> dict:
        """[Claude_Sonnet_4.6_Thinking_planning] v2.5.0: 动态检测系统代理并验证连通性。

        从 macOS/系统全局代理设置中读取配置（通过 urllib.request.getproxies()），
        随后对代理服务器进行 TCP 连通性测试（超时 0.5 秒）。

        - 若代理可达：返回含代理 env var 的字典，可直接注入 subprocess 环境。
        - 若代理不可达或未配置：返回空字典（不注入，避免 connection refused）。

        使用场景：注入 yt-dlp / curl 下载子进程，确保走代理高速下载；
                  同时注入 pipeline_manager 进程，确保 Gemini API 调用正常。
        """
        try:
            system_proxies = urllib.request.getproxies()  # 读取 macOS 系统全局代理
        except Exception:
            return {}

        http_proxy = system_proxies.get("http") or system_proxies.get("https")
        if not http_proxy:
            return {}

        # 解析代理地址和端口，进行 TCP 连通性测试
        try:
            from urllib.parse import urlparse
            parsed = urlparse(http_proxy)
            host = parsed.hostname
            port = parsed.port or 7890
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect((host, port))
            sock.close()
            # 代理可达，返回注入字典
            return {
                "HTTP_PROXY":  http_proxy,
                "HTTPS_PROXY": http_proxy,
                "http_proxy":  http_proxy,
                "https_proxy": http_proxy,
            }
        except Exception:
            # 代理不可达，返回空字典（保持直连，不注入任何代理变量）
            return {}


    @contextmanager
    def clash_switch_node(self, node: Optional[str] = None):
        """[Claude_Sonnet_4.6_Thinking_planning] v2.9.0: Clash 下载节点切换上下文管理器。

        在 with 块进入时，将 clash_proxy_group 切换到指定节点（默认使用 clash_download_node）；
        退出时（无论正常或异常）自动还原到切换前的节点。

        架构说明：Clash Mi 使用 macOS Network Extension，系统扩展不允许动态开放新端口(listeners)。
        因此此方案是在 TUN/proxy 层面切换代理组，下载期间全局流量共用日本节点。
        若 API 未配置或节点为 None，静默透传（不切换）。

        用法::
            with settings.clash_switch_node():
                # 此处所有下载走日本节点
                self._run_tracked(dl_cmd, ...)
            # 退出后自动还原节点
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        target_node = node or self.clash_download_node
        if not target_node or not self.clash_api_secret:
            yield
            return

        import urllib.parse as _up
        encoded_group = _up.quote(self.clash_proxy_group, safe="")
        api_base = self.clash_api_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.clash_api_secret}",
            "Content-Type": "application/json",
        }

        def _get_current() -> Optional[str]:
            try:
                req = urllib.request.Request(
                    f"{api_base}/proxies/{encoded_group}",
                    headers=headers,
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    return json.loads(resp.read()).get("now")
            except Exception as e:
                _log.warning(f"[Clash] 获取当前节点失败: {e}")
                return None

        def _switch(to_node: str) -> bool:
            try:
                body = json.dumps({"name": to_node}).encode()
                req = urllib.request.Request(
                    f"{api_base}/proxies/{encoded_group}",
                    data=body,
                    headers=headers,
                    method="PUT",
                )
                with urllib.request.urlopen(req, timeout=3):
                    pass
                _log.info(f"[Clash] [{self.clash_proxy_group}] → {to_node!r}")
                return True
            except Exception as e:
                _log.warning(f"[Clash] 切换失败 {to_node!r}: {e}")
                return False

        original = _get_current()

        # [Claude_Sonnet_4.6_Thinking_planning] 若 clash_download_node 是一个 URLTest 组名
        # （如 🇯🇵 日本下载专用），Selector 无法直接选择子组，需要先读取该组的 .now（当前最快节点）
        # 再把 Selector 切换到那个直连节点，从而动态跟踪最快日本节点。
        def _resolve_target() -> str:
            try:
                encoded = _up.quote(target_node, safe="")
                req = urllib.request.Request(
                    f"{api_base}/proxies/{encoded}",
                    headers=headers,
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    now = data.get("now")
                    if now:  # 是一个组，返回它当前选中的直连节点
                        _log.info(f"[Clash] {target_node!r} → 解析为直连节点 {now!r}")
                        return now
            except Exception:
                pass
            return target_node  # 不是组，直接用原名

        resolved_node = _resolve_target()
        switched = _switch(resolved_node)
        try:
            yield
        finally:
            if switched and original:
                _switch(original)
                _log.info(f"[Clash] 已还原 → {original!r}")


# 全局单例
settings = Settings()
