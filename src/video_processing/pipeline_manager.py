"""自动化管线调度器 - 协调监测、评分、加工与通知流转

# Modification History
| Version | Date       | Author                              | Description                                                                    |
|---------|------------|-------------------------------------|--------------------------------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.1_Pro_High_planning        | 初始创建 PipelineManager，实现完整的 FSM 调度                                   |
| 1.1.0   | 2026-05-21 | Gemini_3.5_Flash_planning           | 整合 Phase 5：文案生成与视频号全自动发布流                                       |
| 1.2.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 地基重构：消灭裸 SQL + os.environ 泄漏                                           |
| 1.3.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 专项审查：路径常量类级化、os 顶层导入、动态扩展名检测                            |
| 1.4.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 断点续传检查点、封面生成步骤、硬重置接口、完整上传参数                           |
| 2.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Phase 3] Popen+os.setsid 进程组隔离、PID 追踪、SIGTERM handler、评分锁防覆盖 |
| 2.0.1   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Review Fix] BUG-1:移除线程内 signal.signal(); BUG-2:重置 _sigterm_received; BUG-3:upload 用 _run_tracked; LINT-4:math 顶层 import |
| 2.0.2   | 2026-05-26 | Gemini_3.5_Flash_planning           | [v7.0 Phase 6 CON-1] 修复 open() 成功但 flock() 失败时 lock_file 的句柄泄露 |
| 2.1.0   | 2026-05-26 | Gemini_3.5_Flash_planning           | [v7.0 Censor Engine] 整合安全过滤引擎，新增三道违禁词拦截检查点，并捕获锁异常 |
| 2.1.1   | 2026-05-26 | Gemini_3.5_Flash                    | [v7.0 Fix] 修复 _run_tracked 传入 subprocess.Popen 时不支持 capture_output 等 kwargs 的问题 |
| 2.2.0   | 2026-05-26 | Gemini_3.5_Flash_planning           | 封面引擎 2.0 联动：读取短标题/副标题/内容 hints，组装 payload 传给生成器 |
| 2.3.0   | 2026-05-27 | Gemini_3.5_Flash                    | 新增下载后立即裁剪功能 (FFmpeg 流复制裁剪，支持 trim_start/trim_end) |
| 2.3.1   | 2026-05-27 | Unknown_Model_planning              | 修复分片时无法导入 copywriter 的 ModuleNotFoundError 问题                      |
| 2.3.2   | 2026-05-27 | Unknown_Model_planning              | 修复 slice_index > 0 时未执行导入代码导致的 UnboundLocalError 异常          |
| 2.4.0   | 2026-05-27 | Unknown_Model_planning              | 强制子分片封面副标题显示：主标题 + {当前集}/{总集数} 集                      |
| 2.5.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 支持 disable_slicing == 1 时强制跳过章节切片，保留整片制作发布流程 |
| 2.9.0   | 2026-05-28 | Claude_Sonnet_4.6_Thinking_planning | 多切片视频头部标题追加集数进度（如"AI写代码 3/9"），整片视频不受影响 |
| 2.8.0   | 2026-05-28 | Claude_Sonnet_4.6_Thinking_planning | 前移 COPYWRITING 至 TRANSCRIBING 之前，用中文短标题渲染，使视频头部与封面标题一致 |
| 2.7.0   | 2026-05-28 | Gemini_3.5_Flash_planning           | 改进 process_high_score_videos 支持连续批处理以自动完成所有切片与排队任务 |
| 2.6.0   | 2026-05-27 | Unknown_Model_planning              | 红蓝博弈安全性与容错性审计修复 (P1/P2) |
| 2.10.0  | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 从 video dict 读取 tts_provider 并在 render_cmd 中按需附加 --tts-cosy 参数，实现按需 TTS 配音而非默认自动开启 |
| 2.11.0  | 2026-06-01 | Gemini_2.5_Flash_planning           | [Censor Hardening] 修复 zh_text 参数 Bug（中文通道现在真正检测中文）；集成频道策略层；三处调用点传入 zh_title |
| 2.11.1  | 2026-06-01 | Gemini_3.5_Flash_planning           | [Censor Bugfix] 修复无 zh_title 时的中文视频内容安全与频道策略漏检，fallback 到 title |
| 2.12.0  | 2026-06-03 | Claude_Sonnet_4.6_Thinking_planning | [精准下载] 有 trim 参数时加入 --download-sections + --force-keyframes-at-cuts，避免完整下载长视频；跳过 ffmpeg 二次裁剪 |
| 3.0.0   | 2026-06-04 | Gemini_2.5_Pro_planning             | [丝带修复] copywriter checkpoint 增加 label_file 校验：copy+title 存在但 label 缺失时强制重跑，确保封面角标始终正确生成 |
| 3.1.0   | 2026-06-04 | Gemini_3.5_Flash_planning           | [下载优化] yt-dlp 启用 curl 外部下载器并配置 10 次自动重试与断点续传，解决代理环境下大视频/音频下载中断报错 |
| 3.1.1   | 2026-06-07 | Gemini_3.5_Flash_planning           | [修复上传错误] 渲染命令中增加 --output 参数，确保输出视频名不带 yt-dlp 格式后缀，从而与上传器期望路径一致 |
| 3.2.0   | 2026-06-07 | Gemini_3.5_Flash_planning           | [修复下载匹配] 优化 _find_downloaded_video：限定文件名主干(stem)必须与 yid 完全一致，排除包含 _vertical 等衍生文件或格式后缀的临时文件 |
| 3.3.0   | 2026-06-07 | Claude_Sonnet_4.6_Thinking_planning | [代理内射] 修复下载死锁/丢包根因：不再无条件清除代理变量改为动态检测+验证连通性后注入/不注入，确保 curl/yt-dlp 在代理可用时使用代理高速下载 |
| 3.4.0   | 2026-06-08 | Gemini_3.5_Flash_planning           | 注入 Telegram 配置环境变量；upload_cmd 中根据 settings.wechat_headless 动态配置 --no-headless 选项 |
| 3.5.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | [缓存失效] Transcribe Checkpoint 增加 .ass 双语内容校验：旧格式缓存缺少 Georgia 字体标签时强制删除并重渲，彻底消除代码升级后复用旧单语视频的缺陷 |
| 3.6.0   | 2026-06-08 | Claude_Sonnet_4.6_Thinking_planning | [原始归档] 下载完成后将原始媒体文件移入 original_video/ 子目录保留 3 天，_find_downloaded_video 优先热目录再回退冷存档，GC 逻辑零改动 |
| 3.7.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | 跳过 DISCOVERY 源视频的自动评分，保证高赞发现列表不被自动发布 |
| 3.8.0   | 2026-06-09 | Gemini_3.5_Flash_planning           | [下载限速超时] 限制 curl 最低速度 50KB/s 持续 30秒，防止代理连接坏节点时无限期卡死下载 |
| 3.8.1   | 2026-06-09 | Gemini_3.5_Flash_planning           | [下载限速调整] 将最低速度限制调低为 10KB/s (10000)，防止音频正常限速下载时被异常中断导致无限循环重试 |
| 3.9.0   | 2026-06-11 | Claude_Sonnet_4.6                   | [评分修复] 消除悬崖效应：发布门槛从 (views>2000, like_rate>3.5%) 调低至 (views>1500, like_rate>3.0%)，根治连续两天零发布的根因 |
| 3.10.0  | 2026-06-13 | Claude_Opus_4.8                     | _check_censorship 开头读取 is_censorship_bypassed(yid)：人工「🔓 复核放行」后跳过全部审查层，自动/手动触发均生效 |
| 3.11.0  | 2026-06-13 | Claude_Opus_4.8                     | GC 发布后保留再发产物（_vertical/_cover/_copy/_title/_category），仅删源视频与中间字幕，支撑「🔁 再次发布」复用 checkpoint 秒级重发 |
| 3.12.0  | 2026-06-13 | Claude_Opus_4.8                     | [Bugfix] _find_downloaded_video 改用视频扩展名白名单 _VIDEO_SUFFIXES，修复归档目录残留 .ass 被误当源视频喂给 ffmpeg（exit 234）的崩溃 |
| 3.13.0  | 2026-06-15 | Claude_Opus_4.8                     | [BUG-3] _find_downloaded_video 提取为 utils.file_utils.find_downloaded_video 单一真相源（bot 与管线共用），消除 bot 侧分叉实现 |
| 3.14.0  | 2026-06-15 | Claude_Opus_4.8                     | [BUG-1] _check_censorship 新增并透传 slice_index 到全部 db.* 调用与三处调用点，修复切片审查污染父行/卡死/漏发 |
| 3.15.0  | 2026-06-15 | Claude_Opus_4.8                     | [BUG-2] 上传器返回 3(UNCONFIRMED) 时不置 PUBLISHED、不 GC，转 FAILED 并告警人工核验，杜绝「假成功」误删源 |
| 3.16.0  | 2026-06-18 | Claude_Opus_4.8                     | [崩溃根治] 下载格式优先 H.264(avc) 而非 AV1(av01)：imageio-ffmpeg 内置 AOM AV1 解码器解码 YouTube AV1 流时间歇性 SIGSEGV，导致 _burn_subtitles 渲染崩溃；新增 vcodec^=avc 选择器分支 + -S vcodec:h264 排序，无 avc 时回退原行为 |
| 3.17.0  | 2026-06-18 | Claude_Opus_4.8                     | [假成片防护] 渲染 checkpoint 增加 ffprobe 完整性校验：渲染中途崩溃会留下 >1MB 但缺 moov 的截断 _vertical.mp4，旧校验仅看体积 → 误判有效 → 跳过重渲并发布损坏视频；现用 get_video_duration_ffprobe 验证可解析 |
| 3.18.0  | 2026-06-18 | Claude_Opus_4.8                     | [盘中重负载保护] process_high_score_videos 在美股盘中（settings.is_us_market_guard_window：ET 09:15–16:15 工作日）暂停批处理与逐视频处理，剩余任务保持 PENDING 待盘后；共享主机避免抢占实盘行情管线 CPU |
| 3.19.0  | 2026-06-22 | Claude_Opus_4.8                     | [症结 8 修复] 闭合「字幕正文从未过审」漏洞：2c 检查点在渲染后读取 .ass 转录全文，经 enable_subtitle_censorship 开关并入违法层 P0/P1/P2 复检；刻意绕开 CP 共现层避免长转录误杀；字幕读取下沉 utils.file_utils.read_subtitle_text 单一真相源（与 app.py 复核 UI 共用） |
| 3.20.0  | 2026-06-22 | Claude_Opus_4.8                     | [架构 C·DAG 修复] graceful_truncate_title 改从 utils.text_utils 顶层 import，移除 _process_single_video 内 sys.path 注入 scripts/ 反向 import copywriter 的 DAG 违规 |
| 3.21.0  | 2026-06-22 | Claude_Opus_4.8                     | [架构 B] 评分曲线抽出 scoring.compute_auto_score（+12 单测）；_check_censorship 审查执行抽出 censorship_service.CensorshipService（行为逐字保留，按调用契约即时构造）；PipelineManager 职责收敛 |
| 3.22.0  | 2026-06-23 | Claude_Opus_4.8                     | [发布断流根治②] _build_subprocess_env 强制 PATH 含 /opt/homebrew/bin(deno/node)与 .venv/bin：cron 最小 PATH 无 deno → yt-dlp 解 n-sig 挑战失败 → 高分视频"format not available"下载全败；_VENV_YTDLP 统一到 settings.ytdlp_path 单一真相源 |
| 3.23.0  | 2026-06-25 | Claude_Opus_4.8                     | [发布日期戳] enable_source_date_stamp 开启时，render_cmd 注入 --source-date（主视频取 upload_date，切片回退父行），格式化 YYYYMMDD→YYYY-MM-DD，缺失/非法则跳过 |
| 3.24.0  | 2026-06-25 | Claude_Opus_4.8                     | [失败可观测] 新增 _notify_failed(yid,title,reason,slice)：FAILED 通知统一带 youtube_id+精简原因；CalledProcessError(下载失败,最常见) 此前只发 Title 无 ID 无原因→用户无从定位「发了没动静」。title/reason 经 html.escape 防 yt-dlp stderr 的 &/<> 触发 Telegram HTML 400 丢通知 |
| 3.25.0  | 2026-06-28 | Claude_Opus_4.8                     | score_pending_videos 应用 settings.channel_score_floor_map 地板分：受信任频道(如 @wstruthbombs:80)自动评分托底→其所有视频过发布线全发（force=False 仍尊重人工锁分）|
| 3.26.0  | 2026-07-09 | Codex                               | [发布防卡死] _run_tracked 支持 timeout 并在超时时清理子进程组；微信上传调用增加 25 分钟硬超时，避免单条发布挂住拖死整队 |
| 3.27.0  | 2026-07-09 | Codex                               | [转录防卡死] auto-caption 渲染调用增加 45 分钟硬超时，超时后回写 FAILED 并通知，避免状态长期卡在 TRANSCRIBING |
| 3.28.0  | 2026-07-10 | Codex                               | 发布前启用上传器 fail-fast-login，失效登录立即回写 LOGIN_REQUIRED，避免 PUBLISHING 长时间等待扫码 |
| 3.29.0  | 2026-07-12 | Codex                               | 演讲类频道自动发布线降至 40，普通频道保持 75 |
| 3.30.0  | 2026-07-15 | Codex                               | 接入快手创作者中心账本：作品管理确认后才记成功；失败固定重试同一条，历史迁移每日最多 10 条 |
| 3.31.0  | 2026-07-15 | Codex                               | 拆分快手历史迁移与新片审核入口：审核回查绝不上传或发布 |
| 3.32.0  | 2026-07-25 | Gemini_3.6_Flash_planning           | 抽离 _resolve_cover_file 支持切片与父视频封面智能退避，补全快手 --cover 参数 |
| 3.33.0  | 2026-07-25 | Codex                               | 平台历史补录缺失本地投递素材时取消该任务并继续下一条，避免每日迁移被同一条旧记录卡死 |
| 3.34.0  | 2026-07-25 | Codex                               | 快手发布优先使用平台专用短文案，避免共享文案超出快手字数限制且不影响抖音回查 |
| 3.35.0  | 2026-07-26 | Codex                               | 快手/抖音上传前统一复跑内容安全闸门，历史补录与新片命中违禁均取消平台任务，杜绝绕过主流程审查 |
| 3.36.0  | 2026-07-27 | Codex                               | 删除抖音旧重复发布入口，确保补发/重试只保留带上传前审查的单一实现 |
| 3.37.0  | 2026-07-27 | Codex                               | 发布前审查调用 fail-closed 严格模式，禁止 CP fail-open 或审查异常放行到平台提交 |
| 3.38.0  | 2026-07-27 | Codex                               | 抖音创作者中心动作加节流和异常熔断告警，避免连续开网页/连续补录触发平台风控 |
| 3.39.0  | 2026-07-27 | Codex                               | 历史迁移限额为 0 时硬停抖音历史回填，审核回查跳过 HISTORY 记录但保留 NEW 新片发布 |
| 3.40.0  | 2026-07-27 | Codex                               | 平台告警格式抽到共享 PlatformEvent，管线与 Telegram 助手 bot 共用同一事件语义 |
| 3.41.0  | 2026-07-28 | Codex                               | 新增公开视频提交窗口守卫，视频号/抖音/快手仅在黄金时段触发新提交 |
| 3.42.0  | 2026-07-29 | Codex                               | 平台上传前字幕审查读取热目录与 original_video 归档；均读不到才 fail-closed，避免历史补发漏审 |
| 3.43.0  | 2026-07-29 | Codex                               | 抖音历史补发遇到本地产物缺失时取消该候选并继续补发后续视频，避免单条旧素材卡住整批 |
| 3.44.0  | 2026-07-29 | Codex                               | 抖音历史补发每领取一条即发送实时进度：当前视频、今日已领取、剩余额度和待发队列 |
| 3.44.1  | 2026-07-29 | Codex                               | 抖音发布将封面列为强制投递产物，缺封面时不调用上传器，避免半成品作品被提交 |
| 3.44.2  | 2026-07-29 | Codex                               | 抖音 UNDER_REVIEW 回查遇到作品管理未校准时转 UNCERTAIN，避免每轮重复打开后台刷 exit 4 |
| 3.44.3  | 2026-07-29 | Codex                               | 快手发布和回查识别账号封禁为 BANNED，发布确认写入明确证明备注 |
| 3.44.4  | 2026-07-29 | Codex                               | 区分抖音提交前闸门失败和提交后未确认，避免把未提交任务误标为 UNCERTAIN |
| 3.44.5  | 2026-07-29 | Codex                               | 抖音浏览器上传器正常返回仅记审核中，作品管理页明确已发布才允许写 PUBLISHED |
| 3.44.6  | 2026-07-29 | Codex                               | 每轮自动补齐最近微信已发布但抖音 NEW 未建账的漏同步项，并按上限连续同步新片 |
| 3.45.0  | 2026-07-29 | Codex                               | 可选地以已渲染成片、标题和语义策划生成内容贴合封面，默认保持旧封面流程 |
| 3.45.1  | 2026-07-30 | Codex                               | 视频号封面缺失即停止投递；每次投递保留独立、不可覆盖的封面与发布页面证据 |
| 3.45.2  | 2026-07-30 | Codex                               | 封面显式携带成片音轨版本；仅真实普通话配音版本允许显示配音角标           |
| 3.45.3  | 2026-07-31 | Codex                               | 例行发布封面恢复为专门生成图，不再默认从竖版成片截帧                       |
"""


