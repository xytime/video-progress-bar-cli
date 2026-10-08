#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/run_masterpiece.py — 重大新闻 3-5 分钟高品质二创母带独立调度入口 (RFC-2026-DEEP-CREATION-001)。

提供 CLI 与自动化调度入口，支持针对特定 YouTube ID 或链接执行全流程二创编排与母带渲染：
1. 规范脚本加载与 Pydantic 强类型网关出口核查；
2. VTT 事实引证机器门禁双向核验（Fail-Closed）；
3. 100% 完整原片零裁切 + Y=265~555 安全横栏 + 0.6s Dip to Black + 60Hz Hit 空间重音母带装配；
4. 全流程 44.1kHz 音频采样率、音画同轴偏差与媒体规格质检；
5. 三级 SHA-256 收据归档与 DAL 状态机回写。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | 落实 RFC-2026-DEEP-CREATION-001 Milestone 3：独立母带调度 CLI、真实视频影子运行与质检报告输出 |
| 1.1.0 | 2026-10-08 | Antigravity | 扩展字幕候选路径、健全异常下 DAL FAILED 状态回写与 JSON 结构化错误报告输出 |
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# 确保项目根目录与 src/ 在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from video_processing.core.insight_script import InsightScriptV2
from video_processing.processors.insight_processor import (
    InsightProcessor,
    validate_media,
    valid_enrichment,
    probe,
    sha256,
)
from video_processing.utils.insight_planner import verify_vtt_evidence, generate_insight_script
from video_processing.utils.insight_v2_prompt import (
    FEW_SHOT_EXAMPLE_CORNELL,
    FEW_SHOT_EXAMPLE_NOBEL,
)
from video_processing.db.database import PipelineDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("run_masterpiece")


def extract_youtube_id(input_str: str) -> str:
    """从纯 ID 或各种格式的 YouTube 链接中提取 11 位唯一 ID。"""
    match = re.search(r"([A-Za-z0-9_-]{11})", input_str)
    if not match:
        raise ValueError(f"无法从输入识别合法的 11 位 YouTube ID: {input_str}")
    return match.group(1)


