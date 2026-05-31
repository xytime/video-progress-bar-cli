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
"""
from pathlib import Path
from typing import Optional

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用全局配置。
    字段来源优先级：环境变量 > .env 文件 > 字段默认值。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,   # 环境变量大小写不敏感
        extra="ignore",         # 忽略 .env 中未声明的多余字段
    )

    # -------------------------------------------------------------------------
    # 运行时环境变量 (Runtime Env Vars) — 从 .env 或系统环境注入
    # -------------------------------------------------------------------------

    # 日志级别
    log_level: str = "INFO"

    # FFmpeg 可执行文件路径（留空则使用系统 PATH 中的默认值）
    ffmpeg_path: Optional[str] = None

    # Telegram 通知 Bot 配置
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Google Gemini API Key
    gemini_api_key: Optional[str] = None

    # 阿里云百炼 (DashScope / Model Studio) API Key — 用于 CosyVoice TTS
    # 获取地址：https://bailian.console.aliyun.com/ → API-KEY 管理
    dashscope_api_key: Optional[str] = None  # [Gemini_2.5_Pro_planning]

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


# 全局单例 — 整个项目统一引用此实例
settings = Settings()
