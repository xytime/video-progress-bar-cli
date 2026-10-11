"""商品策略的文件加载、原子激活与运行采用记录。

依赖：CLI/uploader → 本模块 → core.wechat_product_policy；不访问浏览器或数据库。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from video_processing.core.wechat_product_policy import ProductPolicy, parse_product_policy


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 字段: {key}")
        result[key] = value
    return result


def load_policy(path: Path | str) -> ProductPolicy:
    # 不读取内置备用规则：初次缺配置或直接编辑成非法配置时明确拒绝。
    data = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    return parse_product_policy(data)


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def activate_policy(candidate: Path, active: Path) -> ProductPolicy:
    """先完整校验再替换；任何校验异常都保持已激活文件原样。"""
    policy = load_policy(candidate)
    atomic_json(active, json.loads(policy.serialized))
    return policy


def decision_payload(decision) -> dict:
    return {'config_version': decision.rule_version, 'config_digest': decision.config_digest,
            'matched_rule': decision.reason, 'context': dict(decision.context),
            'candidates': [{'product_id': p.product_id, 'title': p.title} for p in decision.candidates],
            'timeout_seconds': decision.timeout_seconds, 'max_attempts': decision.max_attempts}


def record_adoption(policy: ProductPolicy, decision, evidence_dir: Path, status_path: Path,
                    *, phase: str, result=None) -> None:
    """只由实际选品入口调用；preview/status 不伪造运行采用。"""
    atomic_json(evidence_dir / 'product_policy_snapshot.json', json.loads(policy.serialized))
    payload = dict(decision_payload(decision), phase=phase, evidence_dir=str(evidence_dir.resolve()),
                   recorded_at=datetime.now(timezone.utc).isoformat())
    if result is not None:
        payload.update(binding_confirmed=result.binding_confirmed, reason=result.reason)
    atomic_json(evidence_dir / 'product_policy_adoption.json', payload)
    atomic_json(status_path, payload)


def policy_status(active: Path, status_path: Path) -> dict:
    policy = load_policy(active)
    last = json.loads(status_path.read_text()) if status_path.exists() else None
    return {'saved_version': policy.version, 'saved_digest': policy.digest,
            'last_selection': last,
            'adopted_by_last_selection': bool(last and last.get('config_digest') == policy.digest)}
