"""查询或证据化清除抖音 UI 漂移跨巡航熔断。

默认只读显示全部阶段。清除操作必须同时给出阶段和 24 小时内由抖音上传器生成的、
与该阶段匹配的控件 JSON；脚本不打开浏览器、不上传、不点击发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-30 | Codex | 新增抖音 UI 熔断状态与校准证据约束清除入口 |
| 1.1.0 | 2026-08-31 | Codex | 支持将同次英语世界最终预检证据受控采纳到校准目录，兼容当前 post/video 页面且拒绝无封面/检测通过证明的材料。 |
"""
from __future__ import annotations

import argparse
import json
import shutil
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
_PRE_SUBMIT_URL_FRAGMENTS = ("/content/upload", "/content/post/video")
_ENGLISH_WORLD_PRE_SUBMIT_COMPANIONS = (
    "douyin_cover_applied.json",
    "douyin_cover_applied.png",
    "douyin_preflight_ready_controls.json",
    "douyin_ready_to_submit.png",
)

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
    _validate_stage_evidence(stage, resolved, now_epoch=now_epoch)
    return resolved


def _validate_stage_evidence(
    stage: str,
    resolved: Path,
    *,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """校验阶段证据内容；调用者单独决定它是否位于可信目录。"""
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
    if stage == "management_verify":
        if "/content/manage" not in url:
            raise ValueError("校准证据页面与阶段不匹配，管理页 URL 必须包含 /content/manage")
    elif not any(fragment in url for fragment in _PRE_SUBMIT_URL_FRAGMENTS):
        raise ValueError("校准证据页面与阶段不匹配，投稿页 URL 必须包含 /content/upload 或 /content/post/video")
    return payload


def adopt_english_world_preflight_evidence(
    evidence_path: Path,
    *,
    calibration_dir: Path = CALIBRATION_DIR,
    project_root: Path = PROJECT_ROOT,
    now_epoch: float | None = None,
) -> Path:
    """受控采纳一次完整英语世界预检；只复制证据，不打开浏览器或触发投稿。"""
    candidate = evidence_path if evidence_path.is_absolute() else project_root / evidence_path
    try:
        source = candidate.resolve(strict=True)
        relative = source.relative_to((project_root / "output" / "english_world_daily").resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError("仅可采纳 output/english_world_daily 内的现有最终预检证据") from exc
    if (
        source.name != "douyin_ready_to_submit_controls.json"
        or "douyin_evidence" not in relative.parts
    ):
        raise ValueError("仅可采纳英语世界同次 douyin_ready_to_submit_controls.json")
    payload = _validate_stage_evidence("publish_pre_submit", source, now_epoch=now_epoch)
    page = payload.get("page") if isinstance(payload, dict) else {}
    preview = str(page.get("bodyTextPreview") or "") if isinstance(page, dict) else ""
    if "封面效果检测通过" not in preview or "作品未见异常" not in preview:
        raise ValueError("最终预检证据缺少封面效果检测通过或作品未见异常证明")
    enabled_publish = any(
        str(control.get("text") or "").strip() == "发布" and not bool(control.get("disabled"))
        for control in payload.get("controls", [])
        if isinstance(control, dict)
    )
    if not enabled_publish:
        raise ValueError("最终预检证据缺少可用的发布按钮")

    for name in _ENGLISH_WORLD_PRE_SUBMIT_COMPANIONS:
        companion = source.parent / name
        if not companion.is_file() or companion.stat().st_size <= 0:
            raise ValueError(f"最终预检证据缺少同次必要材料：{name}")
    _validate_stage_evidence(
        "publish_pre_submit",
        source.parent / "douyin_preflight_ready_controls.json",
        now_epoch=now_epoch,
    )

    destination_dir = calibration_dir / "publish_pre_submit" / source.parent.name
    destination = destination_dir / source.name
    if destination.exists():
        if destination.read_bytes() != source.read_bytes():
            raise ValueError("同名校准证据已存在且内容不一致，拒绝覆盖")
    else:
        destination_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return _resolve_calibration_evidence(
        "publish_pre_submit", destination, calibration_dir=calibration_dir, now_epoch=now_epoch,
    )


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
    parser.add_argument(
        "--adopt-english-world-preflight-evidence", type=Path,
        help="只采纳一次完整英语世界最终预检证据到校准目录；不清除熔断、不打开浏览器",
    )
    args = parser.parse_args()
    if args.adopt_english_world_preflight_evidence and (args.clear_stage or args.calibration_evidence):
        parser.error("--adopt-english-world-preflight-evidence 不能与清除参数同时使用")
    if bool(args.clear_stage) != bool(args.calibration_evidence):
        parser.error("--clear-stage 与 --calibration-evidence 必须同时提供")
    db = PipelineDB()
    try:
        if args.adopt_english_world_preflight_evidence:
            result = {
                "adopted": str(adopt_english_world_preflight_evidence(
                    args.adopt_english_world_preflight_evidence,
                )),
            }
        elif args.clear_stage:
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
