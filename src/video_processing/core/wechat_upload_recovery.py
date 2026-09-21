"""视频号提交前上传故障凭据；依赖仅为标准库，供上传器、管线和 DAL 共用。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-21 | Codex | 定义零进度、未进入发表阶段的单次上传超时凭据与校验。 |
"""

import json
import re
from pathlib import Path

PRE_SUBMIT_UPLOAD_TIMEOUT = 7
RECEIPT_NAME = "pre_submit_upload_timeout.json"


def is_zero_progress_upload(text: str) -> bool:
    """只接受仍有取消上传控件、且所有可见百分数均明确为零的页面。"""
    percentages = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[%％]", text)
    return (
        "取消上传" in text
        and bool(percentages)
        and all(float(value) == 0 for value in percentages)
        and not any(word in text for word in ("上传成功", "上传完成", "发表成功", "审核中"))
    )


def write_timeout_receipt(evidence_dir: Path, video_path: str, visible_text: str) -> bool:
    """仅由上传等待阶段调用；截图不完整或目录已存在提交证据时拒绝签发。"""
    if not is_zero_progress_upload(visible_text):
        return False
    screenshot = evidence_dir / "upload_timeout.png"
    if not screenshot.is_file() or screenshot.stat().st_size == 0:
        return False
    if any((evidence_dir / name).exists() for name in (
        "post_list_after_submission.png", "submission_receipt.json",
    )):
        return False
    receipt = {
        "schema": 1,
        "state": "PRE_SUBMIT_UPLOAD_TIMEOUT",
        "attempt_id": evidence_dir.name,
        "video_path": str(Path(video_path).resolve()),
        "stage": "WAITING_FOR_UPLOAD",
        "submit_attempted": False,
        "visible_text": visible_text,
    }
    # 独占创建防止旧凭据被覆写成一次新的重试授权。
    with (evidence_dir / RECEIPT_NAME).open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False)
    return True


def valid_timeout_receipt(evidence_dir: Path, video_path: str) -> bool:
    """调用方必须传本次子进程独立证据目录，不得扫描历史目录来恢复旧任务。"""
    try:
        receipt = json.loads((evidence_dir / RECEIPT_NAME).read_text(encoding="utf-8"))
        screenshot = evidence_dir / "upload_timeout.png"
        return (
            isinstance(receipt, dict)
            and receipt.get("schema") == 1
            and receipt.get("state") == "PRE_SUBMIT_UPLOAD_TIMEOUT"
            and receipt.get("attempt_id") == evidence_dir.name
            and receipt.get("video_path") == str(Path(video_path).resolve())
            and receipt.get("stage") == "WAITING_FOR_UPLOAD"
            and receipt.get("submit_attempted") is False
            and isinstance(receipt.get("visible_text"), str)
            and is_zero_progress_upload(receipt["visible_text"])
            and screenshot.is_file() and screenshot.stat().st_size > 0
            and not any((evidence_dir / name).exists() for name in (
                "post_list_after_submission.png", "submission_receipt.json",
            ))
        )
    except (OSError, ValueError, TypeError):
        return False
