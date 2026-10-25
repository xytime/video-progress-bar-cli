"""合规二创入口的受控能力装配。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | GPT-6.1 Sol | 外层封面工具注入，未接通治理的发布能力明确阻断 |
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from video_processing.compliance_remix.remix_pipeline import ComplianceVideoRemixPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def generate_cover(payload, cover_path, provenance_path):
    """仅由已批准的流水线调用现有封面入口，不改变其来源治理。"""
    process = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "scripts/cover_generator.py"),
         "--payload", json.dumps(payload, ensure_ascii=False), "--output", str(cover_path),
         "--provenance-output", str(provenance_path)],
        cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        _, error = process.communicate(timeout=300)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise
    if process.returncode:
        raise RuntimeError(f"标准封面工具失败 rc={process.returncode}: {error[-1000:]}")


def submit_wechat(*args, **kwargs):
    """手工发布租约、四件套指纹与提交账本尚未接通，因此禁止调用上传器。"""
    raise PermissionError(
        "COMPLIANCE_REMIX_PUBLICATION_UNAVAILABLE: 尚未接通现有手动发布租约、"
        "配额退避与提交账本；本次未启动上传器。请通过既有受治理发布入口审核成片。"
    )


# 在任何昂贵制作动作之前暴露同一能力阻断。
submit_wechat.preflight = submit_wechat

def build_pipeline(work_dir, **kwargs):
    return ComplianceVideoRemixPipeline(
        work_dir, cover_adapter=generate_cover, submission_adapter=submit_wechat, **kwargs)
