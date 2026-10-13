"""部署源码计划与精确采用；不解冲突、不读取配置密钥、不执行计划中的命令。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 主干快进、已测覆盖文件、dirty 保留及采用中断核验 |
"""
from pathlib import Path
import hashlib
import subprocess

from .deployment import require, read_json, write_json, DeploymentDenied


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, timeout=30).stdout


def public_path(name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts and path.parts, "SOURCE_PATH_INVALID")
    require(not any(p.startswith(".env") or p.lower() in {"secrets", "credentials", "output", ".git"}
                    for p in path.parts), "SECRET_OR_RUNTIME_PATH_REFUSED")
    return path


def file_bytes(root, name):
    path = Path(root) / public_path(name)
    require(not path.is_symlink() and path.resolve() == path.absolute(), "SOURCE_SYMLINK_REFUSED")
    return path.read_bytes()


def runtime_manifest(root):
    root = Path(root)
    paths = [*sorted((root / "src").rglob("*.py")), *sorted((root / "scripts").glob("*.py")), root / "vpanel"]
    return {str(p.relative_to(root)): sha(file_bytes(root, str(p.relative_to(root)))) for p in paths}


def inventory(root):
    require(not git(root, "diff", "--cached", "--name-only"), "STAGED_WORK_PRESENT")
    dirty = git(root, "diff", "--name-only", "-z").decode().strip("\0").split("\0")
    names = git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().strip("\0").split("\0")
    return {"head": git(root, "rev-parse", "HEAD").decode().strip(),
            "branch": git(root, "branch", "--show-current").decode().strip(),
            "dirty": {n: sha(file_bytes(root, n)) for n in dirty if n},
            "untracked": sorted(n for n in names if n), "runtime": runtime_manifest(root)}


def prepare(root, target, directory, tested_manifest, overlay=None):
    """计划只写私有部署目录，不修改 checkout。测试清单必须覆盖最终所有 runtime 文件。"""
    root, directory = Path(root).resolve(), Path(directory).resolve()
    require(not directory.is_relative_to(root), "BACKUP_MUST_BE_OUTSIDE_CHECKOUT")
    before = inventory(root)
    require(before["branch"] == "main", "MAIN_REQUIRED")
    target = git(root, "rev-parse", "--verify", target + "^{commit}").decode().strip()
    git(root, "merge-base", "--is-ancestor", before["head"], target)
    changed = git(root, "diff", "--name-only", "-z", before["head"], target).decode().strip("\0").split("\0")
    changed = [n for n in changed if n]
    expected = dict(before["runtime"])
    updates = {}
    for name in changed:
        public_path(name)
        # 首期只支持普通文件新增/修改；删除、链接、模式变更须另行评审。
        mode = git(root, "ls-tree", target, "--", name).decode().split(None, 1)[0]
        require(mode in {"100644", "100755"}, "FILE_KIND_UNSUPPORTED")
        old_tree = git(root, "ls-tree", before["head"], "--", name).decode()
        require(not old_tree or old_tree.split(None, 1)[0] == mode, "FILE_MODE_CHANGE_UNSUPPORTED")
        require(name not in before["untracked"], "UNTRACKED_COLLISION")
        data = git(root, "show", target + ":" + name)
        if name in before["dirty"]:
            require(overlay is not None, "TESTED_OVERLAY_REQUIRED")
            data = file_bytes(overlay, name)
            original = directory / "original" / name
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(file_bytes(root, name))
        output = directory / "payload" / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        output.chmod(int(mode[-3:], 8))
        updates[name] = {"sha256": sha(data), "mode": int(mode[-3:], 8)}
        if name in expected or (name.endswith(".py") and (name.startswith("src/") or len(Path(name).parts) == 2 and name.startswith("scripts/"))) or name == "vpanel":
            expected[name] = sha(data)
    tested = read_json(tested_manifest)
    require(all(tested.get(n) == h for n, h in expected.items()), "TESTED_SOURCE_MISMATCH")
    return {"before": before, "target": target, "updates": updates, "expected_runtime": expected,
            "tested_manifest_sha256": sha(Path(tested_manifest).read_bytes())}


class Sources:
    def __init__(self, root, directory, plan):
        self.root, self.directory, self.plan = Path(root), Path(directory), plan

    def baseline(self):
        require(inventory(self.root) == self.plan["before"], "SOURCE_BASELINE_DRIFT")
        self.payload_check()

    def payload_check(self):
        for n, row in self.plan["updates"].items():
            require(sha(file_bytes(self.directory / "payload", n)) == row["sha256"], "PAYLOAD_DRIFT")

    def final(self):
        seen = inventory(self.root)
        require(seen["branch"] == "main" and seen["head"] == self.plan["target"], "TARGET_HEAD_MISMATCH")
        require(seen["runtime"] == self.plan["expected_runtime"], "TARGET_RUNTIME_MISMATCH")
        require(seen["untracked"] == self.plan["before"]["untracked"], "UNTRACKED_DRIFT")
        for n, h in self.plan["before"]["dirty"].items():
            expected = self.plan["updates"].get(n, {}).get("sha256", h)
            require(sha(file_bytes(self.root, n)) == expected, "DIRTY_WORK_CHANGED")
        for n, row in self.plan["updates"].items():
            require(sha(file_bytes(self.root, n)) == row["sha256"], "ADOPTED_FILE_MISMATCH")

    def adopt(self):
        self.baseline()
        overlaps = set(self.plan["updates"]) & set(self.plan["before"]["dirty"])
        # 子步骤日志在第一次修改前落盘；任何中断保持维护，不自动回滚/重做。
        write_json(self.directory / "adopt-intent.json", {"before": self.plan["before"]["head"], "target": self.plan["target"], "overlaps": sorted(overlaps)})
        for name in overlaps:
            (self.root / name).write_bytes(git(self.root, "show", self.plan["before"]["head"] + ":" + name))
        git(self.root, "merge", "--ff-only", self.plan["target"])
        for name in overlaps:
            (self.root / name).write_bytes(file_bytes(self.directory / "payload", name))
        self.final()

    def adopted(self):
        try:
            self.final()
            return True
        except (OSError, DeploymentDenied, subprocess.SubprocessError):
            return False
