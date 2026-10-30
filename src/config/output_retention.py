"""output 清理器的具名、非秘密本机配置；不读取环境或业务凭据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-31 | Codex | 双七天、独立隔离区及有界每日清理配置 |
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


@dataclass(frozen=True)
class OutputRetentionPolicy:
    project_root: str
    output_root: str
    volume_root: str
    volume_uuid: str
    store_root: str
    store_identity: dict = field(default_factory=dict)
    legacy_approvals: dict = field(default_factory=dict)
    version: int = 1
    idle_days: int = 7
    observation_days: int = 7
    scan_entries: int = 350_000
    json_bytes: int = 128 * 1024 * 1024
    max_tree_entries: int = 100_000
    max_actions: int = 2_000
    max_bytes: int = 64 * 1024**3
    max_seconds: int = 300

    def validate(self):
        if self.version != 1 or not self.volume_uuid or not self.store_identity:
            raise ValueError("RETENTION_POLICY_IDENTITY_UNKNOWN")
        for value in (self.project_root, self.output_root, self.volume_root, self.store_root):
            path = Path(value)
            if not path.is_absolute() or path.absolute() != path.resolve():
                raise ValueError("RETENTION_POLICY_PATH_UNSAFE")
        project, output, volume, store = map(Path, (
            self.project_root, self.output_root, self.volume_root, self.store_root))
        if (output != project / "output" or not project.is_relative_to(volume)
                or not store.is_relative_to(volume) or store.is_relative_to(project)
                or project.is_relative_to(store)
                or store == volume):
            raise ValueError("RETENTION_POLICY_BOUNDARY_INVALID")
        for value in (self.idle_days, self.observation_days):
            if type(value) is not int or value < 7:
                raise ValueError("RETENTION_POLICY_BELOW_SEVEN_DAYS")
        for value in (self.scan_entries, self.json_bytes, self.max_tree_entries,
                      self.max_actions, self.max_bytes, self.max_seconds):
            if type(value) is not int or value <= 0:
                raise ValueError("RETENTION_POLICY_BUDGET_INVALID")
        if not isinstance(self.legacy_approvals, dict) or any(
                not isinstance(path, str) or not Path(path).is_absolute()
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                for path, digest in self.legacy_approvals.items()):
            raise ValueError("RETENTION_POLICY_LEGACY_APPROVAL_INVALID")
        return self

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError("RETENTION_POLICY_LINK_REFUSED")
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("RETENTION_POLICY_INVALID")
        try:
            return cls(**value).validate()
        except TypeError as exc:
            raise ValueError("RETENTION_POLICY_INVALID") from exc

    def dump(self):
        self.validate()
        return asdict(self)