def resolve_source_assets(
    youtube_id: str,
    output_dir: Path,
    explicit_video: Optional[Path] = None,
    explicit_subtitle: Optional[Path] = None,
    explicit_script: Optional[Path] = None,
) -> tuple[Path, Path, Path]:
    """定位或生成目标视频的全部输入资产（原片竖版、字幕、二创脚本）。"""
    # 1. 定位竖版基础视频
    if explicit_video and explicit_video.is_file():
        source_video = explicit_video
    else:
        candidates = [
            output_dir / f"{youtube_id}_vertical.mp4",
            PROJECT_ROOT / f"output/{youtube_id}_vertical.mp4",
            PROJECT_ROOT / f"experiments/hyperframes_quality_upgrade_RaUWCtcJtK8/raw/{youtube_id}_vertical.mp4",
        ]
        source_video = next((c for c in candidates if c.is_file()), None)
        if not source_video:
            raise FileNotFoundError(
                f"未找到目标视频基础竖版成片 ({youtube_id}_vertical.mp4)，请先完成常规字幕流水线或指定 --source-video"
            )

    # 2. 定位原始字幕
    if explicit_subtitle and explicit_subtitle.is_file():
        subtitle_path = explicit_subtitle
    else:
        sub_candidates = [
            output_dir / f"{youtube_id}_source_subtitle.en.vtt",
            PROJECT_ROOT / f"output/{youtube_id}_source_subtitle.en.vtt",
            output_dir / f"{youtube_id}.en.vtt",
            PROJECT_ROOT / f"output/{youtube_id}.en.vtt",
            output_dir / f"{youtube_id}.vtt",
            PROJECT_ROOT / f"output/{youtube_id}.vtt",
            output_dir / f"{youtube_id}.ass",
            PROJECT_ROOT / f"output/{youtube_id}.ass",
            PROJECT_ROOT / f"experiments/hyperframes_quality_upgrade_RaUWCtcJtK8/raw/{youtube_id}.en.vtt",
            PROJECT_ROOT / f"tests/fixtures/vtt/{youtube_id}_source_subtitle.en.vtt",
        ]
        subtitle_path = next((c for c in sub_candidates if c.is_file()), None)
        if not subtitle_path:
            raise FileNotFoundError(f"未找到目标视频原文字幕文件，请指定 --subtitle")

    # 3. 定位或准备二创脚本 (InsightScriptV2)
    script_path = explicit_script or (output_dir / f"{youtube_id}_insight.json")
    if not script_path.is_file():
        # 如果是标杆案例，自动装载标杆真理脚本
        if youtube_id == "SfNypZIb0H4":
            logger.info("装载康奈尔特检案标杆脚本 (FEW_SHOT_EXAMPLE_CORNELL) -> %s", script_path)
            script_path.write_text(json.dumps(FEW_SHOT_EXAMPLE_CORNELL, ensure_ascii=False, indent=2), encoding="utf-8")
        elif youtube_id == "RaUWCtcJtK8":
            logger.info("装载光遗传学诺奖标杆脚本 (FEW_SHOT_EXAMPLE_NOBEL) -> %s", script_path)
            script_path.write_text(json.dumps(FEW_SHOT_EXAMPLE_NOBEL, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            logger.info("未发现预置脚本，启动 LLM 自动策划生成 -> %s", script_path)
            ok = generate_insight_script(f"Video {youtube_id}", source_video, subtitle_path, script_path)
            if not ok or not script_path.is_file():
                raise RuntimeError(f"二创脚本自动生成失败，终止调度")

    return source_video, subtitle_path, script_path


def run_masterpiece_pipeline(
    youtube_id: str,
    output_dir: Optional[Path] = None,
    source_video: Optional[Path] = None,
    subtitle_path: Optional[Path] = None,
    script_path: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """执行高品质二创母带渲染与质检，返回结构化报告。"""
    out_dir = Path(output_dir or settings.default_output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        src_video, sub_path, sc_path = resolve_source_assets(
            youtube_id, out_dir, source_video, subtitle_path, script_path
        )

        logger.info("================================================================================")
        logger.info("🚀 启动重大新闻 3-5 分钟深度二创母带引擎 (Masterpiece Runner)")
        logger.info("目标视频 ID: %s", youtube_id)
        logger.info("基础竖版视频: %s", src_video)
        logger.info("事实核验字幕: %s", sub_path)
        logger.info("二创脚本文件: %s", sc_path)
        logger.info("================================================================================")

        # 1. 结构化契约强类型校验
        raw_script_text = sc_path.read_text(encoding="utf-8")
        script = InsightScriptV2.model_validate_json(raw_script_text)
        logger.info("✔ Pydantic V2 契约校验通过: headline='%s', cards=%d", script.headline, len(script.cards))

        # 2. VTT 事实引证机器可验证门禁
        logger.info("正在执行 VTT 事实引证机器可验证门禁 (Fail-Closed)...")
        if not verify_vtt_evidence(script, sub_path, tolerance_sec=5.0):
            logger.error("❌ 事实引证门禁拦截：台词引用未能匹配原文字幕时间轴！")
            raise RuntimeError("VTT Evidence Verification Failed: Fail-Closed Gate Blocked")
        logger.info("✔ 事实引证门禁核验 100% 通过 (词频吻合度均 ≥ 80%)")

        output_masterpiece = out_dir / f"masterpiece_{youtube_id}.mp4"

        # 3. 检查缓存
        if not force and valid_enrichment(src_video, sc_path, output_masterpiece):
            logger.info("✔ 命中已验证的完整二创母带缓存: %s", output_masterpiece)
            render_seconds = 0.0
        elif dry_run:
            logger.info("✔ [Dry-Run] 校验全部通过，跳过实际音画渲染")
            return {
                "youtube_id": youtube_id,
                "status": "VALIDATED_DRY_RUN",
                "source_video": str(src_video),
                "script": script.model_dump(),
                "evidence_passed": True,
            }
        else:
            logger.info("正在启动母带音画缝合与 44.1kHz 空间重音混流...")
            processor = InsightProcessor()
            t0 = time.time()
            ok = processor.process(src_video, sc_path, output_masterpiece)
            render_seconds = round(time.time() - t0, 2)
            if not ok or not output_masterpiece.is_file():
                raise RuntimeError(f"母带渲染失败，产物未生成或未通过基础校验")
            logger.info("✔ 母带音画组装完毕，耗时 %.2f 秒: %s", render_seconds, output_masterpiece)

        # 4. 母带完整音画参数与质检提取
        media_info = probe(output_masterpiece)
        video_stream = next(s for s in media_info["streams"] if s["codec_type"] == "video")
        audio_stream = next(s for s in media_info["streams"] if s["codec_type"] == "audio")
        format_info = media_info["format"]

        master_duration = float(format_info["duration"])
        validate_media(output_masterpiece, master_duration)

        receipt_file = output_masterpiece.with_suffix(".receipt.json")
        receipt_data = json.loads(receipt_file.read_text(encoding="utf-8")) if receipt_file.is_file() else {}

        # 5. 更新 DAL 数据库状态机 (如果数据库可用)
        try:
            db = PipelineDB()
            db.update_enrichment_status(youtube_id, "ENRICHED", slice_index=0)
            logger.info("✔ DAL 状态机已更新: youtube_id=%s -> ENRICHED", youtube_id)
        except Exception as exc:
            logger.warning("更新数据库状态机跳过: %s", exc)

        report = {
            "youtube_id": youtube_id,
            "status": "SUCCESS",
            "masterpiece_file": str(output_masterpiece),
            "file_size_bytes": output_masterpiece.stat().st_size,
            "render_seconds": render_seconds,
            "media_parameters": {
                "duration_seconds": master_duration,
                "width": int(video_stream["width"]),
                "height": int(video_stream["height"]),
                "fps": video_stream["r_frame_rate"],
                "video_codec": video_stream["codec_name"],
                "audio_codec": audio_stream["codec_name"],
                "audio_sample_rate": int(audio_stream["sample_rate"]),
                "audio_channels": int(audio_stream["channels"]),
                "total_bitrate_bps": int(format_info.get("bit_rate", 0)),
                "av_skew_tail_ms": round(abs(float(video_stream["duration"]) - float(audio_stream["duration"])) * 1000, 2),
                "av_skew_start_ms": round(abs(float(video_stream.get("start_time", 0)) - float(audio_stream.get("start_time", 0))) * 1000, 2),
            },
            "receipt_sha256": {
                "source_sha256": receipt_data.get("source_sha256"),
                "script_sha256": receipt_data.get("script_sha256"),
                "output_sha256": receipt_data.get("output_sha256"),
            },
            "receipt_manifest": receipt_data,
        }
        return report
    except Exception as exc:
        try:
            db = PipelineDB()
            db.update_enrichment_status(youtube_id, "FAILED", slice_index=0)
            logger.info("✔ DAL 状态机已记录失败: youtube_id=%s -> FAILED", youtube_id)
        except Exception:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description="重大新闻 3-5 分钟高品质二创母带独立调度入口 (RFC-2026-DEEP-CREATION-001)")
    parser.add_argument("target", help="YouTube 视频 ID 或完整链接 (如 SfNypZIb0H4 或 https://youtube.com/...)")
    parser.add_argument("--output-dir", type=Path, default=None, help="成片产物输出目录 (默认: output/)")
    parser.add_argument("--source-video", type=Path, default=None, help="指定基础竖版视频文件路径")
    parser.add_argument("--subtitle", type=Path, default=None, help="指定源字幕文件路径 (.vtt, .srt, .ass)")
    parser.add_argument("--script", type=Path, default=None, help="指定已生成的二创脚本文件 (.json)")
    parser.add_argument("--force", action="store_true", help="强制重新渲染，忽略既有缓存")
    parser.add_argument("--dry-run", action="store_true", help="只校验 Schema、引证门禁与收据，不触发 FFmpeg 渲染")
    parser.add_argument("--json", action="store_true", help="仅输出结构化 JSON 报告")
    args = parser.parse_args()

    try:
        yid = extract_youtube_id(args.target)
        report = run_masterpiece_pipeline(
            youtube_id=yid,
            output_dir=args.output_dir,
            source_video=args.source_video,
            subtitle_path=args.subtitle,
            script_path=args.script,
            force=args.force,
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            params = report.get("media_parameters", {})
            print("\n" + "=" * 70)
            print(f"🎉 重大新闻深度二创母带就绪！")
            print(f"• 视频标识: {report['youtube_id']}")
            print(f"• 母带文件: {report.get('masterpiece_file')}")
            print(f"• 物理总长: {params.get('duration_seconds')} 秒")
            print(f"• 分辨率/帧率: {params.get('width')}x{params.get('height')} @ {params.get('fps')}")
            print(f"• 音频规格: {params.get('audio_sample_rate')} Hz, {params.get('audio_channels')} 声道 ({params.get('audio_codec')})")
            print(f"• 首尾音画偏差: 起点 {params.get('av_skew_start_ms')}ms, 尾点 {params.get('av_skew_tail_ms')}ms")
            print(f"• 渲染耗时: {report.get('render_seconds')} 秒")
            print("=" * 70 + "\n")
        return 0
    except Exception as exc:
        logger.error("❌ 执行失败: %s", exc)
        if args.json:
            print(json.dumps({
                "youtube_id": yid if "yid" in locals() else args.target,
                "status": "FAILED",
                "error": str(exc),
            }, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
