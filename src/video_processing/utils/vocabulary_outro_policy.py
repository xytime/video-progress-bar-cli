"""生词片尾配置、CAS 保存与逐任务冻结结果；不访问商品配置、数据库或平台。

依赖：web/pipeline -> 本模块 -> core.video_groups / 文件原子写入。
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictBool, Field
from video_processing.core.video_groups import VIDEO_GROUPS, GROUP_LABELS, classify_video
from .wechat_product_config import atomic_json, PolicyConflict


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    channel_ids: list[str] = Field(max_length=100)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    enabled: StrictBool
    profiles: dict[str, Profile]


def parse_policy(data: dict) -> dict:
    import re
    value = Policy.model_validate(data).model_dump()
    if set(value["profiles"]) != set(VIDEO_GROUPS):
        raise ValueError("必须配置全部五种视频类型")
    seen = set()
    for name, profile in value["profiles"].items():
        for channel in profile["channel_ids"]:
            if name in {"english_world", "other"} or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel):
                raise ValueError("频道必须使用完整 UC ID，且仅配置在华尔街、TED 或 AI 类型中")
            if channel in seen:
                raise ValueError("同一频道不能重复配置或归属多个类型")
            seen.add(channel)
    return value


def digest(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_policy(path: Path) -> dict:
    return parse_policy(json.loads(path.read_text(encoding="utf-8")))


def save_policy(path: Path, data: dict, expected_digest: str) -> dict:
    config = parse_policy(data)
    with path.with_suffix(".json.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if digest(load_policy(path)) != expected_digest:
            raise PolicyConflict("配置已被其他窗口更新。草稿已保留，请重新载入后再修改。")
        atomic_json(path, config)
    return config


def decide(config: dict, context: dict) -> dict:
    group, reason = classify_video(context, {k: p["channel_ids"] for k, p in config["profiles"].items()})
    enabled = config["enabled"] and config["profiles"][group]["enabled"]
    return dict(group=group, group_label=GROUP_LABELS[group], reason=reason, enabled=enabled,
                config_digest=digest(config), policy=config)


def record_path(output: Path, prefix: str) -> Path:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", prefix):
        raise ValueError("非法视频标识")
    return output / f"{prefix}.outro-policy.json"


def read_record(output: Path, prefix: str) -> dict | None:
    path = record_path(output, prefix)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data["prefix"] != prefix or type(data["enabled"]) is not bool
            or data.get('status') not in {'PENDING', 'DISABLED', 'RENDERED', 'NO_SUITABLE_TERMS', 'FAILED'}
            or data.get('group') not in VIDEO_GROUPS
            or digest(parse_policy(data['policy'])) != data.get('config_digest')):
        raise ValueError("生词片尾任务记录损坏")
    return data


def freeze(output: Path, prefix: str, active: Path, context: dict) -> dict:
    """只在片尾步骤首次开始时冻结；保存后台配置不改正在处理的任务。"""
    output.mkdir(parents=True, exist_ok=True)
    path = record_path(output, prefix)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = read_record(output, prefix)
        if existing is not None:
            return existing
        record = dict(decide(load_policy(active), context), prefix=prefix,
                      status="PENDING", recorded_at=datetime.now(timezone.utc).isoformat())
        if not record["enabled"]:
            record["status"] = "DISABLED"
        atomic_json(path, record)
        return record


def update_record(output: Path, prefix: str, status: str, **values) -> None:
    record = read_record(output, prefix)
    if record is None:
        raise ValueError("缺少已冻结的片尾配置")
    record.update(values, status=status, updated_at=datetime.now(timezone.utc).isoformat())
    atomic_json(record_path(output, prefix), record)
