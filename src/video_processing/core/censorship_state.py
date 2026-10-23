"""当前审查阻塞与历史命中分别展示；历史标签不能授权复核动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 共用当前错误分类，不改变任何批准范围。 |
"""


def censor_layer_from_error(error_msg):
    em = (error_msg or '').strip()
    for prefix, layer, label, severity in (
        ('Social Unrest Review:', 'RISK', '平台题材风险 · 社会动荡', 'high'),
        ('Censorship P0', 'P0', 'P0 · 政治安全违禁', 'critical'),
        ('Censorship P1', 'P1', 'P1 · 敏感内容挂起', 'high'),
        ('Censorship P2', 'P2', 'P2 · 商业合规降权', 'medium'),
        ('Channel Policy Reject:', 'CP', '频道策略限制', 'low'),
    ):
        if em.startswith(prefix):
            return layer, label, severity
    return None, '未知审查层', 'low'


def review_state(video, p0_approved=False):
    layer, label, _ = censor_layer_from_error(video.get('error_msg'))
    current = layer if video.get('status') == 'FAILED' else None
    tag = video.get('censor_tag') or ''
    # P0 必须同时有操作标志与台账；题材层是否仍有效由原指纹门禁负责。
    p0_history = '政治' in tag or '🔴' in tag
    approval = ('P0 已人工放行' if p0_history and p0_approved else
                '已记录人工放行' if not p0_history else '') if video.get('bypass_censorship') else ''
    return dict(current_layer=current, current_label=label if current else '',
                can_review=bool(current), history_tag=tag, approval_label=approval)
