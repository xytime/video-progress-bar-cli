"""grok CLI 的受限结构化文本调用封装（字幕翻译 CLI 供应商）。

与 agy_provider 同契约：无 shell、临时空目录、禁用全部内置工具/子代理/联网搜索，
只接受 CLI 按 JSON Schema 校验后的 ``structuredOutput``；外部输出只压缩为脱敏分类。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Grok Bot | 新增 grok CLI 结构化调用，作为字幕翻译 agy→codex 之后的 CLI 供应商 |
| 1.1.0 | 2026-11-07 | Grok Bot | 长提示改走文件并原样传递、关闭 plan；schema 去掉说明文字；接受 structured_output。 |
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from .agy_provider import _safe_failure_category

_SCHEMA_DROP = {"description", "title", "default", "examples", "$schema", "$comment"}


class GrokProviderError(RuntimeError):
    """grok 不可用、超时或未返回合格结构化输出。"""


def compact_cli_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """交给 CLI 的结构合同：保留字段和类型，去掉说明文字与默认值。

    宿主仍用完整 Pydantic 模型、标题合同和质量门验收。说明文字留在提示里，
    避免和提示重复后把结构化重试拖过共享预算。
    """
    node = json.loads(json.dumps(schema))

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in list(value):
                if key in _SCHEMA_DROP:
                    value.pop(key, None)
            if value.get("type") == "object" and isinstance(value.get("properties"), dict):
                value["required"] = list(value["properties"])
                value.setdefault("additionalProperties", False)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(node)
    return node


def run_grok_structured(
    prompt: str,
    *,
    schema: Dict[str, Any],
    command: str,
    timeout_sec: float,
    model: str = "",
    environment: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """单轮、无工具调用 grok 并返回结构化输出。

    全文案提示含来源链接。CLI 若展开模板或进入 plan，会在宿主 150 秒预算内空转；
    因此提示走文件、原样传递，并显式关闭 plan。不提高超时、不改模型。
    """
    with tempfile.TemporaryDirectory(prefix="video-processing-grok-") as workdir:
        prompt_path = Path(workdir) / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        schema_text = json.dumps(
            compact_cli_schema(schema), ensure_ascii=False, separators=(",", ":"),
        )
        args = [
            command, "-p", "--prompt-file", str(prompt_path), "--verbatim", "--no-plan",
            "--cwd", workdir,
            "--json-schema", schema_text,
            "--output-format", "json",
            "--tools", "", "--no-subagents", "--disable-web-search",
            "--max-turns", "1", "--permission-mode", "dontAsk",
            *(["--model", model] if model else []),
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
    structured = _structured_payload(envelope)
    if not isinstance(structured, dict):
        raise GrokProviderError("grok returned no structured output")
    return structured


def _structured_payload(envelope: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(envelope, dict):
        return None
    for key in ("structured_output", "structuredOutput"):
        value = envelope.get(key)
        if isinstance(value, dict):
            return value
    return None
