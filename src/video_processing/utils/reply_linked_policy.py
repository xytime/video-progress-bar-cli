"""回复策略和运行配置中心共用的联动适配；额度只保存一份。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 联动元数据和计算共用、服务端一致校验、仅处理配置。 |
"""
from copy import deepcopy
import json
from config.settings import settings
from config.reply_linkage import DEFAULT_LINKAGE, calculate
from config.wechat_operations_schema import APPROVED
from video_processing.core.reply_send_schedule import verified_cadence


def editor_config(domains, *, legacy=None):
    reply = domains['wechat_operations']['operations']['reply']
    controls = domains['interaction_controls']
    strategy = controls.get('reply_strategy')
    if strategy is None and legacy is not None:
        strategy = {key: legacy[key] for key in ('window_start_shanghai','window_end_shanghai','approval_mode')}
    if strategy is None and settings.wechat_reply_policy_path.exists():
        from config.secondary_reply_schema import parse_policy
        legacy = parse_policy(json.loads(settings.wechat_reply_policy_path.read_text(encoding='utf-8')))
        strategy = {key: legacy[key] for key in ('window_start_shanghai','window_end_shanghai','approval_mode')}
    strategy = strategy or {
        'window_start_shanghai': settings.wechat_reply_window_start_shanghai,
        'window_end_shanghai': settings.wechat_reply_window_end_shanghai,
        'approval_mode': settings.wechat_reply_approval_mode}
    return {**strategy, 'daily_quota': reply['rolling_24h_limit'],
            'hourly_quota': reply['rolling_1h_limit'], 'min_interval_seconds': reply['min_interval_seconds'],
            'linkage': deepcopy(controls.get('reply_linkage', DEFAULT_LINKAGE))}


def recommend(config):
    return calculate(config, verified_cadence(), max_hourly=APPROVED['reply']['rolling_1h_limit'],
                     min_interval=APPROVED['reply']['min_interval_seconds'])


def capacity_view(config):
    # 展示保存值的真实容量，读取不能悄悄用推荐值替换现有数值。
    manual = {**config, 'linkage': {**DEFAULT_LINKAGE, 'hourly_quota': 'manual', 'min_interval_seconds': 'manual'}}
    _, report = recommend(manual)
    return report


def normalize_domains(domains):
    result = deepcopy(domains)
    mode = result['interaction_controls'].get('reply_linkage')
    if mode and mode['initialized']:
        config, _ = recommend(editor_config(result))
        reply = result['wechat_operations']['operations']['reply']
        reply.update(rolling_1h_limit=config['hourly_quota'], min_interval_seconds=config['min_interval_seconds'])
    return result


def validate_linked_values(domains):
    mode = domains['interaction_controls'].get('reply_linkage')
    if mode and mode['initialized'] and normalize_domains(domains) != domains:
        raise ValueError('自动联动字段与推荐值不一致；请重新计算或将该字段改为手动')
