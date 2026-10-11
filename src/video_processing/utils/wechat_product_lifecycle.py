"""配置影响与历史快照；不启动任务，不把预览当作实际采用。"""
from __future__ import annotations
import json
import re
from pathlib import Path
from video_processing.core.wechat_product_policy import parse_product_policy
from video_processing.utils.wechat_product_config import load_policy, PolicyConflict
from video_processing.utils.wechat_product_context import video_product_context


def history_path(active: Path) -> Path:
    return active.with_name(active.stem + '_history')


def read_revision(active: Path, digest: str):
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('历史摘要格式错误')
    current = load_policy(active)
    policy = current if current.digest == digest else load_policy(history_path(active) / (digest + '.json'))
    if policy.digest != digest:
        raise ValueError('历史快照摘要不一致，拒绝回滚')
    return policy


def list_revisions(active: Path) -> list[dict]:
    current = load_policy(active)
    rows = {current.digest: {'digest': current.digest, 'version': current.version, 'current': True}}
    for path in sorted(history_path(active).glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.stem in rows:
            continue
        try:
            policy = read_revision(active, path.stem)
            rows[policy.digest] = dict(digest=policy.digest, version=policy.version, current=False)
        except (ValueError, OSError):
            rows[path.stem] = dict(digest=path.stem, version='损坏快照，不可恢复', current=False, error=True)
    return list(rows.values())


def impact(active: Path, candidate: dict, expected_digest: str, videos: list[dict], output: Path) -> dict:
    old = load_policy(active)
    if old.digest != expected_digest:
        raise PolicyConflict('配置已被其他窗口更新，请重新载入后比较。')
    new = parse_product_policy(candidate)
    changed, unknown, unchanged = [], [], 0
    def signature(decision):
        return dict(group=decision.video_group, reason=decision.reason,
                    candidates=[vars(p) for p in decision.candidates],
                    timeout_seconds=decision.timeout_seconds, max_attempts=decision.max_attempts)
    for video in videos[:100]:
        identity = dict(key=video.get('preview_key'), title=video.get('title', '未命名任务'), state=video.get('state'))
        try:
            context = video_product_context(output, video)
            before, after = signature(old.decide(**context)), signature(new.decide(**context))
            if before != after:
                changed.append(dict(identity, before=before, after=after))
            else:
                unchanged += 1
        except (ValueError, OSError, TypeError, KeyError):
            unknown.append(dict(identity, reason='上下文缺失、格式错误或资料不可读，影响未知'))
    before_config = json.loads(old.serialized)
    configuration_changes = [label for key, label in [('library','商品资料'),('wait_policy','等待检查参数')]
                             if before_config.get(key) != candidate.get(key)]
    return dict(configuration_changes=configuration_changes, base_digest=old.digest, candidate_digest=new.digest, changed=changed,
                unknown=unknown, unchanged=unchanged, examined=min(100, len(videos)), limit=100,
                preview_only=True, scope='最近最多100条；已开始选品的任务继续使用旧快照')
