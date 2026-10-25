# -*- coding: utf-8 -*-
"""经过批准的二创制作编排；规则校验不能替代人工语义与画面审核。

封面和平台能力由外层入口注入。制作成功仅证明本地产物已生成；
平台受理、审核和公开可见分别记录，缺少治理能力时阻断对应动作。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，实现敏感视频合规二创端到端流水线编排 |
| 1.2.0 | 2026-10-25 | GPT-6.1 Sol | 注入外层能力，纯验证演练及真实发布证据停止态 |
| 1.1.0   | 2026-10-25 | Antigravity | 修复 PROJECT_ROOT 与 SKILL_ROOT 计算层级，统一 sys.executable 子进程调用，B-Roll 增加音频时长对齐 |
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import time
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .censor_guard import ComplianceCensorGuard, ComplianceReport
    from .card_generator import FinancialCardGenerator, generate_vertical_frame_overlay
    from .subtitle_generator import TopEdgeSubtitleGenerator
    from .audio_mixer import AudioMixerEngine
    from .video_compositor import VideoCompositor
except ImportError:
    from video_processing.compliance_remix.censor_guard import ComplianceCensorGuard, ComplianceReport
    from video_processing.compliance_remix.card_generator import FinancialCardGenerator, generate_vertical_frame_overlay
    from video_processing.compliance_remix.subtitle_generator import TopEdgeSubtitleGenerator
    from video_processing.compliance_remix.audio_mixer import AudioMixerEngine
    from video_processing.compliance_remix.video_compositor import VideoCompositor

logger = logging.getLogger("compliance_remix_pipeline")


class ComplianceVideoRemixPipeline:
    """合规二创制作流水线总控。"""

    def __init__(self, work_dir: Path | str, preset_path=None, *,
                 cover_adapter=None, submission_adapter=None, execution_guard=None):
        requested_work_dir = Path(work_dir).absolute()
        if any(p.is_symlink() for p in [requested_work_dir, *requested_work_dir.parents]):
            raise ValueError("工作目录路径不允许符号链接")
        self.work_dir = requested_work_dir.resolve()
        self.preset = json.loads(Path(preset_path).read_text("utf-8")) if preset_path else {}
        self.execution_guard = execution_guard
        self.cover_adapter = cover_adapter
        self.submission_adapter = submission_adapter
        self.censor_guard = ComplianceCensorGuard()
        self.card_gen = self.sub_gen = self.audio_mixer = self.compositor = None

    def run_step_censor_check(self, manifest: Dict[str, Any]) -> ComplianceReport:
        """步骤 1: 语义脱敏安检。"""
        logger.info("[Step 1/7] Running semantic desensitization compliance check...")
        report = self.censor_guard.validate_script_manifest(manifest)
        if not report.passed:
            logger.error(f"[SECURITY BLOCKED] Found {len(report.violations)} policy violations:")
            for v in report.violations:
                logger.error(f"  - [{v.get('type')}/{v.get('level')}] matched='{v.get('matched')}' in {v.get('context')}")
            raise PermissionError(f"Compliance check failed: {report.summary}")
        logger.info(f"✅ Compliance check PASSED ({report.total_items_checked} text units validated)")
        return report

    def run_step_generate_cards_and_overlay(
        self,
        manifest: Dict[str, Any],
    ) -> Tuple[Path, List[Tuple[Path, float, float]]]:
        """步骤 2: 生成竖屏前景画框徽标遮罩及宏观数据卡片。"""
        logger.info("[Step 2/7] Generating frame overlay and financial data cards...")
        overlay_path = self.work_dir / "vertical_overlay.png"
        generate_vertical_frame_overlay(
            output_path=overlay_path,
            badge_text=manifest.get("badge_text", "◆ 六维时空 ｜ 独家观察"),
        )

        cards_dir = self.work_dir / "finance_cards"
        cards_manifest = manifest.get("cards", [])
        card_paths = self.card_gen.batch_generate_from_manifest(cards_manifest, cards_dir)

        # 匹配卡片展示时间区间
        cards_with_timings: List[Tuple[Path, float, float]] = []
        for c_data, c_path in zip(cards_manifest, card_paths):
            start_t = float(c_data.get("start_time", 0.0))
            end_t = float(c_data.get("end_time", start_t + 10.0))
            cards_with_timings.append((c_path, start_t, end_t))

        logger.info(f"✅ Generated overlay and {len(card_paths)} financial cards")
        return overlay_path, cards_with_timings

    async def run_step_synthesize_audio(
        self,
        manifest: Dict[str, Any],
        dry_run: bool = False,
    ) -> Tuple[Path, float, List[Tuple[float, float, str]]]:
        """步骤 3: 专属音色配音与 -17dB BGM 混音。"""
        logger.info("[Step 3/7] Synthesizing Dragon cloned voice and mixing BGM...")
        audio_cache_dir = self.work_dir / "audio_assets"
        chapters = manifest.get("chapters", [])

        if dry_run:
            raise ValueError("dry-run 只能通过 execute_full_pipeline 进行纯验证")

        audio_list = await self.audio_mixer.synthesize_chapters(chapters, audio_cache_dir)
        master_audio_p, dur_s, all_clauses_timing = self.audio_mixer.build_master_audio(
            audio_list, self.work_dir
        )
        logger.info(f"✅ Audio master ready: {master_audio_p} (duration: {dur_s:.2f}s)")
        return master_audio_p, dur_s, all_clauses_timing

    def run_step_generate_subtitles(
        self,
        clauses_timing: List[Tuple[float, float, str]],
        manifest: Dict[str, Any],
    ) -> Path:
        """步骤 4: 生成 9:16 上沿安全区 ASS 字幕。"""
        logger.info("[Step 4/7] Generating upper-edge ASS subtitles (Alignment: 8, MarginV: 570)...")
        ass_path = self.work_dir / "master_subtitles.ass"
        keywords = manifest.get("keywords", [])
        title = manifest.get("title", "Compliance Video Remix")

        self.sub_gen.generate_subtitles(
            clauses_with_timing=clauses_timing,
            output_path=ass_path,
            keywords=keywords,
            title=title,
        )
        logger.info(f"✅ Subtitles generated: {ass_path}")
        return ass_path

    def run_step_compose_and_render(
        self,
        source_video: Path | str,
        manifest: Dict[str, Any],
        master_audio: Path,
        overlay_image: Path,
        cards_with_timings: List[Tuple[Path, float, float]],
        ass_subtitles: Path,
        min_duration: Optional[float] = None,
        dry_run: bool = False,
    ) -> Path:
        """步骤 5: 截取纯净 B-Roll 并渲染 9:16 竖屏成片。"""
        logger.info("[Step 5/7] Splicing clean B-Roll and rendering 9:16 vertical video...")
        output_video_path = self.work_dir / f"{manifest.get('id', 'output')}_Vertical_1080p.mp4"

        if dry_run:
            raise ValueError("dry-run 不生成媒体")

        shots = manifest.get("raw_shots", [])
        if not shots:
            raise ValueError("Manifest 中缺少 raw_shots 纯净 B-Roll 镜头列表")

        broll_video = self.compositor.extract_and_concat_broll(
            source_video=source_video,
            shots=shots,
            output_concat_video=self.work_dir / "concatenated_broll.mp4",
            cache_dir=self.work_dir / "broll_cache",
            min_duration=min_duration,
        )

        final_video = self.compositor.render_final_vertical_video(
            broll_video=broll_video,
            master_audio=master_audio,
            overlay_image=overlay_image,
            cards_info=cards_with_timings,
            ass_subtitles=ass_subtitles,
            output_video=output_video_path,
        )
        logger.info(f"✅ Final vertical video successfully rendered: {final_video}")
        return final_video

    def run_step_generate_cover(
        self,
        manifest: Dict[str, Any],
        cover_output: Optional[Path | str] = None,
        dry_run: bool = False,
    ) -> Tuple[Path, Path]:
        """步骤 6: 调用项目统一 CoverEngine v2.0 (scripts/cover_generator.py) 生成标准封面。"""
        logger.info("[Step 6/7] Invoking standard CoverEngine v2.0 (scripts/cover_generator.py)...")
        cover_path = Path(cover_output) if cover_output else self.work_dir / f"{manifest.get('id', 'remix')}_cover.jpg"
        provenance_path = cover_path.with_name(f"{cover_path.stem}_provenance.json")

        payload = {
            "title": manifest.get("cover_title") or manifest.get("title", ""),
            "subtitle": manifest.get("cover_subtitle", ""),
            "label": manifest.get("cover_label", "独家观察"),
            "category": manifest.get("category", "时政财经"),
            "audio_edition": "mandarin_dubbed",
            "content_hints": manifest.get("content_hints", []),
        }

        if dry_run:
            raise ValueError("dry-run 不生成封面")
        if self.cover_adapter is None:
            raise RuntimeError("缺少受治理的外层封面适配能力")
        self.cover_adapter(payload, cover_path, provenance_path)
        from PIL import Image
        with Image.open(cover_path) as image:
            image.verify()
        provenance = json.loads(provenance_path.read_text("utf-8"))
        if not provenance:
            raise ValueError("封面来源回执为空")
        return cover_path, provenance_path

    def run_step_wechat_upload_preflight(self, video_path, cover_path, provenance_path,
                                        manifest, dry_run=False, upload_now=False):
        if dry_run or not upload_now:
            return {"status": "NOT_SUBMITTED"}
        if self.submission_adapter is None:
            raise RuntimeError("缺少包含调度准入/去重治理的发布适配能力")
        started_ns = time.time_ns()
        result = self.submission_adapter(video_path, cover_path, provenance_path,
                                         manifest, self.work_dir)
        if not isinstance(result, dict):
            return {"status": "UNCERTAIN", "reason": "INVALID_SUBMISSION_RECEIPT"}
        # 只读本次适配动作生成的真实回执；旧文件、返回值或 rc=0 不是证据。
        try:
            path = Path(result["receipt_path"])
            if not path.resolve().is_relative_to(self.work_dir) or path.is_symlink():
                raise ValueError("回执路径越界")
            if path.stat().st_mtime_ns < started_ns:
                raise ValueError("旧回执")
            receipt = json.loads(path.read_text("utf-8"))
            if not isinstance(receipt, dict) or receipt.get("video_id") != manifest["id"]:
                raise ValueError("回执对象不匹配")
            digest = VideoCompositor._digest(video_path)
            if receipt.get("video_sha256") != digest:
                raise ValueError("回执成片指纹不匹配")
        except Exception as exc:
            return {"status": "UNCERTAIN", "reason": "UNVERIFIED_SUBMISSION_RECEIPT",
                    "detail": str(exc)}
        state = receipt.get("status")
        if state not in {"NOT_SUBMITTED", "FAILED", "SUBMITTED", "SUBMITTED_UNBOUND",
                          "UNDER_REVIEW", "UNCERTAIN"}:
            return dict(receipt, status="UNCERTAIN", reason="UNVERIFIED_PUBLICATION_STATE")
        if result.get("returncode", 0) != 0:
            return dict(receipt, status="UNCERTAIN" if state != "NOT_SUBMITTED" else "FAILED",
                        reason="UPLOADER_NONZERO_EXIT")
        return receipt

    async def execute_full_pipeline(
        self,
        manifest: Dict[str, Any],
        source_video: Path | str,
        dry_run: bool = False,
        upload_now: bool = False,
    ) -> Dict[str, Any]:
        """端到端执行全套合规二创流水线。"""
        logger.info(f"=== Starting Compliance Video Remix Pipeline (ID: {manifest.get('id', 'remix')}) ===")

        from .manifest_contract import validate_manifest
        validate_manifest(manifest)
        censor_report = self.run_step_censor_check(manifest)
        if dry_run:
            return {"status": "VALIDATED", "video_id": manifest["id"],
                    "upload_status": "NOT_SUBMITTED", "compliance_checked": True}
        if self.execution_guard is None or self.execution_guard(manifest, self.work_dir) is not True:
            raise PermissionError("缺少有效的一次性生产领取凭据")
        if self.cover_adapter is None:
            raise RuntimeError("缺少受治理的外层封面适配能力")
        if upload_now and self.submission_adapter is None:
            raise RuntimeError("缺少受治理的发布适配能力")
        # 已存在的符号链接可能将固定输出路径转向工作目录之外。
        if self.work_dir.exists() and any(p.is_symlink() for p in self.work_dir.rglob("*")):
            raise ValueError("工作目录内不允许符号链接")
        if upload_now and callable(getattr(self.submission_adapter, "preflight", None)):
            self.submission_adapter.preflight()
        source = Path(source_video)
        if not source.is_file():
            raise ValueError("源视频不存在")
        # 编码能力与所有生产输入先验证，再初始化/调用 TTS。
        self.compositor = VideoCompositor()
        source_duration = self.compositor.probe_duration(source)
        if any(start >= source_duration for start, duration in manifest["raw_shots"]):
            raise ValueError("镜头起点超出源片时长")
        short_title = manifest["cover_title"]
        if not isinstance(short_title, str) or not 6 <= len(short_title.strip()) <= 16:
            raise ValueError("视频号短标题必须为6至16字")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.card_gen = FinancialCardGenerator()
        self.sub_gen = TopEdgeSubtitleGenerator()
        self.audio_mixer = AudioMixerEngine()

        # 2. 生成前景画框与数据卡片
        overlay_p, cards_timings = self.run_step_generate_cards_and_overlay(manifest)

        # 3. 语音合成与混音
        master_audio_p, dur_s, clauses_timing = await self.run_step_synthesize_audio(manifest, dry_run=dry_run)

        # 4. 生成上沿 ASS 字幕
        ass_p = self.run_step_generate_subtitles(clauses_timing, manifest)

        # 5. 切割 B-Roll 并渲染竖屏成片
        final_video_p = self.run_step_compose_and_render(
            source_video=source_video,
            manifest=manifest,
            master_audio=master_audio_p,
            overlay_image=overlay_p,
            cards_with_timings=cards_timings,
            ass_subtitles=ass_p,
            min_duration=dur_s,
            dry_run=dry_run,
        )

        # 6. 生成标准封面
        cover_p, prov_p = self.run_step_generate_cover(manifest, dry_run=dry_run)

        # 7. 视频号上传预检 / 执行
        # 所有实际产物在提交前再次核验；媒体存在不等于发布证据。
        validate_manifest(manifest)
        self.run_step_censor_check(manifest)
        self.compositor.probe_duration(final_video_p)
        self.compositor.probe_duration(master_audio_p)
        upload_ok = self.run_step_wechat_upload_preflight(
            video_path=final_video_p,
            cover_path=cover_p,
            provenance_path=prov_p,
            manifest=manifest,
            dry_run=dry_run,
            upload_now=upload_now,
        )

        receipt = {
            "status": "PRODUCED" if upload_ok["status"] == "NOT_SUBMITTED" else upload_ok["status"],
            "video_id": manifest.get("id"),
            "final_video": str(final_video_p),
            "cover_image": str(cover_p),
            "cover_provenance": str(prov_p),
            "subtitles_ass": str(ass_p),
            "master_audio": str(master_audio_p),
            "duration_seconds": dur_s,
            "compliance_checked": censor_report.passed,
            "upload_status": upload_ok["status"],
            "submission_receipt": upload_ok,
        }

        receipt_path = self.work_dir / "remix_receipt.json"
        temporary_receipt = receipt_path.with_suffix(".json.tmp")
        temporary_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_receipt.replace(receipt_path)
        logger.info(f"=== Compliance Video Remix Completed Successfully! Receipt: {receipt_path} ===")
        return receipt


# 生产入口由外层服务持有审批与能力注入；核心模块不提供绕过审批的 CLI。
