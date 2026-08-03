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
| 3.1.0 | 2026-06-22 | Claude_Opus_4.8                     | 新增 enable_subtitle_censorship（症结8）、enable_external_censor_rules（🅰️词库热加载）开关，及 censor_rules_path 计算属性 |
| 3.2.0 | 2026-06-23 | Claude_Opus_4.8                     | 新增 ytdlp_path 计算属性（单一真相源）：杜绝裸 'yt-dlp'，修复发布断流根因——cron 最小 PATH 无 .venv/bin 致 FileNotFoundError，频道发现整体静默失败 |
| 3.3.0 | 2026-06-25 | Claude_Opus_4.8                     | 新增 enable_source_date_stamp / source_date_stamp_label：竖屏成片左上角「源视频发布日期」毛玻璃戳开关与文案前缀，默认关闭 |
| 3.4.0 | 2026-06-28 | Claude_Opus_4.8                     | 新增 censorship_bypass_channels（逗号分隔 channel_id）+ censorship_bypass_channel_set 解析属性：受信任频道整体跳过审查(P0/P1/P2/CP)，供运营对自审过的优质频道开绿灯；另新增 wechat_session_warn_hours(会话临期预警阈值) |
| 3.4.1 | 2026-07-26 | Codex                               | censorship_bypass_channels 收紧为仅豁免 CP 频道策略，P0/P1/P2 违法层不再允许整频道绕过 |
| 3.5.0 | 2026-06-28 | Claude_Opus_4.8                     | 新增 channel_score_floors（"channel_id:分数"）+ channel_score_floor_map：受信任频道评分地板分，使其所有视频(含低播放)过发布线 ≥75 全发（@wstruthbombs 默认 80）|
| 3.6.0 | 2026-07-05 | Codex                               | 新增 subtitle_translation_provider_order，支持字幕翻译供应商顺序配置 |
| 3.7.0 | 2026-07-05 | Codex                               | 新增 DeepSeek OpenAI-compatible API 配置，为字幕翻译 provider 预留 |
| 3.8.0 | 2026-07-09 | Codex                               | 新增字幕质量与频道策略 fail-open 运行时开关，支持紧急恢复发布 |
| 3.9.0 | 2026-07-10 | Codex                               | 新增微信会话临期自动预热重登开关，提前推送二维码避免发布时才发现过期 |
| 3.17.0 | 2026-07-28 | Codex                              | 新增 YouTube Data API 频道目录配置；无密钥时由 RSS 降级保住候选发现 |
| 3.10.0 | 2026-07-12 | Codex                              | 新增演讲类频道独立自动发布线，score >= 40 进入自动处理队列 |
| 3.11.0 | 2026-07-13 | Codex                              | 新增动态字幕模型池、DeepSeek vocab fallback 与数字检查开关 |
| 3.12.0 | 2026-07-15 | Codex                              | 新增快手创作者中心浏览器上传开关；默认关闭，不改变现有微信发布链路 |
| 3.13.0 | 2026-07-25 | Codex                              | 补齐抖音、视频号暂停恢复与多平台补录配置字段，避免运行时配置缺失崩溃 |
| 3.13.1 | 2026-07-26 | Codex                              | 字幕翻译默认顺序改为 Gemini→DeepSeek→Google，移除阿里云作为可选 provider |
| 3.14.0 | 2026-07-27 | Codex                              | 新增抖音浏览器动作节流和每轮审核回查上限，降低创作者中心风控风险 |
| 3.15.0 | 2026-07-28 | Codex                              | 新增公开视频发布黄金窗口配置，支持按北京时间活跃高峰控制平台提交 |
| 3.15.1 | 2026-07-29 | Codex                              | 默认发布窗口整体前移 30 分钟，抢占活跃峰值前置流量 |
| 3.15.2 | 2026-07-29 | Codex                              | 新增中国大陆节假日/补班日配置，工作日与休息日使用不同发布窗口 |
| 3.15.3 | 2026-07-29 | Codex                              | 人工混音版默认使用 0.16 英文底音，并增加 DeepSeek thinking 脚本精修配置 |
| 3.15.4 | 2026-07-29 | Codex                              | 新增内容贴合封面开关，默认关闭以保持现有例行发布行为不变 |
| 3.15.5 | 2026-07-31 | Codex                              | 收敛发布规则默认值：工作日早窗固定 06:30-09:00、休息日早窗 07:30-11:00，视频号补发上限 10 |
| 3.15.8 | 2026-08-02 | Codex                              | 默认关闭发布时段限制；候选完成全部处理与审查后立即提交 |
| 3.15.6 | 2026-07-31 | Codex                              | 新增源字幕先行预检与非窗口预加工配置，阻止未审视频下载 |
| 3.15.7 | 2026-07-31 | Codex                              | 新增 Codex AI 封面任务队列与本地超时降级配置，默认关闭 |
| 3.15.9 | 2026-08-03 | Codex                              | 新增人工普通话译制的火山语音凭据与频道音色档案路径；专属档案未命中时保持默认 TTS |
"""
import json
import socket
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List
from zoneinfo import ZoneInfo

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

    # 仪表盘端口（见 PORTS.md：9100-9199 为本项目专属区间，避开 :8080 等其他项目）
    # 可用环境变量 DASHBOARD_PORT 覆盖
    dashboard_port: int = 9100

    # [Claude_Opus_4.8] 美股盘中重负载保护：开启后，自动调度器在美股盘中
    # （ET 09:15–16:15，按 America/New_York 自动处理夏/冬令时）暂停一切重型
    # 管线处理（下载/Whisper/渲染），避免抢占与实盘交易行情管线共用的整机 CPU。
    # 本机为共享主机，已确认「盘中过载 → 富途行情积压 → 实盘用过期价格」的失效模式。
    enable_market_hours_guard: bool = True

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
    # [Claude_Opus_4.8] 微信会话临期预警阈值（小时）：会话龄超过此值，看门狗推 Telegram「该重扫了」，
    # 在 ~24h 服务端硬上限造成发布断档前主动提醒（见 docs/wechat_login_expiry_rca.html 候选②坐实）。
    wechat_session_warn_hours: float = 22.0
    # 临期时自动启动 --login-only --relogin 并把二维码推送到 Telegram。
    # 旧 state 在扫码成功前不覆盖；该开关不能绕过微信扫码，只把人工动作前移。
    wechat_auto_relogin_enabled: bool = False


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

    # 字幕翻译供应商顺序，逗号分隔。主链路默认：Gemini → DeepSeek → Google。
    subtitle_translation_provider_order: str = "gemini,deepseek,google"

    # DeepSeek OpenAI-compatible API（默认不启用；需把 deepseek 放入 subtitle_translation_provider_order）
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    # DeepSeek 一体化翻译+vocabulary 候选：完成 A/B 对比前保持关闭。
    enable_deepseek_vocab_fallback: bool = False

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
    # 优先使用静态 Cookie 文件，避免 --cookies-from-browser 在每次调用后触发 YouTube 轮转
    # 留空("")则回退到 --cookies-from-browser chrome
    # 使用 scripts/refresh_yt_cookies.py 从 Chrome 导出并保存到此文件
    # （2026-06-25：源由 Safari 改 Chrome——本机 Safari 未登录 YouTube，导出的匿名 cookie 触发 bot 风控）
    youtube_cookies_file: str = ""

    # YouTube Data API 只用于频道目录和评分元数据；下载仍由 yt-dlp 负责。
    # 留空时监控器自动退到公开 RSS，条目保持 METADATA_PENDING，绝不凭空自动发布。
    youtube_data_api_key: str = ""
    youtube_data_api_timeout_sec: int = 20

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

    # [临时兜底] 频道策略拦截 fail-open 开关。置 true 时，仅用于紧急回归，
    # 将 CP 层命中的中断降级为告警，不阻断发布；恢复后请改为 false。
    # TODO：后续删除该开关并用更精细可控的规则白名单替代，避免误放。
    enable_channel_policy_fail_open: bool = False

    # 审查词库外部化热加载（_BLOCKLIST/_CHANNEL_POLICY → config/censor_rules.json）
    # [Claude_Opus_4.8] 🅰️ 进化：运维在线增删敏感词、无需改代码重部署，闭合突发事件空窗期。
    # 关闭时用硬编码默认；开启后文件缺失/损坏/P0 空均安全回退默认，绝不静默置空审查。
    enable_external_censor_rules: bool = False

    # 字幕正文内容审查（渲染后对 Whisper 转录的 .ass 字幕全文做违禁词扫描）
    # [Claude_Opus_4.8] 闭合「标题/文案干净但语音敏感」的发布漏洞（红蓝审计 症结 8）。
    # 仅复用违法层 P0/P1/P2（精确词匹配，长文本安全）；不接入 CP 共现层——
    # CP 的「国名+冲突词」全文共现在数万字转录上几乎必然误杀，故字幕通道刻意绕开。
    # 默认关闭：开启会对此前「标题干净」的存量视频新增拦截，需先灰度验证再在 .env 置 true。
    enable_subtitle_censorship: bool = False

    # [临时兜底] 翻译质量守门 fail-open 开关。置 true 时，阻断问题仅留告警，不阻塞发布。
    # TODO：后续继续修复金额单位、事件方向相关误杀后，改回 blocking 语义并关闭该开关。
    enable_translation_quality_fail_open: bool = False
    # 财经数字数量级检查当前误报较多，暂时关闭；事件方向、实体、空字幕检查仍保留。
    enable_translation_numeric_guard: bool = False

    # 受信任频道白名单：列出的 channel_id（逗号分隔）仅跳过频道策略 CP。
    # P0/P1/P2 违法层始终执行，不能因整频道白名单绕过中国领导人、反华暴力、严重敏感事件等红线。
    # 经 settings.censorship_bypass_channel_set 读取。
    censorship_bypass_channels: str = ""

    # [Claude_Opus_4.8] 受信任频道评分下限（地板分）：列出的频道自动评分不低于指定分，使其所有视频
    # （含低播放/低互动）都过发布线 ≥75 自动发布。格式 "channel_id:分数,channel_id:分数"。
    # 与 censorship_bypass_channels 配合时也只影响评分与 CP，P0/P1/P2 仍强制审查。
    # 经 channel_score_floor_map 读取。
    channel_score_floors: str = ""

    # 演讲/TED/高校频道使用较低的自动发布线；普通频道仍使用 75。
    speech_publish_score_line: int = 40
    speech_channel_ids: str = (
        "UCt84aUC9OG6di8kSdKzEHTQ,UCLv7Gzc3VTO6ggFlXY0sOyw,"
        "UCzWwWbbKHg4aodl0S35R6XA,UC-EnprmCZ3OXyAoG7vjVNCA,"
        "UCAuUUnT6oDeKwE6v1NGQxug,UCsT0YIqwnpJCM-mx7-gSA4Q,"
        "UCnBT5HobLD5_iyHsZNL85Ng,UCSh-dNnqe1agUSzPM01LgBA"
    )

    # SIGTERM 阶梯强杀机制（删除活跃任务时优雅终止底层进程）
    enable_sigterm_kill: bool = False

    # 动态热词注入开关 [Gemini_3.5_Flash_High_planning]
    enable_dynamic_keywords: bool = False
    hn_top_n: int = 30

    # 源视频「发布日期」毛玻璃水印戳 [Claude_Opus_4.8]
    # 在竖屏成片左上角叠加一枚圆角毛玻璃日期戳（局部高斯模糊 + 半透明深色着色 + 白字），
    # 覆盖源视频左上角频道水印，并向观众标明「源视频的发布日期」——区别于视频号原生显示的
    # 「我们的发布时间(1小时前)」。数据取自 processed_videos.upload_date（YYYYMMDD），切片回退父行；
    # 缺失/非法则不渲染。默认关闭，灰度验证后在 .env 置 true。
    enable_source_date_stamp: bool = False
    # 日期戳文字前缀（与日期拼接，如「发布日期：2026-06-25」）。
    # 使用全角冒号「：」而非半角「:」，避免与 ffmpeg filtergraph 选项分隔符冲突。
    source_date_stamp_label: str = "发布日期："

    # 快手创作者中心浏览器上传。默认关闭；启用后使用本地 Playwright 会话文件扫码登录，
    # 不需要快手开放平台 App ID、密钥或 OAuth 授权。
    enable_kuaishou_browser_publishing: bool = False
    kuaishou_browser_headless: bool = True
    # 历史视频迁移到快手的每日上限；新视频双平台投递不受此上限限制。
    kuaishou_history_daily_limit: int = 10

    # 抖音创作者中心浏览器上传。默认关闭；启用后使用本地 Playwright 会话文件扫码登录。
    enable_douyin_browser_publishing: bool = False
    douyin_browser_headless: bool = True
    # 历史视频迁移到抖音的每日上限；新视频双平台投递不受此上限限制。
    douyin_history_daily_limit: int = 5
    # 任意两次抖音创作者中心浏览器动作之间的最小间隔；覆盖审核回查、新片同步与历史补录。
    douyin_browser_action_interval_sec: int = 180
    # 每轮最多回查多少条 UNDER_REVIEW，避免一次性连续打开作品管理页。
    douyin_review_max_per_run: int = 5
    # 每轮最多同步多少条“微信已发布但抖音未建账”的新片漏项。
    douyin_new_sync_max_per_run: int = 10
    # 仅扫描最近 N 小时内刚完成微信发布的新片，避免把旧历史内容混入 NEW 同步。
    douyin_new_sync_lookback_hours: int = 12

    # 配音再制中心：仅由 ./vpanel dubbing 显式调用，日常 PipelineManager 不读取这些配置。
    # API Key 只允许保存在本机 .env，禁止写入任务报告、数据库或日志。
    minimax_api_key: Optional[str] = None
    minimax_tts_model: str = "speech-2.8-turbo"
    minimax_tts_voice_id: str = "Chinese (Mandarin)_Male_Announcer"
    minimax_tts_preferred_speed: float = 1.08
    minimax_tts_min_speed: float = 0.96
    minimax_tts_max_speed: float = 1.28
    minimax_tts_request_interval_sec: float = 1.1
    # 火山豆包语音 API Key：仅供“人工普通话译制中心”读取，必须只保存在本机 .env。
    # 绝不写入音色档案、数据库快照、日志、报告或 Git；未配置时，命中火山档案的任务直接失败。
    volc_speech_api_key: Optional[str] = None
    volc_speech_request_interval_sec: float = 0.2
    # 非密钥的频道音色档案。命中专属频道时选档案；没有匹配条目时回退现有 MiniMax 默认 TTS。
    # 相对路径以项目根目录为基准，档案内容必须可安全提交且不得出现 API Key。
    dubbing_voice_profiles_path: str = "config/dubbing_voice_profiles.json"
    dubbing_audio_policy: str = "zh_with_english_bed"
    dubbing_english_bed_volume: float = 0.16
    dubbing_target_lufs: float = -14.0
    dubbing_deepseek_script_refinement: bool = True
    dubbing_deepseek_thinking_enabled: bool = True
    dubbing_deepseek_refinement_batch_size: int = 6
    dubbing_subtitle_font_size: int = 72
    dubbing_subtitle_max_page_chars: int = 28
    dubbing_subtitle_max_line_chars: int = 12

    # 内容贴合封面：根据既有标题、分类、content_hints 输出稳定视觉策划，并使用真实成片画面渲染。
    # 默认关闭；启用后会额外持久化 _cover_brief.json，缺失时不复用旧封面 checkpoint。
    enable_content_aware_cover: bool = False

    # Codex 专属底图队列。任务单由项目写入目录，Codex 技能生成底图后写回完成目录；
    # 本地协调器在超时前执行当前确定性封面渲染，绝不等待外部执行器无限期返回。
    enable_codex_cover_queue: bool = False
    ai_cover_queue_dir: str = "ai-cover-queue"
    ai_cover_finish_dir: str = "ai-cover-finish"
    ai_cover_generation_deadline_minutes: int = 32
    ai_cover_fallback_after_minutes: int = 34

    # 视频号暂停发布时，新视频可先进入 WECHAT_DEFERRED，并按限额在恢复后补发。
    wechat_publishing_paused: bool = False
    wechat_deferred_recovery_daily_limit: int = 10

    # 源字幕先行：先用 yt-dlp --skip-download 拉取 VTT 并通过安全审查，
    # 才允许下载原视频。非发布窗口的预加工只处理 AUTO 候选，绝不提交平台。
    enable_background_preparation: bool = True
    background_preparation_batch_limit: int = 1
    source_subtitle_languages: str = "en.*,en"
    source_subtitle_retry_hours: int = 6

    # 公开视频提交窗口。默认关闭，避免成片在等待窗口时落后于同类内容；
    # 如需恢复定时发布，可在 .env 将开关显式设为 true。
    # 工作日：早通勤、午休、晚通勤、晚间黄金档；各窗口相对统计峰值整体提前 30 分钟。
    enable_public_publish_windows: bool = False
    public_publish_timezone: str = "Asia/Shanghai"
    public_publish_windows: str = "06:30-09:00,11:15-12:45,17:00-18:15,19:00-20:40"
    # 周末/法定节假日：通勤峰弱化，上午整体后移，下午休闲窗口拉长，晚间保留更长推荐期。
    public_publish_holiday_windows: str = "07:30-11:00,13:30-16:30,19:00-21:30"
    # 中国大陆 2026 年国务院办公厅放假日期；格式支持 YYYY-MM-DD 或 YYYY-MM-DD..YYYY-MM-DD。
    china_public_holidays: str = (
        "2026-01-01..2026-01-03,"
        "2026-02-15..2026-02-23,"
        "2026-04-04..2026-04-06,"
        "2026-05-01..2026-05-05,"
        "2026-06-19..2026-06-21,"
        "2026-09-25..2026-09-27,"
        "2026-10-01..2026-10-07"
    )
    china_makeup_workdays: str = "2026-01-04,2026-02-14,2026-02-28,2026-05-09,2026-09-20,2026-10-10"

    # 多平台历史补录规则：Wall Street Truthbombs 的源视频发布日期下界（YYYYMMDD）。
    platform_backfill_wall_street_since_upload_date: str = "20260713"

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

    @property
    def censorship_bypass_channel_set(self) -> set:
        """[Claude_Opus_4.8] 受信任频道 channel_id 集合（跳过全部审查）。解析逗号分隔配置。"""
        return {c.strip() for c in (self.censorship_bypass_channels or "").split(",") if c.strip()}

    @property
    def channel_score_floor_map(self) -> dict:
        """[Claude_Opus_4.8] channel_id→地板分 映射（解析 channel_score_floors，如 'UCxxx:80'）。"""
        m = {}
        for pair in (self.channel_score_floors or "").split(","):
            cid, sep, sc = pair.strip().partition(":")
            if sep and cid.strip():
                try:
                    m[cid.strip()] = int(sc.strip())
                except ValueError:
                    pass
        return m

    @property
    def speech_channel_id_set(self) -> set[str]:
        return {cid.strip() for cid in (self.speech_channel_ids or "").split(",") if cid.strip()}

    @property
    def auto_publish_channel_min_scores(self) -> dict[str, int]:
        return {cid: self.speech_publish_score_line for cid in self.speech_channel_id_set}

    @property
    def public_publish_window_ranges(self) -> list[tuple[int, int]]:
        """解析当前日期类型对应的发布窗口为分钟区间。"""
        return self._parse_publish_window_ranges(self.public_publish_windows)

    @property
    def public_publish_holiday_window_ranges(self) -> list[tuple[int, int]]:
        """解析 PUBLIC_PUBLISH_HOLIDAY_WINDOWS 为分钟区间。"""
        return self._parse_publish_window_ranges(self.public_publish_holiday_windows)

    def is_china_rest_day(self, value: date) -> bool:
        """按中国大陆放假/补班规则判断是否休息日；补班日优先级高于周末。"""
        if self._date_in_specs(value, self.china_makeup_workdays):
            return False
        if self._date_in_specs(value, self.china_public_holidays):
            return True
        return value.weekday() >= 5

    def selected_public_publish_windows(self, now: Optional[datetime] = None) -> str:
        """返回当前日期类型使用的发布窗口字符串。"""
        local_now = self._local_public_publish_datetime(now)
        if self.is_china_rest_day(local_now.date()):
            return self.public_publish_holiday_windows
        return self.public_publish_windows

    def selected_public_publish_window_ranges(self, now: Optional[datetime] = None) -> list[tuple[int, int]]:
        """返回当前日期类型使用的发布窗口分钟区间。"""
        return self._parse_publish_window_ranges(self.selected_public_publish_windows(now))

    @staticmethod
    def _parse_publish_window_ranges(value: str) -> list[tuple[int, int]]:
        """解析发布时间窗口；格式 HH:MM-HH:MM，逗号分隔。"""
        ranges: list[tuple[int, int]] = []
        for item in (value or "").split(","):
            start_raw, sep, end_raw = item.strip().partition("-")
            if not sep:
                continue
            start = Settings._parse_hhmm_minutes(start_raw)
            end = Settings._parse_hhmm_minutes(end_raw)
            if start is None or end is None or start == end:
                continue
            ranges.append((start, end))
        return ranges

    def is_public_publish_window(self, now: Optional[datetime] = None) -> bool:
        """当前时间是否允许触发公开视频提交；关闭开关时始终允许。"""
        if not self.enable_public_publish_windows:
            return True
        local_now = self._local_public_publish_datetime(now)
        minute = local_now.hour * 60 + local_now.minute
        for start, end in self.selected_public_publish_window_ranges(local_now):
            if start < end and start <= minute < end:
                return True
            if start > end and (minute >= start or minute < end):
                return True
        return False

    def _local_public_publish_datetime(self, now: Optional[datetime] = None) -> datetime:
        try:
            timezone = ZoneInfo(self.public_publish_timezone or "Asia/Shanghai")
        except Exception:
            timezone = ZoneInfo("Asia/Shanghai")
        local_now = datetime.now(timezone) if now is None else now
        if local_now.tzinfo is None:
            return local_now.replace(tzinfo=timezone)
        return local_now.astimezone(timezone)

    @staticmethod
    def _date_in_specs(value: date, specs: str) -> bool:
        for item in (specs or "").split(","):
            item = item.strip()
            if not item:
                continue
            start_raw, sep, end_raw = item.partition("..")
            try:
                start = date.fromisoformat(start_raw.strip())
                end = date.fromisoformat(end_raw.strip()) if sep else start
            except ValueError:
                continue
            if start <= value <= end:
                return True
        return False

    @staticmethod
    def _parse_hhmm_minutes(value: str) -> Optional[int]:
        parts = value.strip().split(":")
        if len(parts) != 2:
            return None
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute

    @property
    def subtitle_translation_provider_order_list(self) -> list[str]:
        """字幕翻译供应商顺序（过滤未知值，空配置回退默认顺序）。"""
        allowed = {"gemini", "deepseek", "google"}
        providers = []
        for item in (self.subtitle_translation_provider_order or "").split(","):
            provider = item.strip().lower()
            if provider in allowed and provider not in providers:
                providers.append(provider)
        return providers or ["gemini", "deepseek", "google"]

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

    @computed_field  # type: ignore[misc]
    @property
    def censor_rules_path(self) -> Path:
        """外部审查词库 JSON 路径（热加载，由 enable_external_censor_rules 控制）"""
        return self.project_root / "config" / "censor_rules.json"

    @computed_field  # type: ignore[misc]
    @property
    def ytdlp_path(self) -> str:
        """yt-dlp 可执行文件的绝对路径（项目 .venv/bin/yt-dlp）——单一真相源。

        所有调用 yt-dlp 的子进程（发现脚本 / 下载管理器）一律使用此绝对路径，
        严禁裸 "yt-dlp"。根因教训：cron 以 .venv/bin/python 直跑脚本时**不激活 venv**，
        其最小 PATH（/usr/bin:/bin）既无 .venv/bin 也无 /opt/homebrew/bin，裸命令必然
        FileNotFoundError → 频道发现每轮全灭却被当成"无新视频"静默吞掉（发布断流根因之一）。
        """
        return str(self.project_root / ".venv" / "bin" / "yt-dlp")

    # -------------------------------------------------------------------------
    # 工具方法
    # -------------------------------------------------------------------------

    def ensure_directories(self) -> None:
        """确保运行时必要的目录存在"""
        self.default_output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def is_us_market_guard_window(self) -> bool:
        """[Claude_Opus_4.8] 是否处于美股盘中重负载保护窗口（单一真相源）。

        共享主机同时运行实盘交易行情管线，盘中 CPU 被抢会导致行情积压 → 实盘用过期价格
        （已确认失效模式）。窗口 = ET 09:15–16:15 工作日，用 America/New_York 时区自动适配
        夏/冬令时；非交易时段（含周末）返回 False。可经 enable_market_hours_guard 关闭。
        供 web 调度器与 pipeline_manager 共用，避免重复实现。
        """
        if not self.enable_market_hours_guard:
            return False
        from zoneinfo import ZoneInfo
        from datetime import datetime
        et = datetime.now(ZoneInfo("America/New_York"))
        if et.weekday() >= 5:  # 周六/日：美股休市
            return False
        minutes = et.hour * 60 + et.minute
        return (9 * 60 + 15) <= minutes < (16 * 60 + 15)

    def get_yt_cookie_args(self) -> list[str]:
        """返回 yt-dlp 的 Cookie 参数列表。
        优先使用静态 Cookie 文件（避免每次调用触发 YouTube 轮转）；
        文件不存在或未配置时回退到 --cookies-from-browser chrome
        （本机 Chrome 已登录 YouTube；Safari 未登录会导出匿名 cookie 触发 bot 风控）。
        """
        if self.youtube_cookies_file:
            p = Path(self.youtube_cookies_file).expanduser()
            if p.exists():
                return ["--cookies", str(p)]
        return ["--cookies-from-browser", "chrome"]

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
