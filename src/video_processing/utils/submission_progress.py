"""投稿动作前先落盘意图；只有明确未执行提交的凭据允许技术重试。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

PRE_SUBMIT_BROWSER_CLOSED = 15
NAME = "submission_progress.json"


def write_progress(directory: Path, video: str, *, submit_intent: bool = False) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / NAME
    if path.exists():
        prior = json.loads(path.read_text())
        if prior.get("submit_intent") is not False or prior.get("video") != str(Path(video).resolve()):
            raise ValueError("existing submission intent cannot be reset")
    data = {"version": 1, "video": str(Path(video).resolve()), "submit_intent": submit_intent,
            "updated_at": time.time()}
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def proven_pre_submit(directory: Path, video: str) -> bool:
    try:
        data = json.loads((directory / NAME).read_text())
        return (data.get("version") == 1 and data.get("submit_intent") is False
                and data.get("video") == str(Path(video).resolve())
                and 0 <= time.time() - float(data["updated_at"]) < 3600
                and not (directory / "submission_receipt.json").exists()
                and not (directory / "post_list_after_submission.png").exists())
    except (OSError, ValueError, TypeError, KeyError):
        return False
