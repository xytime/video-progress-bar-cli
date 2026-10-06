"""进程生命周期锁、完整产物 manifest 和同卷原子提交。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 分阶段内容寻址缓存；锁不因时间过期被偷走 |
"""
import fcntl
import json
import shutil
import tempfile
import time
from pathlib import Path

from .contracts import PipelineError, digest, fingerprint, local_path


class StageCache:
    def __init__(self, root: Path, wait_seconds=60, revisions=None):
        self.root = root
        self.wait_seconds = wait_seconds
        self.revisions = revisions or {}
        root.mkdir(parents=True, exist_ok=True)

    def key(self, stage, inputs):
        return fingerprint({"revision": self.revisions.get(stage, "follow-along-core/1"), "stage": stage, "inputs": inputs})

    def run(self, stage, inputs, execute, resume=True):
        key = self.key(stage, inputs)
        base = self.root / stage
        base.mkdir(exist_ok=True)
        final = base / key
        started = time.monotonic()
        with (base / f"{key}.lock").open("a+") as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() - started >= self.wait_seconds:
                        raise PipelineError("RESOURCE_TIMEOUT", f"等待阶段锁超时: {stage}")
                    time.sleep(0.1)
            # 内核持锁期间没有 lease expiry/锁接管，故不存在旧 worker 提交竞争。
            manifest = final / "manifest.json"
            if resume and manifest.exists():
                try:
                    data = json.loads(manifest.read_text())
                    valid = data["key"] == key and data["stage"] == stage and bool(data["artifacts"])
                    for artifact in data["artifacts"]:
                        path = local_path(final, artifact["uri"])
                        valid = valid and path.is_file() and path.stat().st_size == artifact["byte_length"] and digest(path) == artifact["sha256"]
                    actual_files = {str(p.relative_to(final)) for p in final.rglob("*") if p.is_file() and p != manifest}
                    valid = valid and actual_files == {a["uri"] for a in data["artifacts"]}
                    if valid:
                        return final, {"stage": stage, "key": key, "state": "CACHE_HIT"}
                except (KeyError, ValueError, OSError):
                    pass
            temporary = Path(tempfile.mkdtemp(prefix=f".{key}-", dir=base))
            try:
                execute(temporary)
                files = sorted(p for p in temporary.rglob("*") if p.is_file())
                if not files or any(p.is_symlink() for p in temporary.rglob("*")):
                    raise PipelineError("OUTPUT_QA_FAILED", "阶段没有完整普通文件产物")
                artifacts = [{"uri": str(p.relative_to(temporary)), "sha256": digest(p), "byte_length": p.stat().st_size} for p in files]
                data = {"stage": stage, "key": key, "artifacts": artifacts}
                (temporary / "manifest.json").write_text(json.dumps(data, indent=2))
                import os
                for file in files + [temporary / "manifest.json"]:
                    with file.open("rb") as stream:
                        os.fsync(stream.fileno())
                # 旧目录仅在互斥锁下替换；断电发生在替换间隙会导致 cache miss 而非假成功。
                if final.exists():
                    shutil.rmtree(final)
                temporary.rename(final)
            except BaseException:
                # 保留诊断但失败目录不会命中 cache。
                failure = base / f"failed-{key}-{time.time_ns()}"
                temporary.rename(failure)
                raise
            return final, {"stage": stage, "key": key, "state": "SUCCEEDED"}
