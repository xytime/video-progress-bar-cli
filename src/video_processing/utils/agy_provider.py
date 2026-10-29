"""agy CLI 的受限结构化文本调用封装。

输入作为无 shell 的单个进程参数传递、在临时空目录内执行，并且只接受 JSON
Schema 验证后的 ``structured_output``。本模块不保存 prompt、字幕或账号信息。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.4.5 | 2026-10-30 | Codex | 空成功结果保留明确地域错误分类，状态码须有语境，避免时间戳误判。 |
| 1.4.4 | 2026-10-20 | Codex | 关闭会返回空成功的 CLI 内部计时，由宿主超时识别基础设施故障。 |
| 1.4.3 | 2026-10-15 | Antigravity | 自动映射已退役 gemini-3.7-flash-high 模型别名，并细分 model unavailable / location ineligible 脱敏分类。 |
| 1.4.2 | 2026-09-25 | Codex | 将结构化 Schema 400 错误归入安全分类，保留退出码且不回显原始内容。 |
| 1.4.1 | 2026-09-22 | Codex | 区分本地启动受限与服务鉴权失败，提供无模型调用的启动预检。 |
| 1.4.0 | 2026-09-22 | Codex | 允许调用方提供最小运行环境，独立 App 文案不继承业务 API 凭据。 |
| 1.3.0 | 2026-09-18 | Antigravity | 支持根据模型后缀(-high/-low)自动推断 effort，避免参数冲突 |
| language-v1 | 2026-09-09 | Codex | 可选返回供应商原始用量，不改变现有结构化调用返回合同。 |
| 1.1.0 | 2026-08-24 | Codex | 禁用 print-mode 指令扩展，并将外部错误压缩为非敏感分类。 |
| 1.2.0 | 2026-09-17 | Codex | 支持显式传递 low/medium/high effort，避免模型名被误当作推理强度。 |
| 1.0.0 | 2026-08-24 | Codex | 新增 agy 受限结构化调用，供字幕与普通话配音精修共享 |
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from typing import Any, Dict, Optional

_RETIRED_MODEL_ALIASES: Dict[str, str] = {
    "gemini-3.7-flash-high": "gemini-3.8-flash-high",
}


class AgyProviderError(RuntimeError):
    """agy 不可用、超时或未返回合格结构化输出。"""


def _normalize_agy_model(model: str) -> str:
    return _RETIRED_MODEL_ALIASES.get(str(model).strip(), str(model))


def run_agy_structured(
    prompt: str,
    *,
    schema: Dict[str, Any],
    model: str,
    command: str,
    timeout_sec: int,
    effort: Optional[str] = None,
    include_usage: bool = False,
    environment: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """在无业务工作区、无危险权限下调用 agy 并提取结构化输出。"""
    model = _normalize_agy_model(model)
    if effort is None:
        if str(model).endswith("-high"):
            effort = "high"
        elif str(model).endswith("-low"):
            effort = "low"
        else:
            effort = "medium"
    effort = str(effort).lower()
    if effort not in {"low", "medium", "high"}:
        raise ValueError("agy effort 必须是 low、medium 或 high")
    args = [
        command,
        "--mode", "plan",
        "--sandbox",
        "--disable-slash-commands",
        "--model", model,
        "--effort", effort,
        "--json-schema", json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
        "--output-format", "json",
        # CLI 内部超时可能以 exit=0、空 SUCCESS 返回，无法可靠区分无效输出。
        # 关闭内部计时，只由下方宿主超时产生可识别的基础设施故障。
        "--print-timeout", "0s",
        f"--print={prompt}",
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="video-processing-agy-") as workdir:
            result = subprocess.run(
                args,
                cwd=workdir,
                input="",
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=max(1, int(timeout_sec)) + 15,
                check=False,
                **({"env": environment} if environment is not None else {}),
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
        # CLI 可能把真实生成错误包装为 exit=0；只恢复既有明确地域分类，
        # 其他空结果仍为无效输出，不能因初始化警告触发供应商兜底。
        if _safe_failure_category(result.stderr) == "location ineligible":
            raise AgyProviderError("agy returned no structured_output: location ineligible")
        raise AgyProviderError("agy returned no structured_output")
    if include_usage:
        return {"structured_result": structured, "usage": envelope.get("usage")}
    return structured


def _safe_failure_category(value: str | None) -> str:
    """将外部错误压缩为稳定分类，避免任何 prompt 或运行环境回显泄漏。"""
    text = (value or "").lower()
    if ("failed to start" in text and "operation not permitted" in text
            and ("listen tcp" in text or "creating log file" in text)):
        return "local startup blocked"
    if "invalid_argument" in text and ("schema" in text or "function_declarations" in text):
        return "invalid schema"
    if any(token in text for token in ("eligibility check failed", "not currently available in your location",
                                      "location_not_eligible", "user location is not supported")):
        return "location ineligible"
    if any(token in text for token in ("model unavailable", "unknown model", "unsupported model", "model not found")):
        return "model unavailable"
    def status(code):
        return re.search(rf"\b(?:http(?:/\d(?:\.\d)?)?|status(?:_code)?|code)\s*[=:]?\s*{code}\b", text)

    if status(429) or re.search(r"\b429\s+too many requests\b|\bquota\b|\brate limit\b|\bresource_exhausted\b", text):
        return "rate limit"
    if (status(401) or status(403)
            or re.search(r"\b(?:401\s+unauthorized|403\s+(?:forbidden|permission denied)|permission_denied|unauthorized)\b", text)):
        return "permission"
    if any(token in text for token in ("timeout", "timed out")):
        return "timeout"
    return "provider error"


def probe_agy_startup(*, command: str, model: str) -> dict:
    """只查询模型列表验证本地启动；不调用模型，不保留原始账号输出。"""
    model = _normalize_agy_model(model)
    try:
        with tempfile.TemporaryDirectory(prefix="video-processing-agy-probe-") as workdir:
            result = subprocess.run(
                [command, "models"], cwd=workdir, input="", text=True,
                capture_output=True, timeout=45, check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgyProviderError("agy startup probe unavailable") from exc
    if result.returncode:
        raise AgyProviderError("agy startup probe: " + _safe_failure_category(result.stderr or result.stdout))
    available = {line.split()[0] for line in result.stdout.splitlines() if line.strip()}
    if model not in available:
        raise AgyProviderError("agy startup probe: requested model unavailable")
    return {"command": "models", "exit_code": 0, "model": model, "model_available": True}