import os
import hashlib
import math
import signal
import time
import logging
import subprocess
import requests
import fcntl
import html
from typing import Dict, Any, Optional
from pathlib import Path

from .db import PipelineDB
from .utils.file_utils import find_downloaded_video, VIDEO_CONTAINER_SUFFIXES, read_subtitle_text
from .utils.platform_events import PlatformEvent, format_platform_event_html
from .utils.text_utils import graceful_truncate_title
from .scoring import compute_auto_score, PUBLISH_SCORE_LINE
from .censorship_service import CensorshipService
from config.settings import settings

logger = logging.getLogger(__name__)


def _cover_audio_edition(tts_provider: Any) -> str:
    """将渲染配置收敛为封面可展示的音轨版本，不猜测未知 provider。"""
    return "mandarin_dubbed" if tts_provider in {"edge", "cosyvoice"} else "original_audio_subtitled"

# [Claude_Sonnet_4.6_Thinking_planning] v7.0: 模块级 SIGTERM 信号处理器
# 当该进程收到 SIGTERM 时，设置此标志位，由主循环在安全点检查并执行清理退出。
# 注意：signal handler 只能做最简单的操作（设置标志位），不能在 handler 内直接操作数据库或锁。
_sigterm_received: bool = False


def _sigterm_handler(signum: int, frame) -> None:  # noqa: ANN001
    """SIGTERM 信号处理器 — 设置模块级标志位，由主流程在安全点响应。"""
    global _sigterm_received
    _sigterm_received = True
    logger.warning("[SIGTERM] Signal received. Will clean up at next safe checkpoint.")

# 非视频文件后缀（下载产物中排除）
_NON_VIDEO_SUFFIXES = {'.description', '.json', '.ytdl', '.part', '.jpg', '.png', '.webp'}
# [Claude_Opus_4.8] 源视频识别改用「白名单」：仅这些容器扩展名才会被当作源视频。
# 单一真相源已上移至 utils.file_utils.VIDEO_CONTAINER_SUFFIXES（bot 与管线共用）；此处保留别名兼容旧引用。
_VIDEO_SUFFIXES = VIDEO_CONTAINER_SUFFIXES
# [Claude_Sonnet_4.6_Thinking_planning] v3.3.0: 代理环境变量选集，用于清除或替换
_PROXY_KEYS = frozenset({
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy',
})
_WECHAT_UPLOAD_TIMEOUT_SEC = 25 * 60
_KUAISHOU_UPLOAD_TIMEOUT_SEC = 25 * 60
_DOUYIN_UPLOAD_TIMEOUT_SEC = 25 * 60
_AUTO_CAPTION_TIMEOUT_SEC = 45 * 60


