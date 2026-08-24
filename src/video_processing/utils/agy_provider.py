"""agy CLI 的受限结构化文本调用封装。

输入作为无 shell 的单个进程参数传递、在临时空目录内执行，并且只接受 JSON
Schema 验证后的 ``structured_output``。本模块不保存 prompt、字幕或账号信息。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-08-24 | Codex | 禁用 print-mode 指令扩展，并将外部错误压缩为非敏感分类。 |
| 1.0.0 | 2026-08-24 | Codex | 新增 agy 受限结构化调用，供字幕与普通话配音精修共享 |
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Any, Dict


class AgyProviderError(RuntimeError):
    """agy 不可用、超时或未返回合格结构化输出。"""


def run_agy_structured(
    prompt: str,
    *,
    schema: Dict[str, Any],
    model: str,
    command: str,
    timeout_sec: int,
) -> Dict[str, Any]:
    """在无业务工作区、无危险权限下调用 agy 并提取结构化输出。"""
    args = [
        command,
        "--mode", "plan",
        "--sandbox",
        "--disable-slash-commands",
        "--model", model,
        "--json-schema", json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
        "--output-format", "json",
        "--print-timeout", f"{max(1, int(timeout_sec))}s",
        f"--print={prompt}",
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="video-processing-agy-") as workdir:
            result = subprocess.run(
                args,
                cwd=workdir,
                input="",
                text=True,
                capture_output=True,
                timeout=max(1, int(timeout_sec)) + 15,
                check=False,
            )
    except FileNotFoundError as exc:
        raise AgyProviderError("agy command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise AgyProviderError(f"agy timed out after {timeout_sec}s") from exc
    if result.returncode != 0:
        # stdout/stderr 来自外部 CLI；不得把可能回显输入的内容带入数据库、日志或审计产物。
        detail = _safe_failure_category(result.stderr or result.stdout)
        raise AgyProviderError(f"agy exit {result.returncode}: {detail}")
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AgyProviderError("agy returned invalid JSON envelope") from exc
    structured = envelope.get("structured_output") if isinstance(envelope, dict) else None
    if not isinstance(structured, dict):
        raise AgyProviderError("agy returned no structured_output")
    return structured


def _safe_failure_category(value: str | None) -> str:
    """将外部错误压缩为稳定分类，避免任何 prompt 或运行环境回显泄漏。"""
    text = (value or "").lower()
    if any(token in text for token in ("429", "quota", "rate limit", "resource_exhausted")):
        return "rate limit"
    if any(token in text for token in ("401", "403", "permission", "unauthorized")):
        return "permission"
    if any(token in text for token in ("timeout", "timed out")):
        return "timeout"
    return "provider error"
