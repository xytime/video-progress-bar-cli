"""在一次性源码副本与 macOS 进程沙盒中运行 pytest。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 收集前隔离配置、源码、输出、网络和子进程；保留快照与真实退出收据 |
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


SOURCE_DIRS = {"src", "scripts", "tests", "resources", "assets", "config", "docs"}
SOURCE_FILES = {"pyproject.toml", "setup.py", "requirements.txt", ".env.example"}
MARKER = ".test-sandbox.json"


def source_files(source):
    """只选受维护代码/测试资产；拒绝链接和敏感文件，不读取正式产物。"""
    listing = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=source
    ).decode().split("\0")
    for name in sorted(set(listing) - {""}):
        relative = Path(name)
        if relative.parts[0] not in SOURCE_DIRS and name not in SOURCE_FILES:
            continue
        if any(part in {"secrets", "__pycache__", ".venv", "output"}
               or (part.startswith(".env") and part != ".env.example") for part in relative.parts):
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("非法源码路径")
        path = source / relative
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError(f"源码快照拒绝符号链接: {name}")
        if not path.is_file():
            raise ValueError(f"源码文件缺失: {name}")
        yield relative


def snapshot(source, destination):
    manifest = {}
    for relative in source_files(source):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (source / relative).read_bytes()
        target.write_bytes(data)
        target.chmod((source / relative).stat().st_mode & 0o777)
        manifest[str(relative)] = hashlib.sha256(data).hexdigest()
    return manifest


def sandbox_profile(run_root):
    """只读系统/解释器依赖；写入仅一次性根，禁止网络与应用控制 IPC。"""
    readable = [run_root, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    readable += [Path(p) for p in (
        "/System/Library", "/System/Volumes/Preboot/Cryptexes/OS",
        "/usr", "/bin", "/sbin", "/opt/homebrew", "/Library/Apple",
        "/Library/Fonts", "/Library/Frameworks", "/Library/Developer",
        "/private/etc", "/private/var/db", "/dev",
    )]
    rules = ["(version 1)", "(allow default)", "(deny network*)", "(deny mach-lookup)",
             "(deny file-read-data)", "(deny file-write*)", "(deny signal)",
             "(allow signal (target same-sandbox))", "(deny process-info*)",
             "(allow process-info* (target same-sandbox))"]
    rules += [f"(allow file-read-data (subpath {json.dumps(str(path))}))" for path in readable]
    rules += ['(allow file-read-data (literal "/"))',
              f'(allow file-write* (subpath {json.dumps(str(run_root))}) (literal "/dev/null"))']
    return "\n".join(rules) + "\n"


def child_environment(repo, run_root):
    """显式环境允许清单；不继承业务密钥、代理、pytest 插件或用户配置。"""
    return {
        "PATH": f"{sys.prefix}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": str(repo / "src"), "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "TMPDIR": str(run_root / "tmp"),
        "XDG_CACHE_HOME": str(run_root / "cache"), "MPLCONFIGDIR": str(run_root / "mpl"),
        # 保留真实 home 路径用于常量解析；其数据仍被沙盒拒绝读取/写入。
        "HOME": str(Path.home()),
        "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
    }


def run_child(command, cwd, environment, log_path, timeout):
    started = time.monotonic()
    with log_path.open("w") as log:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log,
                                       stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        except OSError as exc:
            return {"exit_code": 127, "error_type": type(exc).__name__}
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = 124
        except KeyboardInterrupt:
            code = 130
        finally:
            # 仅清理本工具创建的进程组；自行 setsid 的后代仍受沙盒约束，
            # 但不承诺在此组清理覆盖范围内。
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    return {"exit_code": code, "seconds": round(time.monotonic() - started, 3)}


def boundary_probe(canary):
    """只针对工具自建的无敏感内容探针；不试读实际凭据或正式数据库。"""
    return f'''
import errno, json, os, pathlib, socket, subprocess, sys
canary = pathlib.Path({str(canary)!r})
def denied(action):
    try:
        action()
    except OSError as exc:
        return exc.errno in (errno.EPERM, errno.EACCES)
    return False
sock = socket.socket()
checks = {{
    "outside_read_denied": denied(canary.read_bytes),
    "outside_write_denied": denied(lambda: canary.write_text("unsafe")),
    "network_denied": denied(lambda: sock.bind(("127.0.0.1", 0))),
    "outside_signal_denied": denied(lambda: os.kill({os.getpid()}, 0)),
}}
alias = pathlib.Path("/System/Volumes/Data" + str(canary))
if alias.is_file():
    checks["data_volume_alias_read_denied"] = denied(alias.read_bytes)
sock.close()
child = subprocess.run([sys.executable, "-I", "-c", "from pathlib import Path; Path(" + repr(str(canary)) + ").write_text('unsafe')"], capture_output=True)
checks["child_write_denied"] = child.returncode != 0 and b"PermissionError" in child.stderr
print(json.dumps(checks))
sys.exit(0 if all(checks.values()) else 2)
'''


def prepare_run(source):
    if sys.prefix == sys.base_prefix:
        raise ValueError("必须使用项目 .venv/bin/python")
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("需要可用的 macOS sandbox-exec；禁止退回裸 pytest")
    evidence = Path(tempfile.mkdtemp(prefix="video-pytest-", dir="/tmp")).resolve()
    run_root = evidence / "sandbox"
    repo = run_root / "repo"
    repo.mkdir(parents=True)
    (run_root / "tmp").mkdir()
    manifest = snapshot(source, repo)
    (repo / ".venv").symlink_to(Path(sys.prefix).resolve(), target_is_directory=True)
    canary = evidence / "outside-canary.txt"
    canary.write_text("test-boundary-canary")
    marker = {"schema": 1, "repo": str(repo), "run_root": str(run_root), "canary": str(canary)}
    (repo / MARKER).write_text(json.dumps(marker))
    profile = evidence / "sandbox.sb"
    profile.write_text(sandbox_profile(run_root))
    (evidence / "source-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return evidence, run_root, repo, canary, profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout 必须为正数")
    source = Path(__file__).resolve().parents[1]
    try:
        evidence, run_root, repo, canary, profile = prepare_run(source)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"ISOLATION_REFUSED: {exc}", file=sys.stderr)
        return 2
    environment = child_environment(repo, run_root)
    prefix = ["/usr/bin/sandbox-exec", "-f", str(profile), sys.executable]
    print(f"隔离测试证据: {evidence}", flush=True)
    probe = run_child(prefix + ["-I", "-c", boundary_probe(canary)], repo, environment,
                      evidence / "boundary-probe.log", 30)
    test_args = args.pytest_args
    if test_args[:1] == ["--"]:
        test_args = test_args[1:]
    receipt = {
        "source": str(source), "snapshot": str(repo), "probe": probe,
        "pytest_arguments": test_args, "timeout_seconds": args.timeout,
        "source_manifest_sha256": hashlib.sha256((evidence / "source-manifest.json").read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
    }
    if probe["exit_code"] == 0:
        result = run_child(prefix + ["-m", "pytest", "-p", "no:cacheprovider", "-p", "pytest_asyncio.plugin",
                                    "--basetemp", str(run_root / "pytest-tmp"),
                                    "--junitxml", str(run_root / "pytest.xml")] + test_args,
                           repo, environment, evidence / "pytest.log", args.timeout)
        receipt["pytest"] = result
    else:
        result = {"exit_code": 2}
        print("ISOLATION_REFUSED: 边界探针未通过；未启动 pytest", file=sys.stderr)
    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
