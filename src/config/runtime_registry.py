"""运行参数唯一字段归属；安全上界不能由客户端或活动版本自行扩大。

# Modification History
| reply-recovery-v1 | 2026-10-25 | Codex | 共用回复策略与可选迁移领域校验，保留旧版本兼容。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | 核心额度和任务/观测参数注册；其余启动配置按目录只读或专用编辑。 |
"""
from __future__ import annotations

import re

# (中文名称、单位、最小值、最大值、生效边界、候选组)
SETTING_FIELDS = {
    "score_refresh_interval_minutes": ("评分刷新间隔", "分钟", 30, 1440, "下一批任务", "G09"),
    "copywriter_agy_timeout_seconds": ("文案生成超时", "秒", 10, 300, "下一次请求", "G07"),
    "codex_text_request_timeout_seconds": ("文本请求超时", "秒", 10, 300, "下一次请求", "G07"),
    "codex_subtitle_total_timeout_seconds": ("字幕请求总时限", "秒", 30, 1800, "下一批任务", "G07"),
    "codex_subtitle_batch_size": ("字幕分批数量", "条", 5, 100, "下一批任务", "G07"),
    "google_translate_request_timeout_seconds": ("翻译单次超时", "秒", 5, 300, "下一次请求", "G07"),
    "google_translate_total_timeout_seconds": ("翻译总时限", "秒", 30, 1800, "下一批任务", "G07"),
    "subtitle_translation_total_timeout_seconds": ("字幕翻译总时限", "秒", 30, 660, "下一批任务", "G07"),
    "google_translate_interval_seconds": ("翻译请求间隔", "秒", 0.2, 10, "下一次请求", "G07"),
    "google_translate_max_retries": ("翻译追加重试", "次", 0, 3, "下一批任务", "G07"),
    "youtube_download_timeout_seconds": ("下载总时限", "秒", 60, 3600, "下一批任务", "G08"),
    "youtube_source_preflight_timeout_seconds": ("字幕来源预检超时", "秒", 30, 300, "下一批任务", "G08"),
    "source_subtitle_retry_hours": ("源字幕失败冷却", "小时", 1, 168, "下一批任务", "G08"),
    "source_audio_preflight_timeout_seconds": ("源音频预检超时", "秒", 30, 1800, "下一批任务", "G08"),
    "ai_cover_quality_timeout_seconds": ("封面质量检查时限", "秒", 30, 300, "下一批任务", "G11"),
    "antigravity_timeout_seconds": ("封面生成请求时限", "秒", 30, 2400, "下一批任务", "G11"),
    "monitor_translation_timeout_seconds": ("素材标题翻译时限", "秒", 5, 120, "下一次请求", "G07"),
}

TASK_DEFAULTS = {"local_defer_fallback_seconds": 300, "first_comment_max_age_days": 3,
                 "queue_seen_seconds": 600, "reply_queue_seen_seconds": 2700}
TASK_FIELDS = {
    "local_defer_fallback_seconds": ("未知释放时间的本地重检间隔", "秒", 30, 3600, "5秒内重算本地等待", "G01"),
    "first_comment_max_age_days": ("首评任务最长年龄", "天", 1, 3, "下一次领取；已终止任务不复活", "G01"),
    "queue_seen_seconds": ("普通排队登记有效期", "秒", 600, 3600, "下一次准入", "G02"),
    "reply_queue_seen_seconds": ("回复排队登记有效期", "秒", 2700, 7200, "下一次准入", "G02"),
}
OBSERVABILITY_DEFAULTS = {"wait_notice_cooldown_seconds": 3600}
OBSERVABILITY_FIELDS = {"wait_notice_cooldown_seconds": ("相同等待通知静默时间", "秒", 300, 86400, "下一次通知", "G12")}
REPLY_CONTROL_SETTING_NAMES = frozenset({'enable_wechat_secondary_reply','enable_wechat_secondary_reply_live_submission'})
INTERACTION_CONTROLS_DEFAULTS = {'automatic_replies_enabled':False}
REPLY_STRATEGY_FIELDS = frozenset({'window_start_shanghai', 'window_end_shanghai', 'approval_mode'})


def validate_reply_strategy(value):
    """策略页和配置仓库共用严格校验；旧版本可以没有策略领域。"""
    if not isinstance(value, dict) or set(value) != REPLY_STRATEGY_FIELDS:
        raise ValueError('回复时段与审批字段不完整')
    start, end = value['window_start_shanghai'], value['window_end_shanghai']
    clock = r'(?:[01]\d|2[0-3]):[0-5]\d'
    if not isinstance(start, str) or not re.fullmatch(clock, start):
        raise ValueError('开始时间须为 00:00–23:59')
    if not isinstance(end, str) or not re.fullmatch(clock + r'|24:00', end):
        raise ValueError('结束时间须为 00:00–24:00')
    if value['approval_mode'] not in ('manual', 'hybrid_auto'):
        raise ValueError('回复审批模式无效')
    return value


def validate_interaction_controls(value):
    if not isinstance(value, dict) or set(value) not in (
        {'automatic_replies_enabled'}, {'automatic_replies_enabled', 'reply_strategy'}
    ) or type(value['automatic_replies_enabled']) is not bool:
        raise ValueError('观众回复总开关必须为布尔值，不能附带其他权限开关')
    if 'reply_strategy' in value:
        validate_reply_strategy(value['reply_strategy'])
    return value

GROUPS = [
    ("G01", "任务等待与过期"), ("G02", "队列与执行节奏"), ("G03", "扫描对象与年龄范围"),
    ("G04", "浏览器技术超时"), ("G05", "上传前恢复"), ("G06", "模型熔断"), ("G07", "请求批量与退避"),
    ("G08", "来源发现与回溯"), ("G09", "评分与生产准入"), ("G10", "库存与制作时刻"),
    ("G11", "封面与全机资源"), ("G12", "通知、日志与缓存"), ("G13", "文案与版式"),
    ("G14", "英语视频与渲染"), ("G15", "人工许可与授权"), ("G16", "安全、去重与协议"),
    ("G17", "真实限流后的恢复"), ("G18", "其他平台、专题与实验"),
]


def validate_fields(data, registry):
    if not isinstance(data, dict) or set(data) != set(registry):
        raise ValueError("参数集合不完整或包含未知字段")
    for key, spec in registry.items():
        value = data[key]
        if type(value) not in (int, float) or not spec[2] <= value <= spec[3]:
            raise ValueError(spec[0] + "超出范围或类型错误")
        if key != "google_translate_interval_seconds" and type(value) is not int:
            raise ValueError(spec[0] + "必须为整数")
