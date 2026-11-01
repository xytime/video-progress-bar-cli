"""grok CLI 的受限结构化文本调用封装（字幕翻译 CLI 供应商）。

与 agy_provider 同契约：无 shell、临时空目录、禁用全部内置工具/子代理/联网搜索，
只接受 CLI 按 JSON Schema 校验后的 ``structuredOutput``；外部输出只压缩为脱敏分类。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Grok Bot | 新增 grok CLI 结构化调用，作为字幕翻译 agy→codex 之后的 CLI 供应商 |
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Any, Dict, Optional

from .agy_provider import _safe_failure_category


class GrokProviderError(RuntimeError):
    """grok 不可用、超时或未返回合格结构化输出。"""


def run_grok_structured(
    prompt: str,
    *,
    schema: Dict[str, Any],
    command: str,
    timeout_sec: float,
    model: str = "",
    environment: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """单轮、无工具调用 grok 并返回结构化输出。"""
    with tempfile.TemporaryDirectory(prefix="video-processing-grok-") as workdir:
        args = [
            command, "--cwd", workdir,
            "--json-schema", json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
            "--output-format", "json",
            "--tools", "", "--no-subagents", "--disable-web-search",
            "--max-turns", "1", "--permission-mode", "dontAsk",
            *(["--model", model] if model else []),
            "-p", prompt,
        ]
        try:
            result = subprocess.run(
                args, cwd=workdir, input="", text=True, encoding="utf-8", errors="replace",
                capture_output=True, timeout=max(0.001, float(timeout_sec)), check=False,
                **({"env": environment} if environment is not None else {}),
            )
        except FileNotFoundError as exc:
            raise GrokProviderError("grok command not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise GrokProviderError(f"grok timed out after {timeout_sec}s") from exc
    if result.returncode != 0:
        # 外部 CLI 输出可能回显输入；只保留稳定分类。
        detail = _safe_failure_category((result.stderr or "") + "\n" + (result.stdout or ""))
        raise GrokProviderError(f"grok exit {result.returncode}: {detail}")
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GrokProviderError("grok returned invalid JSON envelope") from exc
    structured = envelope.get("structuredOutput") if isinstance(envelope, dict) else None
    if not isinstance(structured, dict):
        raise GrokProviderError("grok returned no structuredOutput")
    return structured
