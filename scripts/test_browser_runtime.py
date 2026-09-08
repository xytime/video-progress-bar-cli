"""准备一次性 Chromium 依赖快照，不安装浏览器或导入业务配置。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 按已安装 Playwright 版本复制 headless shell，散列依赖并声明最小 IPC 例外 |
| 1.1.0 | 2026-09-08 | Codex | 保留 Playwright 标准缓存子目录，允许生产渲染器使用快照中的默认浏览器 |
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import platform


RENDEZVOUS_RULE = (
    r'(allow mach-lookup (global-name-regex #"^org\.chromium\.Chromium\.MachPortRendezvousServer\.[0-9]+$"))'
)


def installed_browser():
    """只支持可核验的本机默认缓存；未知布局/版本覆盖明确拒绝。"""
    spec = importlib.util.find_spec("playwright")
    if spec is None or not spec.origin:
        raise ValueError("未安装 Playwright；浏览器验收未执行")
    metadata = Path(spec.origin).parent / "driver/package/browsers.json"
    content = metadata.read_bytes()
    records = json.loads(content)["browsers"]
    browser = next(item for item in records if item["name"] == "chromium-headless-shell")
    revision = str(browser["revision"])
    if not revision.isdigit() or browser.get("revisionOverrides"):
        raise ValueError("未知 Chromium revision 布局；需要更新隔离适配，不自动回退")
    machine = platform.machine()
    architecture = {"arm64": "arm64", "x86_64": "x64"}.get(machine)
    if architecture is None:
        raise ValueError(f"未支持的 macOS 架构: {machine}")
    root = (Path.home() / "Library/Caches/ms-playwright" / f"chromium_headless_shell-{revision}").resolve()
    executable = Path(f"chrome-headless-shell-mac-{architecture}/chrome-headless-shell")
    if not (root / executable).is_file():
        raise ValueError(f"缺少 Playwright Chromium headless shell revision {revision}；不计为通过")
    return root, executable, {"revision": revision, "version": browser["browserVersion"],
                              "metadata_sha256": hashlib.sha256(content).hexdigest()}


def copy_browser(source, destination):
    """逐块复制和散列实际字节；拒绝包内链接，不访问其他缓存内容。"""
    manifest = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError("浏览器运行包包含链接；拒绝扩大依赖读取边界")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("浏览器运行包包含非常规文件")
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with path.open("rb") as reader, target.open("wb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(chunk)
                digest.update(chunk)
        target.chmod(path.stat().st_mode & 0o777)
        manifest[relative.as_posix()] = {"sha256": digest.hexdigest(), "bytes": target.stat().st_size}
    return manifest


def prepare_browser(run_root, repo, profile, evidence):
    source, relative_executable, metadata = installed_browser()
    destination = run_root / "browser" / f"chromium_headless_shell-{metadata['revision']}"
    files = copy_browser(source, destination)
    runtime = {**metadata, "source": str(source), "snapshot": str(destination),
               "executable": str(destination / relative_executable), "files": files}
    marker_path = repo / ".test-sandbox.json"
    marker = json.loads(marker_path.read_text())
    marker["browser"] = runtime
    marker_path.write_text(json.dumps(marker))
    profile.write_text(profile.read_text() + RENDEZVOUS_RULE + "\n")
    (evidence / "browser-runtime.json").write_text(json.dumps(runtime, indent=2))
    return runtime
