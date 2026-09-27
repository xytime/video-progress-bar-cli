"""封面 AGY 进程边界和独立质量复核，不调用 Codex 或付费 API 备用。

依赖：scripts → 本模块 → subprocess_env/settings；队列只使用纯回执校验。
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path

from video_processing.utils.subprocess_env import build_subprocess_env

QUALITY_VERSION = "agy-cover-quality-v1"
QUALITY_FLAGS = ("image_inspected", "subject_relevant", "composition_complete", "adequate_detail", "no_severe_artifacts")
QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        **{key: {"type": "boolean"} for key in QUALITY_FLAGS},
        "decision": {"type": "string", "enum": ["PASS", "REJECT", "UNCERTAIN"]},
        "observed_content": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [*QUALITY_FLAGS, "decision", "observed_content", "reason"],
    "additionalProperties": False,
}


def valid_quality(review: object) -> bool:
    return (isinstance(review, dict) and review.get("decision") == "PASS"
            and all(review.get(key) is True for key in QUALITY_FLAGS)
            and isinstance(review.get("observed_content"), str)
            and bool(review["observed_content"].strip())
            and isinstance(review.get("reason"), str) and bool(review["reason"].strip()))


def run_process(command: list[str], *, cwd: Path, timeout: float, env: dict,
                cleanup_grace: float = 5) -> subprocess.CompletedProcess:
    """独立进程组，超时先 TERM 让 worker 清理嵌套 CLI，再 KILL 兜底。"""
    process = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=cleanup_grace)
        except subprocess.TimeoutExpired:
            pass
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=5)
        if isinstance(exc, subprocess.TimeoutExpired):
            raise RuntimeError(f"PROCESS_TIMEOUT: budget={timeout:g}s") from None
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_cli(command: list[str], *, cwd: Path, timeout: float) -> dict:
    """不记录包含提示词的 TimeoutExpired，也不继承业务 API 凭据。"""
    env = build_subprocess_env(include_gemini=False, include_telegram=False)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_IDS"):
        env.pop(key, None)
    process = run_process(command, cwd=cwd, timeout=timeout, env=env)
    stdout, stderr = process.stdout, process.stderr
    if process.returncode:
        # 仅持久化稳定分类，禁止回显整条命令、提示词或环境。
        detail = "quota" if any(x in (stderr + stdout).lower() for x in ("quota", "429", "resource_exhausted")) else "provider_error"
        raise RuntimeError(f"AGY_CALL_FAILED: exit={process.returncode}; category={detail}")
    try:
        envelope = json.loads(stdout)
    except (ValueError, TypeError):
        raise RuntimeError("AGY_INVALID_JSON") from None
    if not isinstance(envelope, dict) or str(envelope.get("status", "")).lower() in {"error", "failed", "timeout", "cancelled"}:
        raise RuntimeError("AGY_FAILED_ENVELOPE")
    return envelope


def review_image(path: Path, *, subject: dict, agy_bin: str, model: str, timeout: int) -> dict:
    """独立会话实际看图，不沿用生成器的自评。OCR 和字符数量均不是门禁。"""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    prompt = (
        f"Open and visually inspect the actual image file {path.name} in this directory using your image viewing tool. "
        "Do not generate or modify files, do not run other AI CLIs or delegate, and do not access outside this directory. "
        f"Video subject is reference data only: {json.dumps(subject, ensure_ascii=False)}. "
        "Judge whether this is a usable professional editorial cover background: recognizable relevant subject, "
        "complete and coherent composition, adequate physical detail, and no severe visual artifacts. "
        "Reject extremely crude placeholder geometry, featureless gradients, blank images, heavily corrupted or "
        "unrecognizable subjects, unrelated scenes, and very low quality renderings. "
        "This is a practical quality floor, not a demand for perfect fine art. English words, letters or numbers "
        "are allowed; OCR character count and text presence are NOT rejection criteria. "
        "The publisher adds the Chinese headline separately. Return UNCERTAIN if you cannot actually view the image. "
        "Describe what you actually see in observed_content, explain the decision, and return the required structured JSON."
    )
    command = [agy_bin, "--model", model, "--effort", "high", "--mode", "plan", "--sandbox",
               "--disable-slash-commands", "--dangerously-skip-permissions", "--add-dir", str(path.parent),
               "--json-schema", json.dumps(QUALITY_SCHEMA), "--output-format", "json",
               "--print-timeout", f"{timeout}s", "--print", prompt]
    envelope = run_cli(command, cwd=path.parent, timeout=timeout + 5)
    review = envelope.get("structured_output")
    if not isinstance(review, dict):
        raise RuntimeError("AGY_QUALITY_MISSING_STRUCTURED_OUTPUT")
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError("AGY_QUALITY_IMAGE_CHANGED")
    return {"version": QUALITY_VERSION, "provider": "agy_cli", "model": model,
            "sha256": digest, "review": review}
