"""在一次性源码副本与 macOS 进程沙盒中运行 pytest。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.0 | 2026-10-29 | Codex | 记录真实后代 birth 并回收已观察的独立后台会话，清理失败显式失败。 |
| 1.0.0 | 2026-09-08 | Codex | 收集前隔离配置、源码、输出、网络和子进程；保留快照与真实退出收据 |
| 1.1.0 | 2026-09-08 | Codex | 显式浏览器模式复制运行依赖，保留版本收据与原有默认隔离 |
| 1.2.0 | 2026-09-08 | Codex | 显式媒体模式复制已校验离线模型，浏览器使用标准快照缓存布局 |
| 1.3.0 | 2026-09-19 | Codex | 精确纳入评论策略只读种子，仍排除 data 中的运行数据 |
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time


SOURCE_DIRS = {"src", "scripts", "tests", "resources", "assets", "config", "docs"}
SOURCE_FILES = {"pyproject.toml", "setup.py", "requirements.txt", ".env.example", "data/comment_strategies.json",
                "vpanel", "vhelp"}
MARKER = ".test-sandbox.json"
TEST_VOLUME = Path("/Volumes/EXT2T")
TEST_RUNS = TEST_VOLUME / "AppDataOffload/ryusei/TestRuns"


def create_evidence():
    """扩展盘缺失时拒绝运行，绝不在主盘创建大副本。"""
    if not TEST_VOLUME.is_mount():
        raise ValueError("测试扩展盘 EXT2T 未挂载；不回退主盘")
    root = TEST_RUNS.resolve()
    if not root.is_relative_to(TEST_VOLUME.resolve()):
        raise ValueError("测试目录必须位于 EXT2T 内")
    root.mkdir(parents=True, exist_ok=True)
    if root.stat().st_dev != TEST_VOLUME.stat().st_dev:
        raise ValueError("测试目录不在 EXT2T 文件系统内")
    return Path(tempfile.mkdtemp(prefix="video-pytest-", dir=root)).resolve()


def finish_run(evidence, receipt, keep_sandbox=False):
    """保留宿主日志/收据与 JUnit，仅回收本次创建的副本。"""
    root = evidence / "sandbox"
    cleanup = {"status": "retained" if keep_sandbox else "removed", "path": str(root)}
    try:
        if root.is_symlink():
            raise ValueError("拒绝清理链接形式的 sandbox")
        junit = root / "pytest.xml"
        if junit.is_file() and not junit.is_symlink():
            shutil.copy2(junit, evidence / "pytest.xml")
        if root.exists() and not keep_sandbox:
            shutil.rmtree(root)
    except (OSError, ValueError) as exc:
        cleanup.update(status="failed", error_type=type(exc).__name__, error=str(exc))
    receipt["cleanup"] = cleanup
    if cleanup["status"] == "failed" and receipt.get("exit_code") == 0:
        receipt["exit_code"] = 3
    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2))
    return cleanup["status"] != "failed"


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
        # 持续记录内核归属，覆盖 Web 测试启动的 start_new_session 后台执行器。
        from test_process_tree import ProcessTree
        tree = ProcessTree(process.pid)
        try:
            while process.poll() is None:
                tree.capture()
                if time.monotonic() - started >= timeout:
                    raise subprocess.TimeoutExpired(command, timeout)
                time.sleep(.02)
            code = process.returncode
        except subprocess.TimeoutExpired:
            code = 124
        except KeyboardInterrupt:
            code = 130
        finally:
            cleanup = tree.cleanup()
            process.wait()
    return {"exit_code": code if not cleanup['remaining'] else 3,
            "seconds": round(time.monotonic() - started, 3), "process_cleanup": cleanup}


def process_lifecycle_probe(run_root, environment, evidence):
    """宿主测试实际 setsid 后代回收；沙盒内无全局子进程枚举权限。"""
    from test_process_tree import ProcessTree
    import textwrap
    target = run_root/'lifecycle-child.json'
    unrelated = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'],
                                 cwd=run_root, env=environment)
    code = textwrap.dedent("""
        import subprocess, sys, time, json
        child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'], start_new_session=True)
        open(sys.argv[1], 'w').write(json.dumps(child.pid))
        time.sleep(.5)
    """)
    try:
        result = run_child([sys.executable, '-I', '-c', code, str(target)], run_root, environment,
                           evidence/'process-lifecycle.log', 5)
        child_pid = json.loads(target.read_text())
        result['detached_child_reaped'] = child_pid in result['process_cleanup']['killed']
        result['unrelated_survived'] = unrelated.poll() is None
        result['ok'] = (result['exit_code'] == 0 and result['detached_child_reaped']
                        and result['unrelated_survived'] and not result['process_cleanup']['remaining'])
        return result
    finally:
        unrelated.kill()
        unrelated.wait()


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


def prepare_run(source, evidence):
    if sys.prefix == sys.base_prefix:
        raise ValueError("必须使用项目 .venv/bin/python")
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("需要可用的 macOS sandbox-exec；禁止退回裸 pytest")
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


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--browser", action="store_true", help="复制本机 Chromium 并允许其内部 rendezvous IPC")
    parser.add_argument("--media", action="store_true", help="校验并复制本机 Whisper tiny/base；不联网下载")
    parser.add_argument("--keep-sandbox", action="store_true", help="排查时显式保留扩展盘副本及 QA 产物；默认自动回收")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout 必须为正数")
    return args


def execute_run(args, source, evidence, receipt):
    browser = None
    media = None
    evidence, run_root, repo, canary, profile = prepare_run(source, evidence)
    if args.browser:
        from test_browser_runtime import prepare_browser

        browser = prepare_browser(run_root, repo, profile, evidence)
    if args.media:
        from test_media_runtime import prepare_media

        media = prepare_media(run_root, repo, evidence)
    environment = child_environment(repo, run_root)
    if browser is not None:
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(run_root / "browser")
    receipt['process_lifecycle_probe'] = process_lifecycle_probe(run_root, environment, evidence)
    if not receipt['process_lifecycle_probe']['ok']:
        return 3
    prefix = ["/usr/bin/sandbox-exec", "-f", str(profile), sys.executable]
    print(f"隔离测试证据: {evidence}", flush=True)
    probe = run_child(prefix + ["-I", "-c", boundary_probe(canary)], repo, environment,
                      evidence / "boundary-probe.log", 30)
    test_args = args.pytest_args
    if test_args[:1] == ["--"]:
        test_args = test_args[1:]
    receipt.update({
        "source": str(source), "snapshot": str(repo), "probe": probe,
        "pytest_arguments": test_args, "timeout_seconds": args.timeout,
        "source_manifest_sha256": hashlib.sha256((evidence / "source-manifest.json").read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "browser_runtime": None if browser is None else {
            key: browser[key] for key in ("revision", "version", "executable")
        },
        "browser_runtime_sha256": None if browser is None else hashlib.sha256(
            (evidence / "browser-runtime.json").read_bytes()
        ).hexdigest(),
        "media_runtime": media,
        "media_runtime_sha256": None if media is None else hashlib.sha256(
            (evidence / "media-runtime.json").read_bytes()
        ).hexdigest(),
    })
    if probe["exit_code"] == 0:
        result = run_child(prefix + ["-m", "pytest", "-p", "no:cacheprovider", "-p", "pytest_asyncio.plugin",
                                    "--basetemp", str(run_root / "pytest-tmp"),
                                    "--junitxml", str(run_root / "pytest.xml")] + test_args,
                           repo, environment, evidence / "pytest.log", args.timeout)
        receipt["pytest"] = result
    else:
        result = {"exit_code": 2}
        print("ISOLATION_REFUSED: 边界探针未通过；未启动 pytest", file=sys.stderr)
    return result["exit_code"]


def main(argv=None):
    args = parse_arguments(argv)
    source = Path(__file__).resolve().parents[1]
    try:
        evidence = create_evidence()
    except (ValueError, OSError) as exc:
        print(f"ISOLATION_REFUSED: {exc}", file=sys.stderr)
        return 2
    receipt = {"source": str(source), "started_at": datetime.now(timezone.utc).isoformat(),
               "evidence": str(evidence), "storage_policy": "external-auto-cleanup"}
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2))

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    code = 2
    try:
        code = execute_run(args, source, evidence, receipt)
    except KeyboardInterrupt:
        code = 130
        receipt["error_type"] = "KeyboardInterrupt"
    except (ValueError, OSError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
        receipt.update(error_type=type(exc).__name__, error=str(exc))
        print(f"ISOLATION_REFUSED: {exc}", file=sys.stderr)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            receipt["exit_code"] = code
            if not finish_run(evidence, receipt, args.keep_sandbox):
                print(f"CLEANUP_FAILED: {evidence}; 查看 receipt.json", file=sys.stderr)
                if code == 0:
                    code = 3
        finally:
            signal.signal(signal.SIGTERM, previous)
            signal.signal(signal.SIGINT, previous_int)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
