"""Codex CLI 的经济型、无工具结构化文字入口；不参与上传或发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.2 | 2026-10-31 | Codex | 显式只读缓存及带 HTTP 语境的认证/限流分类；保留原重试边界。 |
| 1.4.0 | 2026-10-28 | Codex | 接受流重连后有终态且通过结构/质量合同的输出，不把恢复提示当最终失败。 |
| 1.3.0 | 2026-10-27 | Codex | 真实执行前允许调用方持久领取预算，缓存、锁和冷却不消耗请求次数。 |
| 1.2.0 | 2026-10-27 | Codex | 字幕质量合同隔离缓存身份，保存有界宿主拒绝信号并在原预算内重建失效缓存。 |
| 1.1.0 | 2026-10-20 | Codex | 英语世界安全审核可显式附图，图片指纹纳入缓存身份；仍禁用工具。 |
| 1.0.0 | 2026-10-03 | Codex | 独立 Luna 文字入口：最小环境、进程组期限、严格结构、单并发与用量回执。 |
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

from jsonschema import Draft202012Validator, ValidationError

from config.settings import settings


ECONOMY_MODELS = frozenset({"gpt-6-luna", "gpt-5.6-luna"})


def _safe_quality_details(details) -> list[dict]:
    """只保留宿主生成的位置、分类与短事实信号，不接收正文或提示词字段。"""
    safe = []
    for detail in details or ():
        if not isinstance(detail, dict):
            continue
        segment_number, source_id = detail.get("segment_number"), detail.get("source_id")
        if type(segment_number) is not int or segment_number < 1 or type(source_id) is not int or source_id < 0:
            continue
        safe.append({
            "segment_number": segment_number, "source_id": source_id,
            **{key: str(detail.get(key, "")).replace("\n", " ").replace("\r", " ")[:120]
               for key in ("code", "source_signal", "translation_signal")},
        })
        if len(safe) >= 10:
            break
    return safe


class CodexTextError(RuntimeError):
    """仅包含安全分类和宿主信号，禁止回显 prompt、模型原文及 CLI 原始日志。"""

    def __init__(self, code: str, retry_at: int = 0, *, quality_details=()):
        self.code = code
        self.retry_at = retry_at
        self.quality_details = _safe_quality_details(quality_details)
        super().__init__(f"codex_text:{code}")


@dataclass(frozen=True)
class CodexTextResult:
    payload: dict
    model: str
    usage: dict
    duration_ms: int
    cached: bool = False


def strict_schema(schema: dict) -> dict:
    """将 Pydantic 的可选字段改为必返字段，不改变字段类型和宿主校验。"""
    result = json.loads(json.dumps(schema))

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    Draft202012Validator.check_schema(result)
    return result


def _execute(args: list[str], prompt: str, directory: Path, timeout: float) -> subprocess.CompletedProcess:
    """输入经 stdin 传递；超时或中断清理整个子进程组。"""
    try:
        process = subprocess.Popen(
            args, cwd=directory, env=settings.agy_app_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
    except OSError:
        raise CodexTextError("command_unavailable") from None
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
    except BaseException as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # 父进程提前退出也不能留下忽略 TERM、关闭了 stdout 的孙进程。
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise CodexTextError("timeout") from None
        raise
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _failure_code(text: str) -> str:
    lowered = text.lower()
    # stderr 含 RFC3339 小数时间戳和 UUID；裸数字子串并不是 HTTP 响应。
    def status(code):
        return bool(re.search(
            rf'\b(?:http(?:/\d(?:\.\d)?)?\s+|(?:http\s+)?status(?:[\s_-]+code)?[\s\"\x27:=]+)'
            rf'{code}\b|\b{code}\s+(?:unauthorized|too many requests)\b', lowered))
    if status(429) or re.search(r'\b(?:usage limit|rate limit|quota|credits)\b', lowered):
        return "quota"
    if status(401) or re.search(r'\b(?:unauthorized|not logged|authentication)\b', lowered):
        return "authentication"
    if "model" in lowered and any(word in lowered for word in ("not supported", "not found", "unavailable")):
        return "model_unavailable"
    return "unavailable"


def _atomic_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False)
    temporary.replace(path)


def _run_codex_structured(
    prompt: str, *, schema: dict, state_dir: Path, command: str,
    model: str = "gpt-5.6-luna", effort: str = "medium", timeout_sec: float = 120,
    validate: Callable[[dict], dict] | None = None,
    cache_prompt: str | None = None,
    images: tuple[Path, ...] = (),
    cache_contract: str = "",
    repair_cached_output: Callable[[str, CodexTextError], str] | None = None,
    before_execute: Callable[[], None] | None = None,
    _request_audit: dict | None = None,
    _cache_only: bool = False,
) -> CodexTextResult | None:
    """一次有界请求；只缓存经调用方质量合同接受的结果，不自动升级模型。"""
    request_started = time.monotonic()
    if model not in ECONOMY_MODELS or effort not in {"low", "medium", "high"} or timeout_sec <= 0:
        raise CodexTextError("configuration")
    schema = strict_schema(schema)
    state_dir.mkdir(parents=True, exist_ok=True)
    image_hashes = [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in images]
    identity_parts = ["codex-text-v1", model, effort, cache_prompt or prompt, schema, image_hashes]
    if cache_contract:
        identity_parts.append(cache_contract)
    identity = json.dumps(identity_parts, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(identity.encode()).hexdigest()
    cached_path = state_dir / f"{key}.json"
    with (state_dir / "provider.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CodexTextError("busy", int(time.time()) + 60) from None
        if validate and cached_path.exists():
            try:
                cached = json.loads(cached_path.read_text(encoding="utf-8"))
                Draft202012Validator(schema).validate(cached["payload"])
            except (ValueError, KeyError, ValidationError):
                if _cache_only:
                    return None
                cached_path.unlink(missing_ok=True)
            else:
                try:
                    payload = validate(cached["payload"])
                except Exception as exc:
                    if _cache_only:
                        raise
                    cached_path.unlink(missing_ok=True)
                    if not isinstance(exc, CodexTextError) or repair_cached_output is None:
                        raise
                    if _request_audit is not None:
                        _request_audit["cache_rejection"] = {
                            "code": exc.code, "quality_details": _safe_quality_details(exc.quality_details),
                        }
                    prompt = repair_cached_output(prompt, exc)
                    timeout_sec -= time.monotonic() - request_started
                    if timeout_sec <= 0:
                        raise CodexTextError("timeout") from None
                else:
                    return CodexTextResult(payload, model, {}, 0, True)
        if _cache_only:
            return None
        cooldown = state_dir / f"{model}.cooldown.json"
        if cooldown.exists():
            try:
                retry_at = int(json.loads(cooldown.read_text())["retry_at"])
            except (ValueError, KeyError):
                raise CodexTextError("state_invalid") from None
            if retry_at > time.time():
                raise CodexTextError("cooldown", retry_at)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="vp-codex-text-") as folder:
            directory = Path(folder)
            schema_path = directory / "schema.json"
            output_path = directory / "result.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            args = [str(Path(command).expanduser()), "exec", "--cd", folder, "--skip-git-repo-check", "--ephemeral",
                    "--ignore-user-config", "--model", model, "--sandbox", "read-only",
                    "--config", f'model_reasoning_effort="{effort}"',
                    "--config", 'web_search="disabled"', "--config", "project_doc_max_bytes=0",
                    "--output-schema", str(schema_path), "--output-last-message", str(output_path), "--json"]
            for feature in ("shell_tool", "plugins", "apps", "browser_use", "browser_use_external",
                            "computer_use", "image_generation", "view_image", "multi_agent", "code_mode"):
                args.extend(["--disable", feature])
            for path in images:
                args.extend(["--image", str(Path(path).resolve())])
            args.append("-")
            if before_execute is not None:
                before_execute()
            if _request_audit is not None:
                _request_audit["executed_input_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
            result = _execute(args, prompt, directory, timeout_sec)
            if result.returncode:
                code = _failure_code(result.stderr + result.stdout)
                retry_at = int(time.time()) + (3600 if code in {"quota", "authentication"} else 120)
                _atomic_json(cooldown, {"retry_at": retry_at, "code": code})
                raise CodexTextError(code, retry_at)
            usage = {}
            completed = False
            transport_notice = False
            try:
                for line in result.stdout.splitlines():
                    event = json.loads(line)
                    if event.get("type") == "turn.failed":
                        raise CodexTextError("unavailable")
                    if event.get("type") == "error":
                        # CLI 会把可恢复的流重连也记为 error。只有最终 turn.completed、
                        # 工具禁用检查和结构/质量校验共同通过，才接受恢复后的输出。
                        transport_notice = True
                        continue
                    item = event.get("item", {})
                    if item.get("type") == "error":
                        transport_notice = True
                        continue
                    if item.get("type") not in {None, "agent_message", "reasoning"}:
                        raise CodexTextError("tool_use_rejected")
                    if event.get("type") == "turn.completed":
                        completed = True
                        usage = {key: value for key, value in event.get("usage", {}).items()
                                 if key.endswith("tokens") and isinstance(value, int)}
                if not completed:
                    raise CodexTextError("unavailable" if transport_notice else "incomplete")
                raw = json.loads(output_path.read_text(encoding="utf-8"))
                Draft202012Validator(schema).validate(raw)
            except (ValueError, OSError, ValidationError):
                error = CodexTextError("invalid_output")
                error.usage = usage
                raise error from None
            try:
                payload = validate(raw) if validate else raw
            except Exception as exc:
                exc.usage = usage
                raise
            if validate:
                _atomic_json(cached_path, {"payload": raw, "usage": usage})
            return CodexTextResult(payload, model, usage, int((time.monotonic() - started) * 1000))


def read_codex_cache(prompt: str, **kwargs) -> CodexTextResult | None:
    """迁移传图布局前复用原合同缓存；完整校验，不产生供应商调用或请求回执。"""
    return _run_codex_structured(prompt, _cache_only=True, **kwargs)


def run_codex_structured(prompt: str, **kwargs) -> CodexTextResult:
    """逐请求落安全回执，成功与失败都保留模型、耗时、用量及输入哈希。"""
    started = time.monotonic()
    receipt = {"provider": "codex", "model": kwargs.get("model", "gpt-5.6-luna"),
               "at": int(time.time()), "input_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
    try:
        result = _run_codex_structured(prompt, _request_audit=receipt, **kwargs)
        receipt.update(status="SUCCEEDED", usage=result.usage, cached=result.cached)
        return result
    except BaseException as exc:
        receipt.update(status="FAILED", code=getattr(exc, "code", type(exc).__name__),
                       usage=getattr(exc, "usage", {}))
        details = _safe_quality_details(getattr(exc, "quality_details", ()))
        if details:
            receipt["quality_details"] = details
        raise
    finally:
        receipt["duration_ms"] = int((time.monotonic() - started) * 1000)
        try:
            directory = kwargs["state_dir"]
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        except OSError:
            if receipt["status"] == "SUCCEEDED":
                raise CodexTextError("receipt_unavailable") from None
