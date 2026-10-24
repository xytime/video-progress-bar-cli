"""非秘密运行配置的不可变版本仓库；不导入业务层，不修改操作事实。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | hash校验、共享读锁、CAS/幂等提交及只回滚配置的版本存储。 |
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import copy
import fcntl
import hashlib
import json
import os
import re
import time
import uuid


class ConfigurationError(ValueError):
    pass


class ConfigurationConflict(ConfigurationError):
    pass


class ConfigurationUnavailable(ConfigurationError):
    pass


def pairs(items):
    data = {}
    for key, value in items:
        if key in data:
            raise ConfigurationError("配置存在重复字段")
        data[key] = value
    return data


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ConfigurationError("配置含非有限数值")))


def serialized(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(serialized(data)).hexdigest()


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            os.chmod(temp, 0o600)
            stream.write(serialized(data))
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


@dataclass(frozen=True)
class PolicySnapshot:
    revision: str
    version: str
    created_at: float
    _data: dict
    manifest: dict

    def domains(self):
        return copy.deepcopy(self._data)


ATTEMPT = ContextVar("runtime_configuration_attempt", default=None)


class PolicyStore:
    """提交只持策略短锁；从不获取浏览器锁。锁序：账号事务→策略共享读锁。"""
    def __init__(self, root: Path):
        self.root = Path(root)

    @contextmanager
    def locked(self, *, write=False):
        lock = self.root / ".policy.lock"
        # 迁移时创建锁；只读消费者不会隐式初始化配置目录。
        if write:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            stream = lock.open("a+b")
        else:
            stream = lock.open("rb")
        with stream:
            fcntl.flock(stream, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            yield

    def _version(self, version, expected=None):
        if not isinstance(version, str) or not re.fullmatch(r"v-[a-f0-9]{32}", version):
            raise ConfigurationError("版本标识无效")
        directory = self.root / "versions" / version
        manifest = decode((directory / "manifest.json").read_bytes())
        if set(manifest) != {"schema_version", "version", "created_at", "actor", "reason", "previous_revision", "operation_id", "domains", "rollback_of"}:
            raise ConfigurationError("版本元数据无效")
        if manifest["schema_version"] != 1 or manifest["version"] != version:
            raise ConfigurationError("版本协议无效")
        revision = digest(manifest)
        if expected is not None and revision != expected:
            raise ConfigurationError("活动版本摘要不匹配")
        if set(manifest["domains"]) != {"wechat_operations", "task_scheduling", "observability", "runtime_settings", "interaction_controls"}:
            raise ConfigurationError("配置领域集合无效")
        domains = {}
        for name, sha in manifest["domains"].items():
            raw = (directory / (name + ".json")).read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha:
                raise ConfigurationError("配置内容摘要不匹配：" + name)
            domains[name] = decode(raw)
        from config.runtime_registry import SETTING_FIELDS, TASK_FIELDS, OBSERVABILITY_FIELDS, validate_fields
        from config.wechat_operations_schema import validate
        validate(domains['wechat_operations'])
        validate_fields(domains['runtime_settings'], SETTING_FIELDS)
        validate_fields(domains['task_scheduling'], TASK_FIELDS)
        validate_fields(domains['observability'], OBSERVABILITY_FIELDS)
        if not isinstance(domains['interaction_controls'],dict) or set(domains['interaction_controls'])!={'automatic_replies_enabled'} or type(domains['interaction_controls']['automatic_replies_enabled']) is not bool:
            raise ConfigurationError('观众回复总开关必须为布尔值，不能附带其他权限开关')
        return PolicySnapshot(revision, version, manifest["created_at"], domains, manifest)

    def _read(self):
        active = decode((self.root / "active.json").read_bytes())
        if set(active) != {"schema_version", "version", "revision"} or active["schema_version"] != 1:
            raise ConfigurationError("活动指针无效")
        return self._version(active["version"], active["revision"])

    def read(self):
        try:
            with self.locked():
                return self._read()
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise ConfigurationUnavailable("活动配置不可验证，停止新增执行") from exc

    def _write(self, domains, *, actor, reason, previous, operation_id, rollback_of=None):
        version = "v-" + uuid.uuid4().hex
        directory = self.root / "versions" / version
        files = {}
        for name, data in domains.items():
            atomic(directory / (name + ".json"), data)
            files[name] = hashlib.sha256((directory / (name + ".json")).read_bytes()).hexdigest()
        manifest = {"schema_version": 1, "version": version, "created_at": time.time(), "actor": actor,
                    "reason": reason, "previous_revision": previous, "operation_id": operation_id,
                    "domains": files, "rollback_of": rollback_of}
        atomic(directory / "manifest.json", manifest)
        atomic(self.root / "active.json", {"schema_version": 1, "version": version, "revision": digest(manifest)})
        return self._read()

    def initialize(self, domains, *, validate):
        """仅显式迁移调用；保留现有值，不复制任何额度、凭据或重试事实。"""
        validate(domains)
        with self.locked(write=True):
            if (self.root / "active.json").exists():
                return self._read()
            return self._write(domains, actor="local-migration", reason="原值迁移；无预算重置",
                               previous=None, operation_id="initial-migration")

    def commit(self, domains, *, expected_revision, actor, reason, operation_id, validate, rollback_of=None):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}", operation_id):
            raise ConfigurationError("操作编号无效")
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 200:
            raise ConfigurationError("请填写3–200字的变更原因，不要填写账号或凭据")
        validate(domains)
        with self.locked(write=True):
            current = self._read()
            # 幂等结果只允许精确的同一内容/操作者/基线；不能复用ID改写参数。
            for version in (self.root / "versions").iterdir():
                if not (version / 'manifest.json').is_file():
                    continue  # 切换指针前崩溃留下的未完成版本不属于历史。
                previous = self._version(version.name)
                m = previous.manifest
                if m["operation_id"] == operation_id:
                    if (previous.domains() != domains or m["actor"] != actor or m["previous_revision"] != expected_revision
                            or m['reason'] != reason.strip() or m['rollback_of'] != rollback_of):
                        raise ConfigurationConflict("操作编号已用于另一份变更")
                    return previous
            if current.revision != expected_revision:
                raise ConfigurationConflict("配置已被其他窗口修改；草稿已保留，请重新载入")
            return self._write(domains, actor=actor, reason=reason.strip(), previous=current.revision,
                               operation_id=operation_id, rollback_of=rollback_of)

    def history(self, *, limit=30):
        with self.locked():
            rows = [self._version(p.name) for p in (self.root / "versions").iterdir() if p.is_dir() and (p / 'manifest.json').is_file()]
            return sorted(rows, key=lambda s: s.created_at, reverse=True)[:min(100, max(1, limit))]

    def version(self, version):
        with self.locked():
            return self._version(version)
