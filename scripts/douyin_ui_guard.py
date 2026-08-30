"""查询或证据化清除抖音 UI 漂移跨巡航熔断。

默认只读显示全部阶段。清除操作必须同时给出阶段和 24 小时内由抖音上传器生成的、
与该阶段匹配的控件 JSON；脚本不打开浏览器、不上传、不点击发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 新增抖音 UI 熔断状态与校准证据约束清除入口 |
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_DIR = PROJECT_ROOT / "output" / "douyin_calibration"
MAX_EVIDENCE_AGE_SECONDS = 24 * 60 * 60
STAGE_EVIDENCE_NAMES = {
    "publish_pre_submit": {"douyin_ready_to_submit_controls.json"},
    "management_verify": {"douyin_management_evidence_controls.json"},
}

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings  # noqa: E402
from video_processing.db.database import PipelineDB  # noqa: E402


def _resolve_calibration_evidence(
    stage: str,
    evidence_path: Path,
    *,
    calibration_dir: Path = CALIBRATION_DIR,
    now_epoch: float | None = None,
) -> Path:
    """验证证据来自固定目录、阶段匹配、足够新且包含真实创作者中心控件。"""
    if stage not in STAGE_EVIDENCE_NAMES:
        raise ValueError(f"未知 UI 阶段：{stage}")
    candidate = evidence_path if evidence_path.is_absolute() else PROJECT_ROOT / evidence_path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(calibration_dir.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError("校准证据必须是 output/douyin_calibration 内的现有文件") from exc
    if not resolved.is_file() or resolved.name not in STAGE_EVIDENCE_NAMES[stage]:
        expected = ", ".join(sorted(STAGE_EVIDENCE_NAMES[stage]))
        raise ValueError(f"阶段 {stage} 仅接受证据：{expected}")
    age = float(time.time() if now_epoch is None else now_epoch) - resolved.stat().st_mtime
    if age < -300 or age > MAX_EVIDENCE_AGE_SECONDS:
        raise ValueError("校准证据必须在最近 24 小时内生成")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("校准控件 JSON 无法读取或解析") from exc
    page = payload.get("page") if isinstance(payload, dict) else None
    controls = payload.get("controls") if isinstance(payload, dict) else None
    url = str(page.get("url") or "") if isinstance(page, dict) else ""
    if urlparse(url).hostname != "creator.douyin.com" or not isinstance(controls, list) or not controls:
        raise ValueError("校准证据缺少抖音创作者中心 URL 或非空控件列表")
    expected_url_fragment = "/content/manage" if stage == "management_verify" else "/content/upload"
    if expected_url_fragment not in url:
        raise ValueError(f"校准证据页面与阶段不匹配，URL 必须包含 {expected_url_fragment}")
    return resolved


def get_guard_status(db: PipelineDB) -> dict[str, Any]:
    """返回结构化只读状态。"""
    return {
        "platform": "douyin",
        "recording_threshold": max(1, int(settings.douyin_ui_failure_recording_threshold or 1)),
        "stages": db.get_platform_ui_failure_streaks("douyin"),
    }


def clear_guard_after_calibration(
    db: PipelineDB,
    stage: str,
    evidence_path: Path,
    *,
    calibration_dir: Path = CALIBRATION_DIR,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """证据满足契约后清除单一阶段；不删除失败历史。"""
    evidence = _resolve_calibration_evidence(
        stage,
        evidence_path,
        calibration_dir=calibration_dir,
        now_epoch=now_epoch,
    )
    cleared = db.clear_platform_ui_failure_streak("douyin", stage, str(evidence))
    if not cleared:
        raise ValueError(f"阶段 {stage} 没有可清除的熔断记录")
    return {"cleared": True, "stage": stage, "evidence": str(evidence)}


def main() -> int:
    parser = argparse.ArgumentParser(description="查询或证据化清除抖音 UI 漂移熔断")
    parser.add_argument("--clear-stage", choices=sorted(STAGE_EVIDENCE_NAMES))
    parser.add_argument("--calibration-evidence", type=Path)
    args = parser.parse_args()
    if bool(args.clear_stage) != bool(args.calibration_evidence):
        parser.error("--clear-stage 与 --calibration-evidence 必须同时提供")
    db = PipelineDB()
    try:
        if args.clear_stage:
            result = clear_guard_after_calibration(
                db,
                args.clear_stage,
                args.calibration_evidence,
            )
        else:
            result = get_guard_status(db)
    except ValueError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