def _build_subprocess_env() -> dict:
    """[Claude_Sonnet_4.6_Thinking_planning] v3.3.0: 构建 subprocess 环境字典。

    策略：动态检测系统代理可用性，自动决定是否注入代理。
    - 若代理可达：将代理变量注入子进程，让 curl/yt-dlp 通过代理高速下载。
    - 若代理不可达：清除代理变量，避免 connection refused 导致进程卡死。

    这起到了两个作用：
    1. 免除旧日代理已关闭时直连 192.168.1.5:7890 导致 connection refused 的问题
    2. 在代理服务正常时，自动利用代理高速下载，避免直连 CDN 丢包/限速导致 curl exit 18
    """
    active_proxies = settings.get_active_proxies()  # TCP 测试：就绣注入，不就绣不注入
    # 从当前进程环境中展开，然后用 active_proxies 覆盖到/不到变量
    env = {k: v for k, v in os.environ.items() if k not in _PROXY_KEYS}
    # [Gemini_3.5_Flash_planning] v3.4.0: 注入 Telegram 配置环境变量，使 wechat_uploader 能够推送二维码
    if settings.telegram_bot_token:
        env["TELEGRAM_BOT_TOKEN"] = settings.telegram_bot_token
    if settings.active_telegram_chat_id:
        env["TELEGRAM_CHAT_ID"] = settings.active_telegram_chat_id
    if settings.telegram_admin_ids:
        env["TELEGRAM_ADMIN_IDS"] = settings.telegram_admin_ids
    env.update(active_proxies)  # 若 active_proxies 为空字典，则不注入任何代理
    # [Claude_Opus_4.8] 保证子进程 PATH 含 deno/node(yt-dlp 解 YouTube n-sig 挑战的 JS 运行时)
    # 与 .venv/bin。根因：cron 以 .venv/bin/python 直跑时**不激活 venv**，最小 PATH(/usr/bin:/bin)
    # 既无 /opt/homebrew/bin 也无 .venv/bin → yt-dlp 的 ejs 挑战求解器找不到 deno →
    # "n challenge solving failed" → 所有格式失效 → 高分视频下载整体失败（与发现路径裸 yt-dlp 同类）。
    # 此处自给自足，无论父进程(cron/dashboard/交互shell)的 PATH 如何，下载链路均能解挑战。
    _extra_path = [str(settings.project_root / ".venv" / "bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    env["PATH"] = ":".join(_extra_path + ([env["PATH"]] if env.get("PATH") else []))
    return env


class PipelineManager:
    # 路径常量 — 类级，避免每次调用重算
    _PRJ_ROOT    = Path(__file__).parent.parent.parent
    _SRC_DIR     = _PRJ_ROOT / "src"
    _VENV_PYTHON = str(_PRJ_ROOT / ".venv" / "bin" / "python")
    _VENV_YTDLP  = settings.ytdlp_path  # [Claude_Opus_4.8] 单一真相源（settings.ytdlp_path）；值与 _PRJ_ROOT/.venv/bin/yt-dlp 等同
    _OUT_DIR          = _PRJ_ROOT / "output"
    _ORIG_VIDEO_DIR   = _OUT_DIR / "original_video"   # [Claude_Sonnet_4.6_Thinking_planning] 原始视频归档目录

    def __init__(self, db_path: str = "pipeline.db"):
        self.db = PipelineDB(db_path)
        self._OUT_DIR.mkdir(exist_ok=True)
        self._ORIG_VIDEO_DIR.mkdir(exist_ok=True)  # [Claude_Sonnet_4.6_Thinking_planning] 归档目录随主目录一并创建
        self.telegram_token   = settings.telegram_bot_token
        self.telegram_chat_id = settings.telegram_chat_id
        self._last_douyin_browser_action_at: Optional[float] = None
        self._douyin_platform_halted = False
        self._douyin_halt_reason = ""

    # ── Telegram 通知 ─────────────────────────────────────────────────────────

    def send_telegram_msg(self, text: str):
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug(f"Telegram not configured. Would send: {text}")
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                json={"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def _notify_failed(self, yid: str, title: str, reason: str = "", slice_index: int = 0):
        """统一的「视频失败」Telegram 通知：带 youtube_id 与精简错误原因，便于定位。

        修复此前 CalledProcessError（最常见的下载失败）路径只发 'Title'、无 ID 无原因，
        用户无从判断「发了却没动静」的体验缺口（2026-06-25 GsqW5MPFajw 事故）。
        """
        prefix = yid if slice_index == 0 else f"{yid}#{slice_index}"
        # send_telegram_msg 用 parse_mode=HTML，title/reason 含 yt-dlp stderr（常带 & < >，
        # 如 googlevideo URL 的 query 串）会触发 Telegram 400「can't parse entities」→ 通知被
        # 静默丢弃（恰好砸在我们要修的『失败却没动静』场景）。故对插值部分做 HTML 转义，
        # 自己的 <b>/<code> 标签保持不转义。
        safe_title = html.escape(title or "")
        msg = f"❌ <b>Video Failed</b>\nTitle: {safe_title}\nID: <code>{prefix}</code>"
        if reason:
            snippet = html.escape(" ".join(reason.split())[:200])  # 折叠空白/换行，截断防刷屏
            msg += f"\nReason: {snippet}"
        self.send_telegram_msg(msg)

    def _is_public_publish_window(self, platform: str, yid: str = "", slice_index: int = 0) -> bool:
        """公开视频提交窗口守卫；审核回查等只读动作不受此限制。"""
        if settings.is_public_publish_window():
            return True
        prefix = f"{yid}_s{slice_index}" if yid and slice_index > 0 else yid
        target = f" {prefix}" if prefix else ""
        logger.info(
            "[PublishWindow] 当前不在公开视频提交窗口，跳过%s%s；配置窗口=%s %s",
            platform,
            target,
            settings.public_publish_timezone,
            settings.selected_public_publish_windows(),
        )
        return False

    def _notify_platform_alert(
        self,
        platform: str,
        yid: str,
        reason: str,
        *,
        source_kind: str = "",
        state: str = "",
        action: str = "",
    ) -> None:
        """平台发布链高风险告警：强调人工核对和停止自动动作。"""
        self.send_telegram_msg(format_platform_event_html(PlatformEvent(
            platform=platform,
            youtube_id=yid,
            reason=reason,
            source_kind=source_kind,
            state=state,
            action=action,
            severity="critical",
        )))

    def _halt_douyin_platform(
        self,
        yid: str,
        reason: str,
        *,
        publication: Optional[Dict[str, Any]] = None,
        state: str = "",
    ) -> None:
        """停止本轮后续抖音浏览器动作，并发出一次明确告警。"""
        self._douyin_platform_halted = True
        self._douyin_halt_reason = reason
        source_kind = ""
        if publication:
            source_kind = str(publication.get("source_kind") or "")
        logger.error("[%s] 抖音自动动作已熔断：%s", yid, reason)
        self._notify_platform_alert(
            "Douyin",
            yid,
            reason,
            source_kind=source_kind,
            state=state,
            action="本轮停止抖音回查/新片同步/历史回填；请先人工核对创作者中心。",
        )

    def _throttle_douyin_browser_action(self, reason: str) -> None:
        """抖音创作者中心页面动作之间强制留间隔，降低连续打开网页的风控风险。"""
        interval = max(0, int(settings.douyin_browser_action_interval_sec or 0))
        now = time.monotonic()
        if self._last_douyin_browser_action_at is not None and interval > 0:
            elapsed = now - self._last_douyin_browser_action_at
            remaining = interval - elapsed
            if remaining > 0:
                logger.info("[DouyinThrottle] %s：等待 %.1f 秒后再访问创作者中心。", reason, remaining)
                time.sleep(remaining)
        self._last_douyin_browser_action_at = time.monotonic()

    def _reset_douyin_run_guard(self) -> None:
        """新一轮调度开始时重置抖音本轮熔断状态。"""
        self._douyin_platform_halted = False
        self._douyin_halt_reason = ""
        self._last_douyin_browser_action_at = None

    # ── 评分 ──────────────────────────────────────────────────────────────────

    def score_pending_videos(self):
        """对 PENDING 且 score < 75 的视频自动评分（不覆盖人工调分）"""
        # [Claude_Sonnet_4.6_Thinking_planning] LINT-4 修复: math 已移至模块顶层导入
        pending  = self.db.get_videos_by_status("PENDING")
        # [Gemini_3.5_Flash_planning] 跳过 DISCOVERY 来源的视频，防止其被自动评分机制提高到 >= 75 分从而触发自动发布
        to_score = [v for v in pending if v.get('score', 0) < PUBLISH_SCORE_LINE and v.get('source') != 'DISCOVERY']
        skipped  = len(pending) - len(to_score)
        if skipped:
            logger.info(f"Skipping {skipped} already-prioritized or discovery videos.")
        if not to_score:
            return

        logger.info(f"Scoring {len(to_score)} pending videos...")
        for video in to_score:
            yid        = video['youtube_id']
            views      = max(0, video.get('view_count') or 0)
            likes      = max(0, video.get('like_count') or 0)
            # [Claude_Opus_4.8 架构B] 评分曲线已抽至 scoring.compute_auto_score（纯函数，可单测）
            score      = compute_auto_score(views, likes)

            # [Claude_Opus_4.8] 受信任频道地板分：列入 settings.channel_score_floor_map 的频道
            # 评分托底（如 @wstruthbombs 默认 80→必过发布线 ≥75，整批自动发布，不受低播放拖累）。
            _floor = settings.channel_score_floor_map.get(video.get('channel_id'), 0)
            if _floor > score:
                logger.info(f"  [{yid}] trusted-channel score floor {_floor} applied (computed was {score})")
                score = _floor

            if views > 0:
                logger.info(f"  [{yid}] views={views} like_rate={likes / views * 100:.1f}% → score={score}")
            else:
                logger.info(f"  [{yid}] no view data → score=0")
            # force=False：自动算分，is_manually_scored=1 的记录会被 DB 层自动跳过
            self.db.update_video_score(yid, score, force=False)

    # ── 批量触发 ──────────────────────────────────────────────────────────────

    def process_high_score_videos(self, limit: int = 5):
        """拉取高分视频进入加工流转，自动循环处理全部队列和切片任务直至清空。

        # Modification History
        | Version | Date | Author | Description |
        | --- | --- | --- | --- |
        | 1.0.0 | 2026-05-28 | Gemini_3.5_Flash_planning | 实现批次自动循环调度，彻底消除切片子任务需要手动执行的痛点 |
        """
        # [Gemini_3.5_Flash_planning] 连续拉取高分视频直至全部处理完成，避免切片或排队任务需要频繁手动执行
        logger.info(f"Starting pipeline run loop (batch limit={limit}).")
        total_processed = 0
        
        while True:
            # [Claude_Opus_4.8] 美股盘中重负载保护：盘中（ET 09:15–16:15 工作日）不开新批，
            # 剩余高分任务保持 PENDING，盘后（北京 04:15 起）由调度器自动恢复。共享主机避免
            # 抢占实盘交易行情管线 CPU（已确认「盘中过载→行情积压→实盘用过期价格」失效模式）。
            if settings.is_us_market_guard_window():
                logger.info("[MarketGuard] 美股盘中，暂停高分视频批处理（重负载保护），剩余任务保持 PENDING。")
                break
            if not self._is_public_publish_window("Pipeline"):
                logger.info("[PublishWindow] 非发布窗口，暂停高分视频加工；候选保持 PENDING 等待黄金时段。")
                break

            # 拉取多一点以备过滤父视频就绪与发布顺序锁 [Gemini_3.5_Flash_planning]
            targets = self.db.get_high_score_pending_videos(
                min_score=75,
                limit=limit * 3,
                channel_min_scores=settings.auto_publish_channel_min_scores,
            )
            if not targets:
                logger.info("No more high-score videos available for processing.")
                break

            claimed_targets = []
            for video in targets:
                yid = video['youtube_id']
                slice_index = video.get('slice_index', 0)
                
                if slice_index > 0:
                    # 1. 检查父视频文件是否下载就绪
                    parent_file = self._find_downloaded_video(yid)
                    if not parent_file:
                        logger.info(f"Sub-task [{yid} s{slice_index}] skipped: Parent video file not ready.")
                        continue
                    
                    # 2. 检查前序子任务是否已发布 (Sequence Locking)
                    all_slices = self.db.get_slices_by_parent_yid(yid)
                    prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
                    if prev_not_published:
                        prev_indices = [s['slice_index'] for s in prev_not_published]
                        logger.info(f"Sub-task [{yid} s{slice_index}] skipped: Waiting for previous slices {prev_indices} to publish.")
                        continue
                
                # 防竞态：尝试抢占 [Gemini_3.5_Flash_planning]
                if self.db.claim_video_for_processing(yid, slice_index=slice_index):
                    claimed_targets.append(video)
                    if len(claimed_targets) >= limit:
                        break

            if not claimed_targets:
                logger.info("No claimable high-score videos in this batch. Exiting loop.")
                break

            logger.info(f"Processing a batch of {len(claimed_targets)} video(s).")
            self.send_telegram_msg(
                f"🚀 <b>Pipeline Batch Started</b>\nProcessing {len(claimed_targets)} videos in this batch."
            )
            for video in claimed_targets:
                # [Claude_Opus_4.8] 窗口若在批处理中途开盘，立即停手，剩余 claimed 任务由
                # 调度器 purge_stale_tasks 复位回 PENDING，盘后重跑（重负载保护）。
                if settings.is_us_market_guard_window():
                    logger.info("[MarketGuard] 进入美股盘中窗口，停止本批剩余视频处理（重负载保护）。")
                    break
                self._process_single_video(video)
                total_processed += 1

        logger.info(f"Pipeline run loop completed. Total processed: {total_processed}")

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def reset_video_artifacts(self, yid: str) -> list:
        """硬重置：删除指定视频所有产物文件，返回已删除文件名列表。
        调用后配合 db.update_video_status(yid, 'PENDING') 完成完全重置。
        """
        deleted = []
        for pat in [
            f"{yid}.*",
            f"{yid}_vertical.mp4",
            f"{yid}_copy.txt",
            f"{yid}_title.txt",
            f"{yid}_category.txt",
            f"{yid}_cover.jpg",
        ]:
            for f in self._OUT_DIR.glob(pat):
                try:
                    f.unlink()
                    deleted.append(f.name)
                    logger.info(f"[HARD RESET] Deleted: {f.name}")
                except Exception as e:
                    logger.warning(f"Cannot delete {f.name}: {e}")
        return deleted

    def _find_downloaded_video(self, yid: str) -> Optional[str]:
        """查找下载后的视频主文件（热目录 output/ 优先，回退冷归档 original_video/）。

        实现已提取为 ``utils.file_utils.find_downloaded_video`` 单一真相源，
        bot（pipeline_agent）与管线共用，避免两处实现分叉。
        # [Claude_Opus_4.8] v3.13.0 提取共享实现；保留薄封装以维持归档命中的日志。
        """
        result = find_downloaded_video(self._OUT_DIR, yid, self._ORIG_VIDEO_DIR)
        if result and Path(result).parent == self._ORIG_VIDEO_DIR:
            logger.info(f"[OV] Found archived original video for {yid}: {Path(result).name}")
        return result

    # ── 原始视频归档（v3.6.0）────────────────────────────────────────────────

    def _archive_original_video(self, yid: str) -> None:
        """将 output/ 中属于 yid 的原始媒体文件移入 original_video/ 归档目录。

        归档文件范围：
        - 媒体文件：.mp4, .webm, .mkv, .m4a（原始素材）
        - 元数据文件：.info.json（章节提取所需，与视频强绑定）
        - 排除：_vertical.mp4、_copy.txt 等加工产物（stem 含下划线子段）

        移动后立即触发 TTL 清理，防止归档目录无限膨胀。
        # [Claude_Sonnet_4.6_Thinking_planning] v3.6.0
        """
        import shutil

        # 允许归档的媒体扩展名（排除 _NON_VIDEO_SUFFIXES 中非媒体项，保留 .info.json）
        _ARCHIVE_SUFFIXES = {'.mp4', '.webm', '.mkv', '.m4a', '.json'}

        archived_count = 0
        for f in list(self._OUT_DIR.glob(f"{yid}.*")):
            # 只归档主干等于 yid 的文件，排除 {yid}_vertical.mp4 等衍生产物
            if f.stem != yid:
                continue
            if f.suffix not in _ARCHIVE_SUFFIXES:
                continue
            dest = self._ORIG_VIDEO_DIR / f.name
            try:
                shutil.move(str(f), str(dest))
                logger.info(f"[OV] Archived: {f.name} → original_video/")
                archived_count += 1
            except Exception as e:
                logger.warning(f"[OV] Failed to archive {f.name}: {e}")

        if archived_count > 0:
            logger.info(f"[OV] Archived {archived_count} file(s) for {yid}. Triggering TTL eviction.")
            self._evict_original_video_dir()

    def _evict_original_video_dir(self, ttl_days: int = 3) -> None:
        """删除 original_video/ 中修改时间超过 ttl_days 天的文件（TTL 清理）。

        设计原则：只按 mtime 判断，不区分视频 ID，对正在使用的新鲜文件无影响。
        # [Claude_Sonnet_4.6_Thinking_planning] v3.6.0
        """
        import time as _time

        ttl_seconds = ttl_days * 86400
        now = _time.time()
        evicted = 0
        for f in self._ORIG_VIDEO_DIR.iterdir():
            if not f.is_file():
                continue
            age = now - f.stat().st_mtime
            if age > ttl_seconds:
                try:
                    f.unlink()
                    logger.info(f"[OV-GC] Evicted (age={age/86400:.1f}d): {f.name}")
                    evicted += 1
                except Exception as e:
                    logger.warning(f"[OV-GC] Failed to evict {f.name}: {e}")
        if evicted:
            logger.info(f"[OV-GC] TTL eviction complete: {evicted} file(s) removed from original_video/.")

    # ── 子进程辅助（v7.0: Popen + 进程组隔离）────────────────────────────────

    def _run_tracked(self, cmd: list, yid: str, slice_index: int = 0, **kwargs) -> subprocess.CompletedProcess:
        """以独立进程组运行命令，并将 PGID 写入数据库，供 API 层 SIGTERM 精准击杀。

        [Claude_Sonnet_4.6_Thinking_planning] v7.0 关键设计：
        - os.setsid() 在子进程建立独立的会话（Session Leader），
          使 os.killpg(pgid, SIGTERM) 只击杀该子进程组，不波及 FastAPI 父进程。
        - 仅当 settings.enable_sigterm_kill=True 时启用 PID 追踪（Feature Flag 保护）。
        """
        # [Gemini_3.5_Flash_fast] 避免 Popen 收到不支持的 capture_output 和 check 参数
        popen_kwargs = kwargs.copy()
        timeout = popen_kwargs.pop("timeout", None)
        if popen_kwargs.pop("capture_output", False):
            popen_kwargs["stdout"] = subprocess.PIPE
            popen_kwargs["stderr"] = subprocess.PIPE
        popen_kwargs.pop("check", None)
        # [Claude_Sonnet_4.6_Thinking_planning] v3.3.0: 若调用方未显式提供 env，
        # 则自动注入动态代理环境（可达则注入，不可达则清除）
        if "env" not in popen_kwargs:
            popen_kwargs["env"] = _build_subprocess_env()

        if settings.enable_sigterm_kill:
            proc = subprocess.Popen(
                cmd,
                preexec_fn=os.setsid,  # 建立独立进程组
                **popen_kwargs
            )
            try:
                pgid = os.getpgid(proc.pid)
                self.db.update_process_pid(yid, pgid, slice_index=slice_index)
            except ProcessLookupError:
                pass  # 进程已极速退出，无需记录
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as e:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    proc.kill()
                stdout, stderr = proc.communicate()
                raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from e
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, cmd,
                    output=stdout, stderr=stderr,
                )
            return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        else:
            # Feature Flag 关闭时：回退到原有 subprocess.run，零侵入
            return subprocess.run(cmd, check=True, **kwargs)

    def _run_garbage_collection(self, yid: str, slice_index: int, status: str):
        """[Unknown_Model_planning] GC 自动清理器：
        - 支持子任务 (slice_index > 0) 或整片任务 (slice_index == 0) 发布成功后，清理其对应的临时媒体文件与文本/字幕/语音夹。
        - 当所有子任务均进入终态，清理父任务的超大原始 MP4 视频与 info.json 等临时文件。
        """
        import shutil
        
        # 1. 如果任务发布成功，清理其关联的临时文件
        if status == "PUBLISHED":
            prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
            # [Claude_Opus_4.8] 保留「再次发布」所需产物——成片(_vertical.mp4)、封面、文案、
            # 短标题、分类，使已发布视频可被「🔁 再次发布」秒级重发（复用本地产物、内容与原版一致）。
            # 仅清理体积大且可重建的源视频与中间字幕：源视频另有 original_video/ 冷存档（保留 3 天）兜底，
            # 故热目录源可安全删除；超出存档窗口再次发布时管线会自动回退重新下载/渲染。
            suffixes = [
                ".mp4",            # 源视频（已归档到 original_video/，热目录副本可删）
                ".ass",
                "_subtitle.txt",
                ".description",
            ]
            
            for suffix in suffixes:
                file_path = self._OUT_DIR / f"{prefix}{suffix}"
                if file_path.exists():
                    try:
                        file_path.unlink()
                        logger.info(f"[GC] Deleted artifact: {file_path.name}")
                    except Exception as e:
                        logger.warning(f"[GC] Failed to delete artifact {file_path.name}: {e}")
            
            # 清理 Edge TTS 生成的临时语音目录
            audio_gen_dir = self._OUT_DIR / f"{prefix}_audio_gen"
            if audio_gen_dir.exists() and audio_gen_dir.is_dir():
                try:
                    shutil.rmtree(audio_gen_dir)
                    logger.info(f"[GC] Deleted audio gen folder: {audio_gen_dir.name}")
                except Exception as e:
                    logger.warning(f"[GC] Failed to delete audio gen folder {audio_gen_dir.name}: {e}")

        # 2. 检查兄弟子任务状态以判断是否清理父文件
        if slice_index > 0:
            all_slices = self.db.get_slices_by_parent_yid(yid)
            if all_slices and all(s["status"] in ("PUBLISHED", "FAILED", "IGNORED", "COMPLETED") for s in all_slices):
                logger.info(f"[GC] All slices for parent {yid} are finished. Cleaning up parent artifacts...")
                parent_suffixes = [
                    ".mp4", ".info.json", ".description", "_subtitle.txt", "_copy.txt",
                    "_title.txt", "_category.txt", "_cover.jpg", ".ass",
                ]
                for suffix in parent_suffixes:
                    file_path = self._OUT_DIR / f"{yid}{suffix}"
                    if file_path.exists():
                        try:
                            file_path.unlink()
                            logger.info(f"[GC] Deleted parent artifact: {file_path.name}")
                        except Exception as e:
                            logger.warning(f"[GC] Failed to delete parent artifact {file_path.name}: {e}")
                parent_audio_dir = self._OUT_DIR / f"{yid}_audio_gen"
                if parent_audio_dir.exists() and parent_audio_dir.is_dir():
                    try:
                        shutil.rmtree(parent_audio_dir)
                        logger.info(f"[GC] Deleted parent audio gen folder: {parent_audio_dir.name}")
                    except Exception as e:
                        logger.warning(f"[GC] Failed to delete parent audio gen folder {parent_audio_dir.name}: {e}")

    # ── 快手创作者中心发布 ─────────────────────────────────────────────────────

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """计算成片摘要；同一摘要只有在快手作品管理确认已发布后才会去重。"""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _kuaishou_asset_paths(self, yid: str, slice_index: int) -> tuple[Path, Path]:
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
        kuaishou_copy = self._OUT_DIR / f"{prefix}_kuaishou_copy.txt"
        copy_file = kuaishou_copy if kuaishou_copy.is_file() else self._OUT_DIR / f"{prefix}_copy.txt"
        return self._OUT_DIR / f"{prefix}_vertical.mp4", copy_file

    def _resolve_cover_file(self, yid: str, slice_index: int = 0) -> Optional[Path]:
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
        candidate = self._OUT_DIR / f"{prefix}_cover.jpg"
        if candidate.is_file():
            return candidate
        fallback = self._OUT_DIR / f"{yid}_cover.jpg"
        if fallback.is_file():
            return fallback
        return None

    def _read_publication_text_file(self, path: Path, yid: str, label: str) -> str:
        """读取平台投递文本；读取失败时返回空串，由审查层按已有内容继续判断。"""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.warning("[%s] 读取%s失败：%s", yid, label, exc)
            return ""

    def _platform_publication_censorship_blocked(
        self,
        publication: Dict[str, Any],
        platform: str,
        copy_file: Path,
        title_file: Optional[Path] = None,
    ) -> bool:
        """平台上传前复跑同一套审查；命中后取消平台任务而不是调用浏览器上传器。"""
        publication_id = publication["id"]
        yid = publication["youtube_id"]
        slice_index = publication.get("slice_index", 0)
        video = self.db.get_video_by_youtube_id(yid, slice_index) or {}

        copy_text = self._read_publication_text_file(copy_file, yid, f"{platform}文案")
        platform_title = ""
        if title_file is not None:
            platform_title = self._read_publication_text_file(title_file, yid, f"{platform}标题")

        title = platform_title or video.get("zh_title") or video.get("title") or yid
        zh_title = platform_title or video.get("zh_title") or title
        subtitle_text = ""
        if settings.enable_subtitle_censorship:
            subtitle_text = read_subtitle_text(self._OUT_DIR, yid, slice_index=slice_index)
            subtitle_source = "output"
            if not subtitle_text:
                subtitle_text = read_subtitle_text(self._ORIG_VIDEO_DIR, yid, slice_index=slice_index)
                subtitle_source = "original_video"
            if subtitle_text:
                logger.info("[%s] %s上传前审查包含字幕正文（%s chars, source=%s）", yid, platform, len(subtitle_text), subtitle_source)
            else:
                reason = f"{platform}上传前内容安全审查缺少可读字幕正文；平台任务已取消，禁止自动投递。"
                logger.error("[%s] %s", yid, reason)
                if platform == "快手":
                    self.db.update_kuaishou_publication_state(publication_id, "CANCELED", error_message=reason)
                elif platform == "抖音":
                    self.db.update_douyin_publication_state(publication_id, "CANCELED", error_message=reason)
                else:
                    logger.warning("[%s] 未知平台字幕审查缺失，无法更新平台账本：%s", yid, platform)
                return True

        if not self._check_censorship(
            yid,
            title,
            copy_text,
            zh_title=zh_title,
            slice_index=slice_index,
            subtitle_text=subtitle_text,
            stage="platform_publish",
            fail_closed=True,
            platform=platform,
        ):
            return False

        reason = f"{platform}上传前内容安全审查拦截；平台任务已取消，禁止自动重试。"
        logger.error("[%s] %s", yid, reason)
        if platform == "快手":
            self.db.update_kuaishou_publication_state(publication_id, "CANCELED", error_message=reason)
        elif platform == "抖音":
            self.db.update_douyin_publication_state(publication_id, "CANCELED", error_message=reason)
        else:
            logger.warning("[%s] 未知平台审查拦截，无法更新平台账本：%s", yid, platform)
        return True

    def _publish_claimed_kuaishou_publication(self, publication: Dict[str, Any]) -> bool:
        """执行已领取的快手任务；只有上传器完成作品管理回查才将账本置 PUBLISHED。"""
        publication_id = publication["id"]
        yid = publication["youtube_id"]
        slice_index = publication.get("slice_index", 0)
        if not self._is_public_publish_window("快手", yid, slice_index):
            self.db.update_kuaishou_publication_state(
                publication_id,
                "QUEUED",
                error_message="当前不在公开视频提交窗口，保留队列等待下一轮黄金时段。",
            )
            return False
        vertical, copy_file = self._kuaishou_asset_paths(yid, slice_index)
        if not vertical.is_file() or not copy_file.is_file():
            reason = f"快手投递产物缺失：video={vertical.is_file()} copy={copy_file.is_file()}"
            logger.error("[%s] %s", yid, reason)
            state = "CANCELED" if publication.get("source_kind") == "HISTORY" else "RETRYABLE_FAILED"
            self.db.update_kuaishou_publication_state(publication_id, state, error_message=reason)
            return False

        if self._platform_publication_censorship_blocked(publication, "快手", copy_file):
            return False

        upload_cmd = [
            self._VENV_PYTHON,
            str(self._PRJ_ROOT / "scripts" / "kuaishou_uploader.py"),
            "--video", str(vertical),
            "--copy", str(copy_file),
            "--state", str(self._OUT_DIR / "kuaishou_state.json"),
            "--fail-fast-login",
            "--calibrate-after-upload",
            "--prepare-description",
            "--publish",
        ]
        cover_file = self._resolve_cover_file(yid, slice_index)
        if cover_file:
            upload_cmd += ["--cover", str(cover_file)]

        if not settings.kuaishou_browser_headless:
            upload_cmd.append("--no-headless")
        try:
            result = self._run_tracked(
                upload_cmd,
                yid,
                slice_index=slice_index,
                text=True,
                capture_output=True,
                cwd=str(self._PRJ_ROOT),
                timeout=_KUAISHOU_UPLOAD_TIMEOUT_SEC,
            )
            if result.stdout:
                logger.debug("Kuaishou uploader stdout:\n%s", result.stdout)
            if result.stderr:
                logger.debug("Kuaishou uploader stderr:\n%s", result.stderr)
        except subprocess.TimeoutExpired:
            reason = "快手发布超过 25 分钟未完成；可能已提交但未能完成作品管理回查。"
            logger.error("[%s] %s", yid, reason)
            self.db.update_kuaishou_publication_state(publication_id, "UNCERTAIN", error_message=reason)
            return False
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode()
            if exc.returncode == 2:
                state = "RETRYABLE_FAILED"
                reason = "快手登录态失效，尚未开始公开发布；请重新登录后重试同一视频。"
            elif exc.returncode == 6:
                reason = "快手作品管理已可见，当前审核中；等待平台审核结果，不重新上传。"
                logger.info("[%s] %s", yid, reason)
                self.db.update_kuaishou_publication_state(publication_id, "UNDER_REVIEW", error_message=reason)
                self.send_telegram_msg(f"⏳ <b>Video Under Review</b>\nPlatform: Kuaishou\nYouTube ID: {yid}")
                return True
            elif exc.returncode == 7:
                state = "BANNED"
                reason = "快手账号已被封禁，无法访问创作者中心；停止快手投递并等待人工处理。"
            elif exc.returncode == 3:
                state = "UNCERTAIN"
                reason = "快手提交后未能在作品管理确认可见；请先人工核对，勿切换视频。"
            else:
                state = "RETRYABLE_FAILED"
                reason = f"快手上传器失败（exit {exc.returncode}）：{stderr[:500]}"
            logger.error("[%s] %s", yid, reason)
            self.db.update_kuaishou_publication_state(publication_id, state, error_message=reason)
            return False

        self.db.update_kuaishou_publication_state(
            publication_id,
            "PUBLISHED",
            error_message="快手作品管理已确认本次作品为已发布。",
        )
        self.send_telegram_msg(f"✅ <b>Video Published</b>\nPlatform: Kuaishou\nYouTube ID: {yid}")
        return True

    def _queue_and_publish_new_kuaishou_video(self, yid: str, slice_index: int) -> bool:
        """视频号发布完成后立即投递同一成片到快手；默认由特性开关关闭。"""
        if not settings.enable_kuaishou_browser_publishing:
            return True
        if self.db.is_blacklisted(yid):
            logger.warning("[%s] 已拉黑视频，跳过快手同步投递", yid)
            return False
        vertical, _ = self._kuaishou_asset_paths(yid, slice_index)
        if not vertical.is_file():
            logger.error("[%s] 快手同步投递缺少成片：%s", yid, vertical)
            return False
        publication = self.db.create_kuaishou_publication(
            yid,
            self._sha256_file(vertical),
            str(vertical),
            source_kind="NEW",
            slice_index=slice_index,
        )
        if publication["state"] == "PUBLISHED":
            logger.info("[%s] 相同成片已在快手作品管理确认发布，跳过重复投递", yid)
            return True
        if not self._is_public_publish_window("快手", yid, slice_index):
            logger.info("[%s] 快手新片已入队，等待公开视频提交窗口。", yid)
            return True
        claimed = self.db.claim_kuaishou_publication(publication["id"])
        if not claimed:
            logger.warning("[%s] 快手新片任务未能领取，保留账本等待下次重试", yid)
            return False
        return self._publish_claimed_kuaishou_publication(claimed)

    def _run_kuaishou_history_migration(self) -> None:
        """按每日限额迁移视频号历史作品；任一失败后固定在该视频，绝不切换下一条。"""
        if not settings.enable_kuaishou_browser_publishing:
            return
        if not self._is_public_publish_window("快手历史迁移"):
            return
        daily_limit = settings.kuaishou_history_daily_limit
        for candidate in self.db.get_unqueued_kuaishou_history_videos(limit=daily_limit):
            yid = candidate["youtube_id"]
            slice_index = candidate.get("slice_index", 0)
            vertical, _ = self._kuaishou_asset_paths(yid, slice_index)
            if not vertical.is_file():
                logger.warning("[%s] 历史快手迁移跳过：本地成片不存在", yid)
                continue
            self.db.create_kuaishou_publication(
                yid,
                self._sha256_file(vertical),
                str(vertical),
                source_kind="HISTORY",
                slice_index=slice_index,
            )

        while True:
            claimed = self.db.claim_next_kuaishou_history_publication(daily_limit=daily_limit)
            if not claimed:
                return
            if not self._publish_claimed_kuaishou_publication(claimed):
                latest = self.db.get_kuaishou_publication(
                    claimed["youtube_id"], slice_index=claimed.get("slice_index", 0)
                )
                if latest and latest.get("id") == claimed["id"] and latest.get("state") == "CANCELED":
                    logger.warning("[%s] 快手历史迁移任务已取消，继续处理下一条", claimed["youtube_id"])
                    continue
                logger.warning("[%s] 快手历史迁移未确认成功，停止本轮，保留同一视频供下次重试", claimed["youtube_id"])
                return

    def run_kuaishou_history_migration(self) -> None:
        """供早间定时任务调用：仅迁移快手历史作品，不执行视频加工或新片发布。"""
        logger.info("--- Starting Kuaishou History Migration ---")
        self._run_kuaishou_history_migration()
        logger.info("--- Kuaishou History Migration Completed ---")

    def reconcile_kuaishou_under_review(self) -> int:
        """只读回查快手审核中的作品；确认发布才落账，绝不再次上传或提交。"""
        if not settings.enable_kuaishou_browser_publishing:
            return 0
        reviewed = 0
        publications = self.db.get_kuaishou_publications_by_states(["UNDER_REVIEW"])
        for publication in publications:
            publication_id = publication["id"]
            yid = publication["youtube_id"]
            slice_index = publication.get("slice_index", 0)
            _, copy_file = self._kuaishou_asset_paths(yid, slice_index)
            if not copy_file.is_file():
                logger.error("[%s] 快手审核回查缺少文案文件：%s", yid, copy_file)
                continue
            verify_cmd = [
                self._VENV_PYTHON,
                str(self._PRJ_ROOT / "scripts" / "kuaishou_uploader.py"),
                "--copy", str(copy_file),
                "--state", str(self._OUT_DIR / "kuaishou_state.json"),
                "--fail-fast-login",
                "--verify-only",
            ]
            if not settings.kuaishou_browser_headless:
                verify_cmd.append("--no-headless")
            try:
                result = self._run_tracked(
                    verify_cmd,
                    yid,
                    slice_index=slice_index,
                    text=True,
                    capture_output=True,
                    cwd=str(self._PRJ_ROOT),
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                logger.warning("[%s] 快手审核回查超时，保留审核中状态", yid)
                continue
            except subprocess.CalledProcessError as exc:
                if exc.returncode == 6:
                    logger.info("[%s] 快手作品仍在审核中", yid)
                elif exc.returncode == 2:
                    logger.warning("[%s] 快手登录态失效，保留审核中状态等待下次核对", yid)
                elif exc.returncode == 7:
                    reason = "快手账号已被封禁，无法访问创作者中心；停止快手审核回查。"
                    logger.error("[%s] %s", yid, reason)
                    self.db.update_kuaishou_publication_state(
                        publication_id,
                        "BANNED",
                        error_message=reason,
                    )
                else:
                    logger.warning("[%s] 快手审核回查未确认状态（exit %s），保留审核中", yid, exc.returncode)
                continue
            if result.stdout:
                logger.debug("Kuaishou review verifier stdout:\n%s", result.stdout)
            if result.stderr:
                logger.debug("Kuaishou review verifier stderr:\n%s", result.stderr)
            self.db.update_kuaishou_publication_state(
                publication_id,
                "PUBLISHED",
                error_message="快手作品管理已确认本次作品为已发布。",
            )
            self.send_telegram_msg(f"✅ <b>Video Published</b>\nPlatform: Kuaishou\nYouTube ID: {yid}")
            reviewed += 1
        return reviewed

    def _retry_one_kuaishou_new_video(self) -> bool:
        """每日优先重试一条未确认的新片；失败时由调用者停止历史迁移，避免换片。"""
        if not settings.enable_kuaishou_browser_publishing:
            return True
        if not self._is_public_publish_window("快手新片重试"):
            return True
        claimed = self.db.claim_next_kuaishou_publication("NEW")
        if not claimed:
            return True
        return self._publish_claimed_kuaishou_publication(claimed)

    # ── 抖音创作者中心发布 ─────────────────────────────────────────────────────

    def _douyin_asset_paths(self, yid: str, slice_index: int) -> tuple[Path, Path]:
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
        return self._OUT_DIR / f"{prefix}_vertical.mp4", self._OUT_DIR / f"{prefix}_copy.txt"

    def _douyin_title_path(self, yid: str, slice_index: int) -> Path:
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
        return self._OUT_DIR / f"{prefix}_title.txt"

    def _publish_claimed_douyin_publication(self, publication: Dict[str, Any]) -> bool:
        """执行已领取的抖音任务；校准完成前上传器会 fail-closed，不会误点发布。"""
        if self._douyin_platform_halted:
            logger.warning("[DouyinHalt] 已停止本轮抖音自动动作，跳过新提交：%s", self._douyin_halt_reason)
            return False
        publication_id = publication["id"]
        yid = publication["youtube_id"]
        slice_index = publication.get("slice_index", 0)
        if not self._is_public_publish_window("抖音", yid, slice_index):
            self.db.update_douyin_publication_state(
                publication_id,
                "QUEUED",
                error_message="当前不在公开视频提交窗口，保留队列等待下一轮黄金时段。",
            )
            return False
        vertical, copy_file = self._douyin_asset_paths(yid, slice_index)
        title_file = self._douyin_title_path(yid, slice_index)
        cover_file = self._resolve_cover_file(yid, slice_index)
        if not vertical.is_file() or not copy_file.is_file() or not title_file.is_file() or not cover_file:
            reason = (
                f"抖音投递产物缺失：video={vertical.is_file()} "
                f"copy={copy_file.is_file()} title={title_file.is_file()} cover={bool(cover_file)}"
            )
            logger.error("[%s] %s", yid, reason)
            state = "CANCELED" if publication.get("source_kind") == "HISTORY" else "RETRYABLE_FAILED"
            self.db.update_douyin_publication_state(publication_id, state, error_message=reason)
            if publication.get("source_kind") == "HISTORY":
                logger.warning("[%s] 抖音历史迁移任务已取消，继续处理下一条", yid)
                return True
            self._halt_douyin_platform(yid, reason, publication=publication, state=state)
            return False

        if self._platform_publication_censorship_blocked(publication, "抖音", copy_file, title_file):
            self._halt_douyin_platform(
                yid,
                "抖音上传前内容安全审查拦截；疑似违禁或频道策略风险，禁止继续自动投递。",
                publication=publication,
                state="CANCELED",
            )
            return False

        upload_cmd = [
            self._VENV_PYTHON,
            str(self._PRJ_ROOT / "scripts" / "douyin_uploader.py"),
            "--video", str(vertical),
            "--copy", str(copy_file),
            "--title-file", str(title_file),
            "--state", str(self._OUT_DIR / "douyin_state.json"),
            "--fail-fast-login",
            "--prepare-description",
            "--publish",
            "--cover", str(cover_file),
        ]

        if not settings.douyin_browser_headless:
            upload_cmd.append("--no-headless")
        try:
            self._throttle_douyin_browser_action(f"{yid} 发布提交")
            result = self._run_tracked(
                upload_cmd,
                yid,
                slice_index=slice_index,
                text=True,
                capture_output=True,
                cwd=str(self._PRJ_ROOT),
                timeout=_DOUYIN_UPLOAD_TIMEOUT_SEC,
            )
            if result.stdout:
                logger.debug("Douyin uploader stdout:\n%s", result.stdout)
            if result.stderr:
                logger.debug("Douyin uploader stderr:\n%s", result.stderr)
        except subprocess.TimeoutExpired:
            reason = "抖音发布超过 25 分钟未完成；可能已提交但未能完成作品管理回查。"
            logger.error("[%s] %s", yid, reason)
            self.db.update_douyin_publication_state(publication_id, "UNCERTAIN", error_message=reason)
            self._halt_douyin_platform(yid, reason, publication=publication, state="UNCERTAIN")
            return False
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode()
            if exc.returncode == 2:
                state = "RETRYABLE_FAILED"
                reason = "抖音登录态失效，尚未开始公开发布；请重新登录后重试同一视频。"
            elif exc.returncode == 6:
                reason = "抖音已接受发布提交，当前按审核中处理；等待作品管理回查校准后确认最终发布。"
                logger.info("[%s] %s", yid, reason)
                self.db.update_douyin_publication_state(publication_id, "UNDER_REVIEW", error_message=reason)
                self.send_telegram_msg(f"⏳ <b>Video Under Review</b>\nPlatform: Douyin\nYouTube ID: {yid}")
                return True
            elif exc.returncode == 3:
                state = "RETRYABLE_FAILED"
                reason = "抖音发布前元信息、封面或自主声明闸门未能确认；本次未提交，修复后可重试。"
            elif exc.returncode == 7:
                state = "UNCERTAIN"
                reason = "抖音已点击最终发布但未能在作品管理确认可见；请先人工核对，勿切换视频。"
            elif exc.returncode == 4:
                state = "RETRYABLE_FAILED"
                reason = "抖音上传器尚未完成页面校准；本次没有触发发布。"
            else:
                state = "RETRYABLE_FAILED"
                reason = f"抖音上传器失败（exit {exc.returncode}）：{stderr[:500]}"
            logger.error("[%s] %s", yid, reason)
            self.db.update_douyin_publication_state(publication_id, state, error_message=reason)
            self._halt_douyin_platform(yid, reason, publication=publication, state=state)
            return False

        self.db.update_douyin_publication_state(
            publication_id,
            "UNDER_REVIEW",
            error_message="抖音浏览器已完成最终提交；等待作品管理页显示已发布后再确认最终成功。",
        )
        self.send_telegram_msg(f"⏳ <b>Video Under Review</b>\nPlatform: Douyin\nYouTube ID: {yid}")
        return True

    def _queue_and_publish_new_douyin_video(self, yid: str, slice_index: int = 0) -> bool:
        """为成片入库一条 NEW 抖音发布任务，并当即触发发布。"""
        if self._douyin_platform_halted:
            logger.warning("[%s] 抖音自动动作已熔断，跳过新片同步：%s", yid, self._douyin_halt_reason)
            return False
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
        vertical, copy_file = self._douyin_asset_paths(yid, slice_index)
        title_file = self._douyin_title_path(yid, slice_index)
        if not vertical.is_file() or not copy_file.is_file() or not title_file.is_file():
            logger.error("[%s] 无法入库抖音任务：投递产物不全", prefix)
            return False
        publication = self.db.get_douyin_publication(yid, slice_index=slice_index)
        if not publication:
            publication = self.db.create_douyin_publication(
                yid,
                self._sha256_file(vertical),
                str(vertical),
                source_kind="NEW",
                slice_index=slice_index,
            )
        if publication["state"] == "PUBLISHED":
            logger.info("[%s] 相同成片已在抖音确认发布，跳过重复投递", prefix)
            return True
        if not self._is_public_publish_window("抖音", yid, slice_index):
            logger.info("[%s] 抖音新片已入队，等待公开视频提交窗口。", prefix)
            return True
        publication_id = publication["id"]
        claimed = self.db.claim_douyin_publication(publication_id)
        if not claimed:
            logger.warning("[%s] 抖音任务 id=%s 当前无法 claim", prefix, publication_id)
            return False
        return self._publish_claimed_douyin_publication(claimed)

    def _run_douyin_history_migration(self) -> None:
        """按每日限额迁移历史作品到抖音；任一失败后固定在该视频。"""
        if not settings.enable_douyin_browser_publishing:
            return
        if self._douyin_platform_halted:
            logger.warning("[DouyinHalt] 已停止本轮抖音历史迁移：%s", self._douyin_halt_reason)
            return
        if not self._is_public_publish_window("抖音历史迁移"):
            return
        daily_limit = settings.douyin_history_daily_limit
        if daily_limit < 1:
            logger.info("[DouyinHistory] 历史迁移限额为 0，本轮不创建也不领取 HISTORY 任务。")
            return
        for candidate in self.db.get_platform_backfill_preview_candidates(
            "douyin",
            wall_street_since_upload_date=settings.platform_backfill_wall_street_since_upload_date,
            limit=daily_limit,
        ):
            yid = candidate["youtube_id"]
            slice_index = candidate.get("slice_index", 0)
            vertical, copy_file = self._douyin_asset_paths(yid, slice_index)
            title_file = self._douyin_title_path(yid, slice_index)
            if not vertical.is_file() or not copy_file.is_file() or not title_file.is_file():
                reason = (
                    f"历史抖音迁移本地产物不全：video={vertical.is_file()} "
                    f"copy={copy_file.is_file()} title={title_file.is_file()}"
                )
                logger.error("[%s] %s", yid, reason)
                missing_asset_digest = hashlib.sha256(f"douyin-missing-assets:{yid}:{slice_index}".encode()).hexdigest()
                publication = self.db.create_douyin_publication(
                    yid,
                    missing_asset_digest,
                    str(vertical),
                    source_kind="HISTORY",
                    slice_index=slice_index,
                )
                self.db.update_douyin_publication_state(publication["id"], "CANCELED", error_message=reason)
                continue
            self.db.create_douyin_publication(
                yid,
                self._sha256_file(vertical),
                str(vertical),
                source_kind="HISTORY",
                slice_index=slice_index,
            )

        while True:
            claimed = self.db.claim_next_douyin_history_publication(daily_limit=daily_limit)
            if not claimed:
                return
            self._notify_douyin_history_progress(claimed, daily_limit)
            if not self._publish_claimed_douyin_publication(claimed):
                logger.warning("[%s] 抖音历史迁移未确认成功，停止本轮，保留同一视频供下次重试", claimed["youtube_id"])
                return

    def _notify_douyin_history_progress(self, publication: Dict[str, Any], daily_limit: int) -> None:
        """每条抖音历史补发开始前汇报当前篇和队列进度。"""
        yid = publication.get("youtube_id", "")
        slice_index = int(publication.get("slice_index") or 0)
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
        video = self.db.get_video_by_youtube_id(yid, slice_index) or {}
        title = video.get("zh_title") or video.get("title") or prefix
        snapshot = self.db.get_douyin_history_progress_snapshot(daily_limit)
        claimed_today = int(snapshot.get("claimed_today", 0))
        queue_ready = int(snapshot.get("queue_ready", 0))
        remaining_today = int(snapshot.get("remaining_today", 0))
        logger.info(
            "[DouyinHistoryProgress] 当前发送 %s；今日已领取 %s/%s；剩余额度 %s；待发队列 %s",
            prefix,
            claimed_today,
            daily_limit,
            remaining_today,
            queue_ready,
        )
        self.send_telegram_msg(
            "🚚 <b>Douyin History Progress</b>\n"
            f"正在发送：{html.escape(prefix)}\n"
            f"标题：{html.escape(str(title)[:80])}\n"
            f"今日进度：{claimed_today}/{daily_limit}\n"
            f"今日剩余额度：{remaining_today}\n"
            f"待发队列：{queue_ready}"
        )

    def run_douyin_history_migration(self) -> None:
        """供早间定时任务调用：仅迁移抖音历史作品。"""
        logger.info("--- Starting Douyin History Migration ---")
        self._reset_douyin_run_guard()
        self._run_douyin_history_migration()
        logger.info("--- Douyin History Migration Completed ---")

    def reconcile_douyin_under_review(self) -> int:
        """只读回查抖音审核中的作品；确认发布才落账。"""
        if not settings.enable_douyin_browser_publishing:
            return 0
        if self._douyin_platform_halted:
            logger.warning("[DouyinHalt] 已停止本轮抖音审核回查：%s", self._douyin_halt_reason)
            return 0
        reviewed = 0
        publications = self.db.get_douyin_publications_by_states(["UNDER_REVIEW"])
        reviewable_publications = [
            publication for publication in publications
            if publication.get("source_kind") != "HISTORY"
        ]
        skipped_history = len(publications) - len(reviewable_publications)
        if skipped_history:
            logger.info("跳过 %s 条历史迁移 UNDER_REVIEW 回查；历史任务当前已暂停。", skipped_history)
        max_per_run = max(0, int(settings.douyin_review_max_per_run or 0))
        if max_per_run and len(reviewable_publications) > max_per_run:
            logger.warning(
                "抖音 UNDER_REVIEW 待回查 %s 条，本轮仅检查前 %s 条，避免连续访问创作者中心。",
                len(reviewable_publications),
                max_per_run,
            )
        for publication in reviewable_publications[:max_per_run or len(reviewable_publications)]:
            publication_id = publication["id"]
            yid = publication["youtube_id"]
            slice_index = publication.get("slice_index", 0)
            _, copy_file = self._douyin_asset_paths(yid, slice_index)
            if not copy_file.is_file():
                reason = f"抖音审核回查缺少文案文件：{copy_file}"
                logger.error("[%s] %s", yid, reason)
                self._halt_douyin_platform(yid, reason, publication=publication, state="UNDER_REVIEW")
                break
            verify_cmd = [
                self._VENV_PYTHON,
                str(self._PRJ_ROOT / "scripts" / "douyin_uploader.py"),
                "--copy", str(copy_file),
                "--state", str(self._OUT_DIR / "douyin_state.json"),
                "--fail-fast-login",
                "--verify-only",
            ]
            if not settings.douyin_browser_headless:
                verify_cmd.append("--no-headless")
            try:
                self._throttle_douyin_browser_action(f"{yid} 审核回查")
                result = self._run_tracked(
                    verify_cmd,
                    yid,
                    slice_index=slice_index,
                    text=True,
                    capture_output=True,
                    cwd=str(self._PRJ_ROOT),
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                reason = "抖音审核回查超时，保留审核中状态；停止本轮后续回查，避免连续访问。"
                logger.warning("[%s] %s", yid, reason)
                self._halt_douyin_platform(yid, reason, publication=publication, state="UNDER_REVIEW")
                break
            except subprocess.CalledProcessError as exc:
                if exc.returncode == 6:
                    logger.info("[%s] 抖音作品仍在审核中", yid)
                    continue
                elif exc.returncode == 2:
                    reason = "抖音登录态失效，保留审核中状态；停止本轮后续自动回查。"
                elif exc.returncode == 4:
                    reason = (
                        "抖音作品已提交但当前机器尚未完成作品管理回查校准；"
                        "转为 UNCERTAIN 等待人工核验，避免每轮重复打开创作者中心。"
                    )
                    self.db.update_douyin_publication_state(
                        publication_id,
                        "UNCERTAIN",
                        error_message=reason,
                    )
                    logger.warning("[%s] %s", yid, reason)
                    self._halt_douyin_platform(yid, reason, publication=publication, state="UNCERTAIN")
                    break
                else:
                    reason = f"抖音审核回查未确认状态（exit {exc.returncode}），保留审核中；停止本轮后续自动回查。"
                logger.warning("[%s] %s", yid, reason)
                self._halt_douyin_platform(yid, reason, publication=publication, state="UNDER_REVIEW")
                break
            if result.stdout:
                logger.debug("Douyin review verifier stdout:\n%s", result.stdout)
            if result.stderr:
                logger.debug("Douyin review verifier stderr:\n%s", result.stderr)
            self.db.update_douyin_publication_state(publication_id, "PUBLISHED")
            self.send_telegram_msg(f"✅ <b>Video Published</b>\nPlatform: Douyin\nYouTube ID: {yid}")
            reviewed += 1
        return reviewed

    def _retry_one_douyin_new_video(self) -> bool:
        """每日优先重试一条抖音未确认的新片；失败则保留同一视频下次再试。"""
        if not settings.enable_douyin_browser_publishing:
            return True
        if self._douyin_platform_halted:
            logger.warning("[DouyinHalt] 已停止本轮抖音新片重试：%s", self._douyin_halt_reason)
            return False
        if not self._is_public_publish_window("抖音新片重试"):
            return True
        claimed = self.db.claim_next_douyin_publication("NEW")
        if not claimed:
            return True
        return self._publish_claimed_douyin_publication(claimed)

    def _queue_missing_douyin_new_publications(self) -> int:
        """补齐最近微信已发布但抖音 NEW 账本缺失的新片，防止同步入口漏建任务。"""
        if not settings.enable_douyin_browser_publishing:
            return 0
        max_per_run = max(1, int(settings.douyin_new_sync_max_per_run or 1))
        lookback_hours = max(1, int(settings.douyin_new_sync_lookback_hours or 24))
        queued = 0
        for video in self.db.get_unqueued_douyin_new_videos(
            lookback_hours=lookback_hours,
            limit=max_per_run,
        ):
            yid = video["youtube_id"]
            slice_index = int(video.get("slice_index") or 0)
            prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
            vertical, copy_file = self._douyin_asset_paths(yid, slice_index)
            title_file = self._douyin_title_path(yid, slice_index)
            cover_file = self._resolve_cover_file(yid, slice_index)
            if not vertical.is_file() or not copy_file.is_file() or not title_file.is_file() or not cover_file:
                reason = (
                    f"抖音 NEW 漏同步产物缺失：video={vertical.is_file()} "
                    f"copy={copy_file.is_file()} title={title_file.is_file()} cover={bool(cover_file)}"
                )
                logger.error("[%s] %s", prefix, reason)
                self.send_telegram_msg(
                    "⚠️ <b>Douyin NEW sync skipped</b>\n"
                    f"YouTube ID: {html.escape(prefix)}\n"
                    f"Reason: {html.escape(reason)}"
                )
                continue
            self.db.create_douyin_publication(
                yid,
                self._sha256_file(vertical),
                str(vertical),
                source_kind="NEW",
                slice_index=slice_index,
            )
            queued += 1
            logger.info("[%s] 已补齐抖音 NEW 同步队列。", prefix)
        if queued:
            self.send_telegram_msg(f"🚚 <b>Douyin NEW Sync</b>\n已补齐漏同步队列：{queued} 条")
        return queued

    def _run_douyin_new_sync(self) -> bool:
        """按上限同步抖音 NEW 队列；任一失败停止，保留同一视频下轮重试。"""
        if not settings.enable_douyin_browser_publishing:
            return True
        if self._douyin_platform_halted:
            logger.warning("[DouyinHalt] 已停止本轮抖音新片同步：%s", self._douyin_halt_reason)
            return False
        if not self._is_public_publish_window("抖音新片同步"):
            return True
        self._queue_missing_douyin_new_publications()
        max_per_run = max(1, int(settings.douyin_new_sync_max_per_run or 1))
        for index in range(max_per_run):
            claimed = self.db.claim_next_douyin_publication("NEW")
            if not claimed:
                return True
            yid = claimed.get("youtube_id", "")
            logger.info(
                "[DouyinNewSync] 当前发送 %s；本轮 %s/%s",
                yid,
                index + 1,
                max_per_run,
            )
            if not self._publish_claimed_douyin_publication(claimed):
                logger.warning("[%s] 抖音新片同步未确认成功，停止本轮，保留同一视频供下次重试。", yid)
                return False
        return True

    def _check_censorship(
        self,
        yid: str,
        title: str,
        description: str = "",
        zh_title: str = "",
        slice_index: int = 0,
        subtitle_text: str = "",
        *,
        stage: str = "pipeline",
        fail_closed: bool = False,
        platform: str = "",
    ) -> bool:
        """执行内容安全审查（违法层）+ 频道内容策略检查（运营层）。

        [Claude_Opus_4.8] 症结 8 修复：新增 subtitle_text（Whisper 转录的 .ass 字幕正文）。
        该文本仅并入违法层 P0/P1/P2（精确词匹配，对数万字长文本安全），
        刻意不并入 CP 频道策略层——CP 的「国名+冲突词」全文共现判定在长转录上几乎必然误杀。
        调用方仅在 settings.enable_subtitle_censorship 开启时才读取并传入此参数。

        [Claude_Opus_4.8] v3.14.0 BUG-1 修复：新增 slice_index 并透传到每一处 db.* 调用。
        此前所有写入默认 slice_index=0（父行），切片命中违禁词时会污染父视频状态/分数，
        且切片本行不被置 FAILED 导致漏审/卡死。调用方必须传入当前任务的 slice_index。


        [Gemini_2.5_Flash_planning] v2.11.0 修复：
        - 修复 zh_text 参数 Bug：原来错误地将英文 title 传给 zh 通道，现在使用 zh_title。
        - 集成频道内容策略层（check_channel_policy），由 enable_channel_policy_filter 控制。
        - 手动触发与自动触发统一走同一套审查流程，无例外。

        [Gemini_3.5_Flash_planning] v2.11.1 修复：
        - 修复测试用例或手动视频无 zh_title 时的中文漏检问题。若 zh_title 为空，但 original title 包含中文，则 fallback 到 title。

        返回 True 表示命中（任意层）→ 需要拦截/中断，False 表示全部通过。
        """
        # [Claude_Opus_4.8 架构B] 审查执行已抽至 CensorshipService（内聚单元，可独立测试）。
        # 这里按调用方既有契约（仅需 self.db + self.send_telegram_msg）即时构造，零状态。
        return CensorshipService(self.db, self.send_telegram_msg).check(
            yid, title, description, zh_title=zh_title,
            slice_index=slice_index, subtitle_text=subtitle_text,
            stage=stage, fail_closed=fail_closed, platform=platform,
        )

    # ── 主处理流程 ────────────────────────────────────────────────────────────

    def _process_single_video(self, video: Dict[str, Any]):
        # [Claude_Opus_4.8] graceful_truncate_title 已下沉至 utils.text_utils 并在模块顶部 import，
        # 消除此前 sys.path 注入 scripts/ 反向 import copywriter 的 DAG 违规。
        yid   = video['youtube_id']
        title = video['title']
        url   = f"https://youtu.be/{yid}"
        trim_start = video.get('trim_start')
        trim_end   = video.get('trim_end')
        slice_index = video.get('slice_index', 0)
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid

        # [Claude_Sonnet_4.6_Thinking_planning] BUG-1 修复: signal.signal() 只能在主线程调用。
        # 此方法通过 daemon 线程执行，signal 注册已移至 app.py startup_event()。
        # [Claude_Sonnet_4.6_Thinking_planning] BUG-2 修复: 每个视频开始时重置标志位。
        # 若不重置，一旦 video1 收到 SIGTERM，后续所有视频将在首个 checkpoint 立即中断。
        global _sigterm_received
        _sigterm_received = False  # 每个视频独立的中断状态

        lock_path = self._OUT_DIR / "pipeline.lock"
        logger.info(f"[Lock] Waiting for pipeline lock to process {prefix}...")
        lock_file = None
        try:
            try:
                lock_file = open(lock_path, "w")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                logger.info(f"[Lock] Acquired pipeline lock. Processing {prefix}...")
            except Exception as lock_err:
                logger.error(f"Failed to acquire pipeline lock for {prefix}: {lock_err}")
                self.db.update_video_status(yid, "FAILED", error_msg=f"Pipeline lock error: {lock_err}", slice_index=slice_index)
                self._notify_failed(yid, title, f"Lock error: {lock_err}", slice_index=slice_index)
                return

            # ── 0. CENSORSHIP PRE-CHECK ───────────────────────────────────────
            # [Gemini_2.5_Flash_planning] v2.11.0: 手动/自动任务统一走同一套审查流程
            # zh_title 来自 DB，爬虫入库时已翻译；手动添加视频若翻译任务尚未完成则为空（回退到英文通道）
            zh_title_for_check = video.get('zh_title') or ""
            if self._check_censorship(yid, title, zh_title=zh_title_for_check, slice_index=slice_index):
                return

            try:
                # ── 1. DOWNLOADING / SLICING ──────────────────────────────────────
                if settings.enable_sigterm_kill and _sigterm_received:
                    logger.warning(f"[SIGTERM] Checkpoint before DOWNLOADING: aborting {prefix}")
                    raise InterruptedError("SIGTERM received before download/slice start")

                if slice_index > 0:
                    # 子任务：无需下载，只需从父任务的视频执行切片操作
                    target_file = self._OUT_DIR / f"{prefix}.mp4"
                    if target_file.exists() and target_file.stat().st_size > 50_000:
                        logger.info(f"[SKIP] Slice checkpoint: {target_file.name}")
                    else:
                        parent_file = self._find_downloaded_video(yid)
                        if not parent_file:
                            raise FileNotFoundError(f"Parent video file not found for slice {prefix}")
                        
                        self.db.update_video_status(yid, "DOWNLOADING", slice_index=slice_index)
                        from .processors.slicer import VideoSlicer
                        slicer = VideoSlicer(Path(parent_file), self._OUT_DIR)
                        
                        # 毫秒精度寻求解析
                        trim_start_val = float(video.get("trim_start", 0.0) or 0.0)
                        trim_end_val = float(video.get("trim_end", 0.0) or 0.0)
                        
                        logger.info(f"Slicing parent {parent_file} -> {target_file} ({trim_start_val} -> {trim_end_val})")
                        success = slicer.slice_video(trim_start_val, trim_end_val, Path(target_file))
                        if not success or not target_file.exists():
                            raise RuntimeError(f"Failed to slice parent video for {prefix}")
                else:
                    # 主任务：常规下载逻辑
                    existing = self._find_downloaded_video(yid)
                    if existing:
                        logger.info(f"[SKIP] Download checkpoint: {existing}")
                        self.db.update_video_status(yid, "DOWNLOADING", slice_index=slice_index)
                        target_file = existing
                    else:
                        self.db.update_video_status(yid, "DOWNLOADING", slice_index=slice_index)
                        logger.info(f"Downloading {yid}...")
                        # [Gemini_3.5_Flash_planning] v3.1.0: 针对代理环境下的 SSL UNEXPECTED_EOF_WHILE_READING 报错，
                        # 引入 --downloader curl 将大文件下载转交给 curl 处理，其代理兼容性和 TLS 握手比 python ssl 模块更稳定。
                        dl_cmd = [
                            self._VENV_YTDLP,
                            # [Claude_Opus_4.8] v3.16.0: 优先 H.264(avc) 视频流，规避 AV1(av01)。
                            # imageio-ffmpeg 内置的 AOM AV1 解码器解码 YouTube AV1 流时会间歇性
                            # SIGSEGV，导致后续 _burn_subtitles(ffmpeg) 渲染崩溃。YouTube ≤720p
                            # 始终提供 avc1，故首选 vcodec^=avc；仅当无 avc 可用时回退原选择器
                            # （可能落到 av01）。-S vcodec:h264 进一步保证回退分支也优先 H.264。
                            "-f", (
                                "bestvideo[height<=720][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/"
                                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                                "best[ext=mp4]/best"
                            ),
                            "-S", "vcodec:h264",
                            *settings.get_yt_cookie_args(),
                            "--write-description",
                            "--write-info-json",  # 新增：写 info.json 便于 chapters 提取
                            "--remote-components", "ejs:github",
                            "--downloader", "curl",
                            # [Gemini_3.5_Flash_planning] v3.8.1: 最低速度限制从 50KB/s 降低为 10KB/s (10000) 持续 30s，防止音频下载被 YouTube 限速导致无限重试
                            "--downloader-args", "curl:--retry 10 --retry-delay 3 --retry-all-errors --speed-limit 10000 --speed-time 30 --connect-timeout 15",
                            url, "-o", str(self._OUT_DIR / f"{yid}.%(ext)s"),
                        ]

                        # [Claude_Sonnet_4.6_Thinking_planning] v2.12.0: 精准区间下载
                        # 若有裁剪参数，使用 --download-sections 让 yt-dlp 只下载必要片段，
                        # 避免先完整下载 2 小时视频再裁剪的巨大浪费。
                        # --force-keyframes-at-cuts 确保切割点关键帧精确（需 yt-dlp >= 2022.10.04）。
                        used_download_sections = False
                        if trim_start or trim_end:
                            _sec_start = trim_start or "0"
                            _sec_end   = trim_end   or "inf"
                            dl_cmd += [
                                "--download-sections", f"*{_sec_start}-{_sec_end}",
                                "--force-keyframes-at-cuts",
                            ]
                            used_download_sections = True
                            logger.info(
                                f"[PARTIAL DL] Using --download-sections *{_sec_start}-{_sec_end} for {yid}"
                            )

                        # [Claude_Sonnet_4.6_Thinking_planning] v3.3.0: 动态代理环境构建
                        # 检测系统代理可用性：可达则注入代理，不可达则不注入
                        subprocess_env = _build_subprocess_env()

                        # [Claude_Sonnet_4.6_Thinking_planning] v3.9.0: 日本节点切换（Clash Mi API）
                        # Clash Mi 基于 macOS Network Extension，无法动态开放新端口，
                        # 因此通过 API 临时切换代理组到日本 URLTest 组来提速，
                        # 下载结束（含异常）后自动还原原节点。
                        # 配置项：CLASH_API_SECRET + CLASH_DOWNLOAD_NODE（见 .env）
                        if settings.clash_download_node:
                            logger.info(
                                f"[Clash] 切换到日本节点: {settings.clash_download_node}"
                            )
                        with settings.clash_switch_node():
                            self._run_tracked(dl_cmd, yid, slice_index=slice_index, capture_output=True,
                                              cwd=str(self._PRJ_ROOT), env=subprocess_env)
                        target_file = self._find_downloaded_video(yid)
                        if not target_file:
                            raise FileNotFoundError(f"No video file found for {yid} after download")
                        logger.info(f"Downloaded: {target_file}")

                        # [Claude_Sonnet_4.6_Thinking_planning] v3.6.0: 归档原始视频到 original_video/ 子目录
                        # 注意：归档后 target_file 路径变更，必须重新获取
                        self._archive_original_video(yid)
                        target_file = self._find_downloaded_video(yid)
                        if not target_file:
                            raise FileNotFoundError(f"No video file found for {yid} after archiving")

                        # [Claude_Sonnet_4.6_Thinking_planning] v2.12.0: 仅在未使用 --download-sections
                        # 时才执行 ffmpeg 二次裁剪（used_download_sections=True 时 yt-dlp 已完成裁剪）。
                        if (trim_start or trim_end) and not used_download_sections:
                            logger.info(f"Trimming main video {yid} to range: {trim_start or '0'} -> {trim_end or 'End'}")
                            temp_trimmed = self._OUT_DIR / f"{yid}_trimmed.mp4"

                            import imageio_ffmpeg
                            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

                            trim_cmd = [ffmpeg_exe, "-y"]
                            if trim_start:
                                trim_cmd += ["-ss", trim_start]
                            if trim_end:
                                trim_cmd += ["-to", trim_end]
                            trim_cmd += ["-i", str(target_file), "-c", "copy", str(temp_trimmed)]

                            res = subprocess.run(trim_cmd, capture_output=True, text=True, cwd=str(self._PRJ_ROOT))
                            if res.returncode != 0:
                                raise subprocess.CalledProcessError(res.returncode, trim_cmd, output=res.stdout, stderr=res.stderr)

                            if temp_trimmed.exists():
                                Path(target_file).unlink()
                                temp_trimmed.rename(target_file)

                # ── 1a. CHAPTERS EXTRACTION (仅针对主任务) ────────────────────────
                if slice_index == 0:
                    enable_chapters = getattr(settings, "enable_chapters_slicing", True)
                    if video.get("disable_slicing") == 1:
                        enable_chapters = False
                        logger.info(f"[Pipeline] Slicing explicitly disabled for {yid} (disable_slicing=1)")
                    
                    if enable_chapters:
                        from .processors.chapters_extractor import ChaptersExtractor
                        extractor = ChaptersExtractor()
                        info_json_path = self._OUT_DIR / f"{yid}.info.json"
                        
                        chapters = []
                        if info_json_path.exists():
                            chapters = extractor.extract_from_metadata(info_json_path)
                            
                        if len(chapters) > 1:
                            logger.info(f"Found {len(chapters)} native chapters. Slicing enabled.")
                            parent_video = self.db.get_video_by_youtube_id(yid, 0)
                            parent_id = parent_video["id"] if parent_video else None
                            
                            # [Unknown_Model_planning] 强制先清理已存在的陈旧切片，规避 Unique constraint 冲突
                            if parent_id is not None:
                                logger.info(f"Purging old slices for parent task ID {parent_id} before recreation.")
                                self.db.delete_slices_by_parent_id(parent_id)

                            slice_tasks = []
                            for idx, ch in enumerate(chapters, start=1):
                                prefix_title = graceful_truncate_title(title, max_len=6)
                                ch_title = ch["title"]
                                import re as _re
                                ch_title_clean = _re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', ch_title).strip()
                                sub_title = f"【{prefix_title} {idx:02d}】{ch_title_clean}"
                                sub_title = graceful_truncate_title(sub_title, max_len=16)
                                
                                slice_tasks.append({
                                    "youtube_id": yid,
                                    "slice_index": idx,
                                    "parent_id": parent_id,
                                    "title": sub_title,
                                    "channel_id": video.get("channel_id", ""),
                                    "score": video.get("score", 0),
                                    "source": video.get("source", "AUTO"),
                                    "duration_sec": int(ch["end_time"] - ch["start_time"]),
                                    "trim_start": f"{ch['start_time']:.3f}",
                                    "trim_end": f"{ch['end_time']:.3f}",
                                    "disable_slicing": 1,  # [Unknown_Model_planning] 切片任务本身必须禁用分片
                                })
                                
                            # [Unknown_Model_planning] 强制抛出异常以防默默回退整视频处理
                            if not self.db.batch_add_videos(slice_tasks):
                                raise RuntimeError(f"batch_add_videos failed to insert slice tasks for parent {yid}")
                                
                            self.db.update_video_status(yid, "SEGMENTED", slice_index=0)
                            self.send_telegram_msg(
                                f"📦 <b>Video Segmented</b>\nParent: {title}\n"
                                f"Generated {len(slice_tasks)} slices to publish."
                            )
                            return

                # ── 1b. CENSORSHIP DESC CHECK ─────────────────────────────────────
                desc_path = self._OUT_DIR / f"{yid}.description"
                description = ""
                if desc_path.exists():
                    try:
                        description = desc_path.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
                if self._check_censorship(yid, title, description, zh_title=zh_title_for_check, slice_index=slice_index):
                    return

                # ── 2a. COPYWRITING ────────────────────────────────────────────────
                # [Claude_Sonnet_4.6_Thinking_planning] v2.8.0 前移至 TRANSCRIBING 之前：
                # Copywriter 仅依赖 YouTube ID + 原始标题 + description，不需要 transcript。
                # 先生成中文短标题，TRANSCRIBING 步骤再读取，确保视频头部标题与封面一致。
                copy_file = self._OUT_DIR / f"{prefix}_copy.txt"
                title_file = self._OUT_DIR / f"{prefix}_title.txt"
                category_file = self._OUT_DIR / f"{prefix}_category.txt"
                # [Gemini_2.5_Pro_planning] v3.0.0: label 也是 checkpoint 校验条件。
                # 旧视频（copywriter v1.11.0 前处理）有 copy+title 但无 label，
                # 原 checkpoint 会跳过 copywriter → cover 生成时读不到 label → 封面无丝带。
                # 修复：三者同时存在才算命中 checkpoint；任一缺失则强制重跑 copywriter。
                label_file = self._OUT_DIR / f"{prefix}_label.txt"

                if copy_file.exists() and title_file.exists() and label_file.exists():
                    logger.info(f"[SKIP] Copywriting checkpoint: {copy_file.name} (label ok)")
                    self.db.update_video_status(yid, "COPYWRITING", slice_index=slice_index)
                else:
                    _reason = "label missing, re-generating" if (copy_file.exists() and title_file.exists()) else "first run"
                    self.db.update_video_status(yid, "COPYWRITING", slice_index=slice_index)
                    logger.info(f"Generating WeChat copy for {prefix}... ({_reason})")
                    copy_cmd = [
                        self._VENV_PYTHON,
                        str(self._PRJ_ROOT / "scripts" / "copywriter.py"),
                        "--youtube-id", prefix,
                        "--title", title,
                        "--desc-file", str(self._OUT_DIR / f"{yid}.description"),
                    ]
                    self._run_tracked(copy_cmd, yid, slice_index=slice_index, capture_output=True,
                                      cwd=str(self._PRJ_ROOT))

                # ── 2b. TRANSCRIBING & RENDERING ──────────────────────────────────
                # [Claude_Sonnet_4.6_Thinking_planning] v2.8.0 读取 copywriter 生成的中文短标题
                # 作为渲染标题，使视频头部 title 与封面 title 保持一致。
                render_title = title  # fallback：若 title_file 不存在则用 DB 原始标题
                if title_file.exists():
                    try:
                        _rt = title_file.read_text(encoding="utf-8").strip()
                        if _rt:
                            render_title = _rt
                    except Exception:
                        pass

                # [Claude_Sonnet_4.6_Thinking_planning] v2.9.0 多切片视频：在视频头部标题追加集数进度
                # 格式："{短标题} {当前集}/{总集数}"，如 "AI写代码 3/9"
                # 整片视频（slice_index == 0）不追加，避免干扰。
                if slice_index > 0:
                    all_slices = self.db.get_slices_by_parent_yid(yid)
                    total_cnt = len(all_slices) if all_slices else 1
                    render_title = f"{render_title} {slice_index}/{total_cnt}"
                logger.info(f"[Render] Using title for video header: {render_title!r}")


                vertical = self._OUT_DIR / f"{prefix}_vertical.mp4"
                # [Claude_Sonnet_4.6_Thinking_planning] v3.5.0 Transcribe Checkpoint 缓存校验增强：
                # 仅检测 _vertical.mp4 存在不够，当字幕渲染代码升级后旧格式视频会被错误地复用。
                # 策略：检查关联的 .ass 文件是否包含双语标记（Georgia 字体标签），
                # 若缺失则说明是旧格式单语缓存，强制删除后重新渲染。
                _ass_file = self._OUT_DIR / f"{prefix}.ass"
                _cache_valid = False
                if vertical.exists() and vertical.stat().st_size > 1_000_000:
                    _cache_valid = True  # 默认视为有效
                    # [Claude_Opus_4.8] v3.17.0: _vertical.mp4 完整性校验（不止看体积）。
                    # 历史根因：_burn_subtitles 渲染中途崩溃（如 AV1 解码 SIGSEGV）会留下
                    # 体积 >1MB 但缺失 moov atom 的截断文件，旧校验仅看体积 → 误判为有效缓存 →
                    # 跳过重渲并把损坏视频直接送入发布。此处用 ffprobe 读取 duration 验证文件可解析，
                    # 不可解析（截断/损坏）则判缓存失效，强制重渲。
                    try:
                        from .utils.video_metadata import get_video_duration_ffprobe
                        if get_video_duration_ffprobe(vertical) <= 0:
                            raise ValueError("duration<=0")
                    except Exception as _e:
                        logger.warning(
                            f"[CacheInvalid] {vertical.name} 无法解析（疑似截断/损坏: {_e}），强制重渲 {prefix}"
                        )
                        _cache_valid = False
                    if _cache_valid and _ass_file.exists():
                        try:
                            _ass_content = _ass_file.read_text(encoding="utf-8", errors="ignore")
                            # Georgia 字体标签是双语字幕的必要标志（单语版本不含此标签）
                            if "fnGeorgia" not in _ass_content:
                                logger.warning(
                                    f"[CacheInvalid] {_ass_file.name} missing bilingual marker "
                                    f"(fnGeorgia), forcing re-render for {prefix}"
                                )
                                _cache_valid = False
                        except Exception as _e:
                            logger.warning(f"[CacheCheck] Failed to read {_ass_file.name}: {_e}")
                    else:
                        # .ass 文件不存在但 _vertical.mp4 存在，说明 .ass 已被清理或历史遗留
                        # 保守起见：若 .ass 不存在则信任 _vertical.mp4（可能是手动渲染）
                        pass

                if _cache_valid:
                    logger.info(f"[SKIP] Transcribe checkpoint (bilingual verified): {vertical.name}")
                    self.db.update_video_status(yid, "TRANSCRIBING", slice_index=slice_index)
                else:
                    # 强制清除过期/无效缓存
                    if vertical.exists():
                        try:
                            vertical.unlink()
                            logger.info(f"[CacheEvict] Deleted stale vertical: {vertical.name}")
                        except Exception as _e:
                            logger.warning(f"[CacheEvict] Failed to delete {vertical.name}: {_e}")
                    if _ass_file.exists():
                        try:
                            _ass_file.unlink()
                            logger.info(f"[CacheEvict] Deleted stale ASS: {_ass_file.name}")
                        except Exception as _e:
                            logger.warning(f"[CacheEvict] Failed to delete {_ass_file.name}: {_e}")
                    # 执行渲染
                    if settings.enable_sigterm_kill and _sigterm_received:
                        logger.warning(f"[SIGTERM] Checkpoint before TRANSCRIBING: aborting {prefix}")
                        raise InterruptedError("SIGTERM received before transcription")
                    self.db.update_video_status(yid, "TRANSCRIBING", slice_index=slice_index)
                    render_cmd = [
                        "nice", "-n", "19",
                        self._VENV_PYTHON, "-m", "cli.main", "auto-caption",
                        str(target_file), "--vertical", "--bilingual", "--title", render_title,
                        "--output", str(vertical),  # [Gemini_3.5_Flash_planning] 指定输出路径，去除可能携带的格式后缀
                    ]
                    # [Claude_Opus_4.8] 源视频「发布日期」毛玻璃戳：仅在开关开启且能取到合法 upload_date 时注入。
                    # 主视频行自带 upload_date；切片行不带 → 回退父行(slice_index=0)。缺失/非法则跳过（不烧戳）。
                    if settings.enable_source_date_stamp:
                        from .processors.date_stamp import format_upload_date
                        _raw_upload = video.get("upload_date")
                        if not _raw_upload and slice_index:
                            _parent_row = self.db.get_video_by_youtube_id(yid, 0)
                            _raw_upload = _parent_row.get("upload_date") if _parent_row else None
                        _src_date = format_upload_date(_raw_upload)
                        if _src_date:
                            render_cmd += ["--source-date", _src_date]
                            logger.info(f"[DateStamp] {prefix} 源发布日期戳: {_src_date}")
                        else:
                            logger.info(f"[DateStamp] {prefix} 无合法 upload_date({_raw_upload!r})，跳过日期戳")
                    # [Claude_Sonnet_4.6_Thinking_planning] v2.10.0: 按需附加 TTS 参数
                    # 只有 tts_provider 非空时才开启，默认流程不开启 TTS
                    _tts_provider = video.get("tts_provider") or None
                    if _tts_provider == "cosyvoice":
                        render_cmd += ["--tts-cosy"]
                        logger.info(f"[TTS] Activating CosyVoice for {prefix} (stored tts_provider={_tts_provider})")
                    elif _tts_provider == "edge":
                        render_cmd += ["--tts"]
                        logger.info(f"[TTS] Activating Edge TTS for {prefix} (stored tts_provider={_tts_provider})")
                    elif _tts_provider:
                        logger.warning(f"[TTS] Unknown tts_provider={_tts_provider!r} for {prefix}, skipping TTS")
                    render_env = os.environ.copy()
                    render_env["PYTHONPATH"] = str(self._SRC_DIR)
                    try:
                        self._run_tracked(
                            render_cmd,
                            yid,
                            slice_index=slice_index,
                            capture_output=True,
                            cwd=str(self._PRJ_ROOT),
                            env=render_env,
                            timeout=_AUTO_CAPTION_TIMEOUT_SEC,
                        )
                    except subprocess.TimeoutExpired:
                        logger.error(
                            f"Auto-caption timed out for {prefix} after {_AUTO_CAPTION_TIMEOUT_SEC}s."
                        )
                        self.db.update_video_status(
                            yid,
                            "FAILED",
                            error_msg=(
                                "字幕转录/翻译/渲染超时（>45分钟）并已被系统终止。"
                                "通常是 Whisper、翻译质量守卫或 FFmpeg 渲染阶段异常拖长；"
                                "请查看 translation_quality 报告与 pipeline.log 后再点「重试」。"
                            ),
                            slice_index=slice_index,
                        )
                        self.send_telegram_msg(
                            f"⚠️ <b>Auto-caption timed out</b>\n"
                            f"Title: {render_title}\n"
                            f"Renderer exceeded {_AUTO_CAPTION_TIMEOUT_SEC // 60} minutes and was terminated."
                        )
                        return


                # ── 2c. CENSORSHIP COPYWRITING CHECK ──────────────────────────────
                copy_content = ""
                if copy_file.exists():
                    try:
                        copy_content = copy_file.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass

                short_title = title
                if title_file.exists():
                    try:
                        short_title = title_file.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass

                # [Gemini_2.5_Flash_planning] v2.11.0: 文案检测使用 AI 生成的中文短标题作为 zh_title
                # short_title 此时已是文案阶段生成的中文标题，直接作为 zh 通道输入
                # [Claude_Opus_4.8] v3.19.0 症结 8 修复：此处已在 2b 渲染之后，.ass 字幕正文就绪。
                # 当 enable_subtitle_censorship 开启时，读取转录字幕全文一并送审，闭合
                # 「标题/文案干净但语音内容敏感」的发布漏洞。读取失败返回空串则退化为原行为。
                subtitle_text = ""
                if settings.enable_subtitle_censorship:
                    subtitle_text = read_subtitle_text(self._OUT_DIR, yid, slice_index=slice_index)
                    if subtitle_text:
                        logger.info(f"[Censor] Subtitle body included for {prefix} ({len(subtitle_text)} chars)")
                if self._check_censorship(yid, short_title, copy_content, zh_title=short_title,
                                          slice_index=slice_index, subtitle_text=subtitle_text,
                                          stage="wechat_publish", fail_closed=True, platform="微信"):
                    return


                # ── 3. 封面生成 ──────────────────────────────────────────────────
                cover_file = self._OUT_DIR / f"{prefix}_cover.jpg"
                cover_brief_file = self._OUT_DIR / f"{prefix}_cover_brief.json"
                content_aware_cover_enabled = settings.enable_content_aware_cover
                cover_checkpoint_ready = cover_file.exists() and (
                    not content_aware_cover_enabled or cover_brief_file.is_file()
                )
                if not cover_checkpoint_ready:
                    logger.info(f"Generating cover for {prefix}...")
                    cover_title = title
                    if title_file.exists():
                        try:
                            cover_title = title_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass

                    import json
                    cover_payload = {
                        "title": cover_title,
                        "subtitle": "",
                        "category": "",
                        "content_hints": [],
                        # 只能依据本次成片实际启用的 TTS provider 标注版本；
                        # 原声英文加字幕与未知 provider 都不得出现“译制/配音”角标。
                        "audio_edition": _cover_audio_edition(video.get("tts_provider")),
                    }
                    subtitle_file = self._OUT_DIR / f"{prefix}_subtitle.txt"
                    
                    # [Unknown_Model_planning] 强制子分段视频封面副标题：整体的标题 + {当前集}/{总集数} 集
                    if slice_index > 0:
                        parent_video = self.db.get_video_by_youtube_id(yid, 0)
                        if parent_video:
                            parent_zh = parent_video.get("zh_title") or parent_video.get("title") or ""
                            # 剔除括号以防止副标题过长
                            import re as _re
                            parent_zh_clean = _re.sub(r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', parent_zh).strip()
                            
                            parent_title_file = self._OUT_DIR / f"{yid}_title.txt"
                            if parent_title_file.exists():
                                try:
                                    parent_short = parent_title_file.read_text(encoding="utf-8").strip()
                                except Exception:
                                    parent_short = graceful_truncate_title(parent_zh_clean, max_len=14)
                            else:
                                parent_short = graceful_truncate_title(parent_zh_clean, max_len=14)
                                
                            all_slices = self.db.get_slices_by_parent_yid(yid)
                            total_cnt = len(all_slices) if all_slices else 1
                            slice_subtitle = f"{parent_short} {slice_index}/{total_cnt}集"
                            try:
                                subtitle_file.write_text(slice_subtitle, encoding="utf-8")
                                logger.info(f"Enforced slice subtitle: {slice_subtitle}")
                            except Exception as e:
                                logger.error(f"Failed to write slice subtitle file: {e}")

                    if subtitle_file.exists():
                        try:
                            cover_payload["subtitle"] = subtitle_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass
                    category_file = self._OUT_DIR / f"{prefix}_category.txt"
                    if category_file.exists():
                        try:
                            cover_payload["category"] = category_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass
                    hints_file = self._OUT_DIR / f"{prefix}_content_hints.json"
                    if hints_file.exists():
                        try:
                            cover_payload["content_hints"] = json.loads(hints_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    # [Gemini_2.5_Pro_planning] v3.0.0: 读取封面角标标签（label_file 已在 2a 段定义）
                    if label_file.exists():
                        try:
                            cover_payload["content_label"] = label_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass

                    cover_cmd = [
                        self._VENV_PYTHON,
                        str(self._PRJ_ROOT / "scripts" / "cover_generator.py"),
                        "--payload", json.dumps(cover_payload, ensure_ascii=False),
                        "--output", str(cover_file),
                    ]
                    if content_aware_cover_enabled:
                        cover_cmd.extend([
                            "--content-aware",
                            "--brief-output", str(cover_brief_file),
                        ])
                    res = subprocess.run(cover_cmd, capture_output=True,
                                         cwd=str(self._PRJ_ROOT))
                    if res.returncode != 0:
                        logger.warning(f"Cover generation failed (non-fatal): "
                                       f"{res.stderr.decode()[:200]}")
                else:
                    logger.info(f"[SKIP] Cover checkpoint: {cover_file.name}")

                # ── 4. PUBLISHING ─────────────────────────────────────────────────
                # Sequence Locking 二次校验（防止在 queue 排队期间状态改变）
                if slice_index > 0:
                    all_slices = self.db.get_slices_by_parent_yid(yid)
                    # [Unknown_Model_planning] 放宽顺序锁：跳过处于已发布/跳过/手动上传状态的切片任务
                    prev_not_published = [s for s in all_slices if s['slice_index'] < slice_index and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
                    if prev_not_published:
                        logger.warning(f"Sequence Lock active: slice {slice_index} waiting for previous slices. Resetting to PENDING.")
                        self.db.update_video_status(yid, "PENDING", slice_index=slice_index)
                        return

                if not self._is_public_publish_window("微信", yid, slice_index):
                    self.db.update_video_status(yid, "PENDING", slice_index=slice_index)
                    logger.info("[%s] 视频号成片已就绪，等待公开视频提交窗口。", prefix)
                    return

                if not cover_file.is_file():
                    reason = "视频号投递产物缺失：封面文件不存在，禁止提交默认封面作品。"
                    logger.error("[%s] %s", prefix, reason)
                    self.db.update_video_status(yid, "FAILED", error_msg=reason, slice_index=slice_index)
                    self._notify_failed(yid, title, reason, slice_index=slice_index)
                    return

                self.db.update_video_status(yid, "PUBLISHING", slice_index=slice_index)
                logger.info(f"Uploading to WeChat Channels for {prefix}...")

                # ── 合集（Collection）名称决策 ──────────────────────────────────
                # [Gemini_2.5_Pro_planning] v3.0.0 修复: 微信视频号"分类"已改名为"合集"。
                # 规则：
                #   slice_index == 0（整片视频）→ 使用 AI 生成的大分类（如"科技""财经"）作为合集
                #   slice_index >  0（系列切片）→ 使用父视频短标题作为合集（各切片共享同一合集）
                # _select_collection 已能处理"选中已有"和"自动新建"两种情况。
                collection_name = ""
                if slice_index == 0:
                    # 整片视频：用 AI 分类结果作为大类合集名
                    if category_file.exists():
                        try:
                            collection_name = category_file.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass
                    if collection_name:
                        logger.info(f"[Collection] Single video → using category as collection: {collection_name!r}")
                    else:
                        logger.warning(f"[Collection] Single video: no category_file, skipping collection.")
                else:
                    # 系列切片：用父视频短标题作为合集名（确保各切片合集一致）
                    import re as _re
                    parent_video_for_coll = self.db.get_video_by_youtube_id(yid, 0)
                    if parent_video_for_coll:
                        parent_zh_coll = (
                            parent_video_for_coll.get("zh_title")
                            or parent_video_for_coll.get("title")
                            or ""
                        )
                        # 剔除括号内容防止合集名过长
                        parent_zh_coll = _re.sub(
                            r'\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】', '', parent_zh_coll
                        ).strip()
                        # 优先使用已生成的中文短标题
                        parent_title_file_coll = self._OUT_DIR / f"{yid}_title.txt"
                        if parent_title_file_coll.exists():
                            try:
                                parent_zh_coll = parent_title_file_coll.read_text(encoding="utf-8").strip()
                            except Exception:
                                pass
                        collection_name = graceful_truncate_title(parent_zh_coll, max_len=15)
                        logger.info(f"[Collection] Slice video → using parent short title as collection: {collection_name!r}")
                    else:
                        logger.warning(f"[Collection] Parent video (slice_index=0) not found for {yid}, skipping collection.")

                upload_cmd = [
                    self._VENV_PYTHON,
                    str(self._PRJ_ROOT / "scripts" / "wechat_uploader.py"),
                    "--video",  str(vertical),
                    "--copy",   str(copy_file),
                    "--state",  str(self._OUT_DIR / "wechat_state.json"),
                    "--fail-fast-login",
                    "--evidence-dir",
                    str(self._OUT_DIR / "wechat_evidence" / prefix / str(time.time_ns())),
                ]
                if not settings.wechat_headless:
                    upload_cmd += ["--no-headless"]
                upload_cmd += ["--cover", str(cover_file)]
                if title_file.exists():
                    upload_cmd += ["--title-file", str(title_file)]
                if category_file.exists():
                    upload_cmd += ["--category-file", str(category_file)]
                # [Gemini_2.5_Pro_planning] v3.0.0: 对单视频和多切片均传 collection
                if collection_name:
                    upload_cmd += ["--collection", collection_name]

                try:
                    res = self._run_tracked(upload_cmd, yid, slice_index=slice_index, text=True,
                                            capture_output=True, cwd=str(self._PRJ_ROOT),
                                            timeout=_WECHAT_UPLOAD_TIMEOUT_SEC)
                    if res.stdout:
                        logger.debug(f"Uploader stdout:\n{res.stdout}")
                    if res.stderr:
                        logger.debug(f"Uploader stderr:\n{res.stderr}")
                except subprocess.TimeoutExpired:
                    logger.error(f"WeChat publish timed out for {prefix} after {_WECHAT_UPLOAD_TIMEOUT_SEC}s.")
                    self.db.update_video_status(
                        yid, "FAILED",
                        error_msg=(
                            "微信上传超时（>25分钟）并已被系统终止。"
                            "通常是页面交互卡住或发布结果迟迟未确认；请先核对视频号后台，"
                            "确认未发后再点「重试」。"
                        ),
                        slice_index=slice_index)
                    self.send_telegram_msg(
                        f"⚠️ <b>WeChat publish timed out</b>\n"
                        f"Title: {short_title}\n"
                        f"Uploader exceeded {_WECHAT_UPLOAD_TIMEOUT_SEC // 60} minutes and was terminated."
                    )
                    return
                except subprocess.CalledProcessError as upload_err:
                    if upload_err.returncode == 2:
                        logger.error(f"WeChat login required for {prefix}.")
                        self.db.update_video_status(yid, "LOGIN_REQUIRED", slice_index=slice_index)
                        self.send_telegram_msg(
                            f"⚠️ <b>WeChat Login Required</b>\n"
                            f"Session expired: <b>{prefix}</b>\n"
                            f"<code>python scripts/wechat_uploader.py --login-only --no-headless</code>"
                        )
                        return
                    if upload_err.returncode == 3:
                        # [Claude_Opus_4.8] BUG-2: 发布结果无法确认（可能已发/可能未发）。
                        # 绝不置 PUBLISHED、绝不 GC 删源（保留产物供核验/重发），也不自动重发（防重复）。
                        logger.error(f"WeChat publish UNCONFIRMED for {prefix} — keeping artifacts, no GC, no auto-republish.")
                        self.db.update_video_status(
                            yid, "FAILED",
                            error_msg=("发布结果无法确认（可能已发/可能未发）。请到视频号后台核对：\n"
                                       "· 若【未发布】→ 点「重试」重新发布；\n"
                                       "· 若【已发布】→ 点「已处理」，切勿重试以免重复发布。"),
                            slice_index=slice_index)
                        self.send_telegram_msg(
                            f"⚠️ <b>发布结果待人工核实</b>\nTitle: {short_title}\n"
                            f"无法确认是否已发布到视频号，请核对后再操作，避免重复发布。"
                        )
                        return  # 关键：不置 PUBLISHED、不 GC
                    raise

                # ── 5. PUBLISHED ──────────────────────────────────────────────────
                self.db.update_video_status(yid, "PUBLISHED", slice_index=slice_index)
                self.send_telegram_msg(
                    f"✅ <b>Video Published</b>\nTitle: {short_title}\n"
                    f"Platform: WeChat Channels\nScore: {video['score']}"
                )

                if settings.enable_kuaishou_browser_publishing:
                    if not self._queue_and_publish_new_kuaishou_video(yid, slice_index):
                        logger.warning("[%s] 视频号已发布；快手未确认成功，将固定重试同一成片", yid)
                if settings.enable_douyin_browser_publishing:
                    if not self._queue_and_publish_new_douyin_video(yid, slice_index):
                        logger.warning("[%s] 视频号已发布；抖音未确认成功，将固定重试同一成片", yid)
                
                # 触发 GC 清理该子任务的临时文件
                self._run_garbage_collection(yid, slice_index, "PUBLISHED")

            except InterruptedError as e:
                logger.warning(f"[SIGTERM] Clean abort for {prefix}: {e}")
                self.db.update_video_status(yid, "PENDING", error_msg="Aborted by SIGTERM", slice_index=slice_index)
                self.reset_video_artifacts(prefix)

            except subprocess.CalledProcessError as e:
                err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode()
                logger.error(f"Process failed for {prefix}: {err[:500]}")
                self.db.update_video_status(yid, "FAILED", error_msg=err, slice_index=slice_index)
                self._notify_failed(yid, title, err, slice_index=slice_index)
                self._run_garbage_collection(yid, slice_index, "FAILED")

            except Exception as e:
                logger.error(f"Unexpected error for {prefix}: {e}")
                self.db.update_video_status(yid, "FAILED", error_msg=str(e), slice_index=slice_index)
                self._notify_failed(yid, title, str(e), slice_index=slice_index)
                self._run_garbage_collection(yid, slice_index, "FAILED")

        finally:
            if lock_file is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    logger.info(f"[Lock] Released pipeline lock for {prefix}.")
                except Exception as ex:
                    logger.error(f"[Lock] Error releasing lock: {ex}")
                finally:
                    lock_file.close()
            if settings.enable_sigterm_kill:
                self.db.update_process_pid(yid, None, slice_index=slice_index)

    # ── 每日作业 ──────────────────────────────────────────────────────────────

    def recover_deferred_wechat_publications(self) -> int:
        """从 WECHAT_DEFERRED 状态按限额恢复微信发布"""
        if settings.wechat_publishing_paused:
            return 0
        if not self._is_public_publish_window("微信补发"):
            return 0
        limit = settings.wechat_deferred_recovery_daily_limit
        recovered = 0
        for _ in range(limit):
            claimed = self.db.claim_next_deferred_wechat_publication()
            if not claimed:
                break
            self._process_single_video(claimed)
            recovered += 1
        return recovered

    def _defer_wechat_and_publish_kuaishou(self, yid: str, slice_index: int = 0) -> None:
        prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
        self.db.update_video_status(yid, "WECHAT_DEFERRED", slice_index=slice_index)
        if settings.enable_kuaishou_browser_publishing:
            if not self.db.get_kuaishou_publication(yid, slice_index=slice_index):
                self._queue_and_publish_new_kuaishou_video(yid, slice_index=slice_index)
        if settings.enable_douyin_browser_publishing:
            if not self.db.get_douyin_publication(yid, slice_index=slice_index):
                self._queue_and_publish_new_douyin_video(yid, slice_index=slice_index)
        self._run_garbage_collection(yid, slice_index, "WECHAT_DEFERRED")

    def run_daily_job(self):
        """执行每日例行调度"""
        logger.info("--- Starting Daily Pipeline Job ---")
        self.score_pending_videos()
        self.process_high_score_videos(limit=5)
        if not settings.wechat_publishing_paused:
            recovered = self.recover_deferred_wechat_publications()
            if recovered:
                logger.info(f"WeChat deferred recovery processed {recovered} video(s).")
        if settings.enable_kuaishou_browser_publishing:
            self.reconcile_kuaishou_under_review()
            if not self._retry_one_kuaishou_new_video():
                logger.warning("快手新片重试未确认成功，保留同一视频下次重试。")
        if settings.enable_douyin_browser_publishing:
            self._reset_douyin_run_guard()
            self.reconcile_douyin_under_review()
            if self._douyin_platform_halted:
                logger.warning("抖音审核回查触发熔断，跳过本轮新片重试和历史迁移。")
            elif not self._run_douyin_new_sync():
                logger.warning("抖音新片同步未确认成功，保留同一视频下次重试。")
            else:
                self._run_douyin_history_migration()
        logger.info("--- Daily Pipeline Job Completed ---")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    PipelineManager().run_daily_job()
