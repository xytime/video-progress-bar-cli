"""人工配音再制中心的单人 MiniMax 编排服务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 实现独立选片、时长闭环、实际字幕、中文成片和显式投递门禁 |
| 1.0.1 | 2026-07-29 | Codex | 对齐平台上传器审核中/封禁退出码，避免把已提交误记失败 |
| 1.0.2 | 2026-07-29 | Codex | 配音字幕改为完整句子分页，超长句仅在自然停顿处分屏并使用大字号单语样式 |
| 1.0.3 | 2026-07-29 | Codex | 再制渲染继承源片发布日期戳，并将日期上下文写入可追溯快照 |
| 1.0.4 | 2026-07-29 | Codex | 生成前用 DeepSeek thinking 精修普通话脚本，失败时阻断而非复用旧译文 |
| 1.0.5 | 2026-07-29 | Codex | 人工配音发布优先采用版本目录内已验收的定制封面，避免回退原片封面 |
| 1.0.6 | 2026-07-29 | Codex | 人工配音投递归档上传器日志、封面及提交页截图，微信封面失败不再继续发表 |
| 1.0.7 | 2026-07-30 | Codex | 缺少普通话配音版专属封面时阻断投递，禁止静默复用原声版封面           |
| 1.0.8 | 2026-07-31 | Codex | 平台闸门失败未提交时保持 READY_TO_PUBLISH，避免误记 UNDER_REVIEW       |
| 1.0.9 | 2026-07-31 | Codex | 普通话译制版投递标题和文案统一使用普通话译制命名                       |
| 1.1.0 | 2026-07-31 | Codex | 译制版封面须有非视频帧来源清单，禁止人工路径复用历史截图               |
| 1.1.1 | 2026-08-01 | Codex | TTS 时长失配时自动短写一次并重合成，减少人工卡在 NEEDS_REWRITE          |
| 1.1.2 | 2026-08-03 | Codex | 译制版封面来源清单追加无大面积遮罩版式硬门槛                           |
| 1.2.0 | 2026-08-03 | Codex | 按源频道选择专属火山声音复刻档案；未命中保持 MiniMax 默认回退            |
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pysubs2

from config.settings import settings
from ..core.cover_policy import validate_dedicated_cover_file
from ..censor_engine import check_text
from ..db.database import PipelineDB
from ..processors.date_stamp import format_upload_date
from ..processors.vertical_processor import VerticalCaptionProcessor
from ..utils.layout import VerticalLayout
from .minimax_client import MiniMaxTTSClient
from .script_refiner import DubbingScriptRefiner
from .subtitle_pages import build_semantic_pages, write_page_ass
from .timing import decide_timing, next_synthesis_speed
from .voice_profiles import DubbingVoiceProfile, profile_from_snapshot, resolve_dubbing_voice_profile
from .volc_speech_client import VolcSpeechTTSClient


logger = logging.getLogger(__name__)
_ASS_TAG = re.compile(r"\{[^}]*\}")
_ZH_MARKER = r"\N{\fnHiragino Sans GB"


class DubbingService:
    """人工入口调用的独立服务，不被 PipelineManager 导入。"""

    def __init__(self, db: Optional[PipelineDB] = None, *, project_root: Optional[Path] = None) -> None:
        self.db = db or PipelineDB()
        self.project_root = project_root or settings.project_root

    def create(
        self, youtube_id: str, *, slice_index: int = 0, platforms: Sequence[str] = (),
        force_new_version: bool = False,
    ) -> Dict[str, Any]:
        """人工选片后同步生产成片，完成后停在 QA_REQUIRED，绝不自动投递。"""
        profile = self._voice_profile_for_source(youtube_id, slice_index)
        config = self._config_snapshot(profile)
        job = self.db.create_dubbing_job(
            youtube_id, slice_index=slice_index, provider=profile.provider, model=profile.model,
            voice_id=profile.voice_id, requested_platforms=platforms,
            config=config, force_new_version=force_new_version,
        )
        job = self.db.get_dubbing_job(job["id"])
        if not job:
            raise RuntimeError("配音任务创建后无法重新读取。")
        if job["state"] in {"QA_REQUIRED", "READY_TO_PUBLISH", "PUBLISHING", "UNDER_REVIEW", "PUBLISHED"}:
            return self._job_view(job["id"])
        workspace = self._workspace(job)
        try:
            self.db.update_dubbing_job(job["id"], "ANALYZING", workspace_path=str(workspace), error_message=None)
            source_video, source_ass = self._source_assets(job)
            self._record_source_snapshot(job, source_video, source_ass, workspace)
            chunks = self._load_semantic_chunks(source_ass)
            if not chunks:
                raise RuntimeError("未从源字幕提取到可配音的中文语义片段。")
            chunks = self._refine_script(job, chunks, workspace)
            self._safety_gate(job, chunks)
            job_profile = self._profile_from_job(job)
            self.db.upsert_dubbing_speaker(job["id"], "NARRATOR", voice_id=job_profile.voice_id)
            self.db.update_dubbing_job(job["id"], "SCRIPT_READY")
            plans = self._synthesize_and_fit(job, chunks, workspace, profile=job_profile)
            self.db.update_dubbing_job(job["id"], "ALIGNING")
            narration = self._build_narration(plans, source_video, workspace)
            subtitle = self._write_actual_subtitles(plans, workspace / "subtitles" / "zh_actual.srt")
            self.db.replace_dubbing_utterances(job["id"], plans)
            self.db.upsert_dubbing_artifact(job["id"], "narration", str(narration), sha256=self._sha256(narration))
            self.db.upsert_dubbing_artifact(job["id"], "subtitle", str(subtitle), sha256=self._sha256(subtitle))
            self.db.update_dubbing_job(job["id"], "RENDERING", narration_path=str(narration), subtitle_path=str(subtitle))
            output = self._render_video(job, source_video, plans, narration, workspace)
            report = self._write_qa_report(job, source_video, output, plans, workspace)
            asset_sha = self._sha256(output)
            self.db.upsert_dubbing_artifact(job["id"], "video", str(output), sha256=asset_sha)
            self.db.upsert_dubbing_artifact(job["id"], "qa_report", str(report), sha256=self._sha256(report))
            self.db.update_dubbing_job(
                job["id"], "QA_REQUIRED", narration_path=str(narration), subtitle_path=str(subtitle),
                output_video_path=str(output), qa_report_path=str(report), asset_sha256=asset_sha, error_message=None,
            )
        except Exception as exc:
            current = self.db.get_dubbing_job(job["id"])
            if not current or current["state"] != "NEEDS_REWRITE":
                self.db.update_dubbing_job(job["id"], "FAILED", error_message=str(exc))
            raise
        return self._job_view(job["id"])

    def approve(self, youtube_id: str, *, slice_index: int = 0) -> Dict[str, Any]:
        """人工试听/字幕核验后放行投递准备，不会触发任何外部动作。"""
        job = self._require_latest_job(youtube_id, slice_index)
        if job["state"] != "QA_REQUIRED":
            raise ValueError(f"任务当前状态为 {job['state']}，不能批准发布。")
        output = Path(str(job.get("output_video_path") or ""))
        if not output.is_file() or not job.get("asset_sha256"):
            raise RuntimeError("质检产物不完整，拒绝放行。")
        self.db.update_dubbing_job(job["id"], "READY_TO_PUBLISH")
        return self._job_view(job["id"])

    def publish(
        self, youtube_id: str, *, platforms: Sequence[str], slice_index: int = 0, confirm: bool = False,
    ) -> Dict[str, Any]:
        """唯一会调用平台上传器的入口；必须显式 --confirm。"""
        if not confirm:
            raise ValueError("发布需要显式 --confirm，未执行任何平台动作。")
        job = self._require_latest_job(youtube_id, slice_index)
        if job["state"] not in {"READY_TO_PUBLISH", "UNDER_REVIEW"}:
            raise ValueError(f"任务当前状态为 {job['state']}，请先完成人工质检批准。")
        selected = self._normalize_platforms(platforms, job)
        self.db.update_dubbing_job(job["id"], "PUBLISHING")
        for platform in selected:
            self._publish_one(job, platform)
        publications = self.db.get_dubbing_publications(job["id"])
        submitted_states = {"UNDER_REVIEW", "PUBLISHED"}
        if publications and all(item["state"] == "PUBLISHED" for item in publications):
            final_state = "PUBLISHED"
            final_error = None
        elif any(item["state"] in submitted_states for item in publications):
            final_state = "UNDER_REVIEW"
            final_error = None
        else:
            final_state = "READY_TO_PUBLISH"
            final_error = "平台投递未提交成功；请修正平台闸门失败后再重试。"
        self.db.update_dubbing_job(job["id"], final_state, error_message=final_error)
        return self._job_view(job["id"])

    def run_selected(
        self, youtube_id: str, *, platforms: Sequence[str], slice_index: int = 0,
        confirm: bool = False, force_new_version: bool = False,
    ) -> Dict[str, Any]:
        """人工选片即是一次端到端授权；仍要求 --confirm 才允许外部平台提交。"""
        requested_platforms = [] if not platforms or "all" in platforms else platforms
        job = self.create(
            youtube_id, slice_index=slice_index, platforms=requested_platforms,
            force_new_version=force_new_version,
        )
        if job["state"] == "QA_REQUIRED":
            job = self.approve(youtube_id, slice_index=slice_index)
        if job["state"] not in {"READY_TO_PUBLISH", "UNDER_REVIEW"}:
            raise RuntimeError(f"机器质检未能放行，当前状态为 {job['state']}。")
        return self.publish(youtube_id, slice_index=slice_index, platforms=platforms, confirm=confirm)

    def status(self, youtube_id: str, *, slice_index: int = 0) -> Dict[str, Any]:
        return self._job_view(self._require_latest_job(youtube_id, slice_index)["id"])

    def _synthesize_and_fit(
        self, job: Dict[str, Any], chunks: List[Dict[str, Any]], workspace: Path,
        *, profile: Optional[DubbingVoiceProfile] = None,
    ) -> List[Dict[str, Any]]:
        self.db.update_dubbing_job(job["id"], "SYNTHESIZING")
        active_profile = profile or self._profile_from_job(job)
        client = self._tts_client(active_profile)
        audio_cache = workspace / "cache"
        plans: List[Dict[str, Any]] = []
        for chunk in chunks:
            timing_rewrites = 0
            while True:
                speed = max(active_profile.min_speed, min(active_profile.max_speed, active_profile.preferred_speed))
                attempts: List[Dict[str, Any]] = []
                for attempt in range(1, 3):
                    synthesis = client.synthesize(chunk["zh_text"], speed=speed, cache_dir=audio_cache)
                    actual_ms = self._duration_ms(synthesis.audio_path)
                    attempts.append({"speed": speed, "actual_ms": actual_ms, "synthesis": synthesis})
                    tolerance = max(220, round(chunk["target_ms"] * 0.04))
                    if abs(actual_ms - chunk["target_ms"]) <= tolerance:
                        break
                    next_speed = next_synthesis_speed(
                        speed, actual_ms, chunk["target_ms"], minimum=active_profile.min_speed,
                        maximum=active_profile.max_speed,
                    )
                    if abs(next_speed - speed) < 0.025:
                        break
                    speed = next_speed
                selected = attempts[-1]
                decision = decide_timing(selected["actual_ms"], chunk["target_ms"])
                if not decision.requires_rewrite:
                    break
                ordinal = len(plans) + 1
                if timing_rewrites >= 1:
                    self.db.update_dubbing_job(job["id"], "NEEDS_REWRITE", error_message=f"第 {ordinal} 段无法自然对齐，需改写中文稿。")
                    raise RuntimeError("存在超过 12% 的时长失配，已阻断成片并转 NEEDS_REWRITE。")
                chunk = self._rewrite_chunk_for_timing(
                    job, chunk, actual_ms=selected["actual_ms"], workspace=workspace, ordinal=ordinal,
                )
                timing_rewrites += 1
            fitted = self._fit_audio(
                selected["synthesis"].audio_path, decision.post_tempo, decision.pad_ms,
                workspace / "fitted" / f"{len(plans):04d}.wav",
            )
            actual_duration = round(selected["actual_ms"] / decision.post_tempo) if decision.post_tempo else selected["actual_ms"]
            subtitle_entries = self._actual_subtitles(
                selected["synthesis"].subtitles, chunk["source_start_ms"], decision.post_tempo,
                chunk["zh_text"], actual_duration,
            )
            subtitle_entries = build_semantic_pages(
                subtitle_entries, max_chars=settings.dubbing_subtitle_max_page_chars,
            )
            plans.append({
                **chunk, "audio_path": str(fitted), "actual_start_ms": chunk["source_start_ms"],
                "actual_end_ms": chunk["source_start_ms"] + actual_duration, "actual_duration_ms": actual_duration,
                "speed": selected["speed"], "alignment_strategy": decision.strategy,
                "synthesis_attempts": len(attempts), "cache_key": selected["synthesis"].cache_key,
                "usage_characters": selected["synthesis"].usage_characters,
                "subtitle_entries": subtitle_entries,
            })
        return plans

    def _rewrite_chunk_for_timing(
        self,
        job: Dict[str, Any],
        chunk: Dict[str, Any],
        *,
        actual_ms: int,
        workspace: Path,
        ordinal: int,
    ) -> Dict[str, Any]:
        """时长过长时做一次可追溯短写，仍过不了则交回人工处理。"""
        if not settings.dubbing_deepseek_script_refinement:
            self.db.update_dubbing_job(job["id"], "NEEDS_REWRITE", error_message=f"第 {ordinal} 段无法自然对齐，需改写中文稿。")
            raise RuntimeError("脚本精修未启用，无法自动短写失配片段。")
        try:
            rewritten = DubbingScriptRefiner().shorten_for_timing(
                chunk,
                video_title=self._display_title(job),
                actual_ms=actual_ms,
                target_ms=int(chunk["target_ms"]),
            )
        except Exception as exc:
            self.db.update_dubbing_job(job["id"], "NEEDS_REWRITE", error_message=f"第 {ordinal} 段自动短写失败：{exc}")
            raise
        if rewritten == str(chunk.get("zh_text") or "").strip():
            self.db.update_dubbing_job(job["id"], "NEEDS_REWRITE", error_message=f"第 {ordinal} 段短写后仍未变短，需人工改写。")
            raise RuntimeError("DeepSeek 短写未改变失配片段。")
        record = {
            "ordinal": ordinal,
            "target_ms": int(chunk["target_ms"]),
            "previous_actual_ms": actual_ms,
            "source_text": chunk.get("source_text") or "",
            "before": chunk.get("zh_text") or "",
            "after": rewritten,
        }
        path = workspace / "timing_rewrites.json"
        records: List[Dict[str, Any]] = []
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                records = loaded if isinstance(loaded, list) else []
            except (OSError, ValueError):
                records = []
        records.append(record)
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.db.upsert_dubbing_artifact(job["id"], "timing_rewrites", str(path), sha256=self._sha256(path))
        item = dict(chunk)
        item["zh_text"] = rewritten
        return item

    def _load_semantic_chunks(self, source_ass: Path) -> List[Dict[str, Any]]:
        subtitles = pysubs2.load(str(source_ass))
        captions: List[Dict[str, Any]] = []
        for event in subtitles:
            if event.style != "Default" or event.is_comment:
                continue
            source, chinese = self._split_bilingual(event.text)
            if chinese:
                captions.append({"source_start_ms": event.start, "source_end_ms": event.end, "source_text": source, "zh_text": chinese})
        chunks: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        for caption in captions:
            current.append(caption)
            duration = caption["source_end_ms"] - current[0]["source_start_ms"]
            ends_sentence = bool(re.search(r"[.!?][\"']?$", caption["source_text"]))
            if (ends_sentence and duration >= 3000) or duration >= 14000:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)
        output: List[Dict[str, Any]] = []
        for group in chunks:
            zh_text = "".join(item["zh_text"] for item in group).strip()
            if zh_text and not re.search(r"[。！？]$", zh_text):
                zh_text += "。"
            output.append({
                "source_start_ms": group[0]["source_start_ms"], "source_end_ms": group[-1]["source_end_ms"],
                "target_ms": group[-1]["source_end_ms"] - group[0]["source_start_ms"],
                "source_text": " ".join(item["source_text"] for item in group).strip(), "zh_text": zh_text,
            })
        return output

    def _render_video(self, job: Dict[str, Any], source_video: Path, plans: List[Dict[str, Any]], narration: Path, workspace: Path) -> Path:
        # VerticalCaptionProcessor 保持原有竖版布局；输入软链接保证新 ASS 不会覆盖原视频字幕文件。
        linked_source = workspace / "render_source.mp4"
        if not linked_source.exists():
            linked_source.symlink_to(source_video)
        subtitle_pages = []
        for plan in plans:
            for entry in plan["subtitle_entries"]:
                subtitle_pages.append(entry)
        render_with_source_audio = workspace / "rendered_with_source_audio.mp4"
        processor = VerticalCaptionProcessor(
            linked_source, output_path=render_with_source_audio, src_lang="en", target_lang="zh-CN",
            title=self._display_title(job), bilingual=False, tts_provider=None,
            source_date=self._source_date_stamp(job),
        )
        video_w, video_h = processor._get_video_resolution()
        ass = write_page_ass(
            subtitle_pages, workspace / "render_source.ass",
            font_size=settings.dubbing_subtitle_font_size,
            subtitle_y=VerticalLayout.calculate(video_w, video_h).subtitle_margin_v,
            max_line_chars=settings.dubbing_subtitle_max_line_chars,
        )
        self.db.upsert_dubbing_artifact(job["id"], "ass", str(ass), sha256=self._sha256(ass))
        rendered = processor._burn_subtitles(ass)
        output = workspace / "dubbing_zh.mp4"
        if settings.dubbing_audio_policy == "zh_only":
            audio_filter = "[1:a]anull[aout]"
        else:
            # 已通过实片验收：普通话标准响度，英文仅作极低底音，不触发不可预测的 sidechain ducking。
            audio_filter = (
                f"[1:a]anull[zh];[0:a]volume={settings.dubbing_english_bed_volume:.3f}[enbed];"
                "[zh][enbed]amix=inputs=2:weights='1 1':normalize=0,alimiter=limit=0.95,aresample=44100[aout]"
            )
        self._run([
            "ffmpeg", "-y", "-i", str(rendered), "-i", str(narration), "-filter_complex", audio_filter,
            "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-shortest", str(output),
        ])
        return output

    def _build_narration(self, plans: List[Dict[str, Any]], source_video: Path, workspace: Path) -> Path:
        duration_ms = self._duration_ms(source_video)
        output = workspace / "narration.wav"
        command = ["ffmpeg", "-y"]
        for plan in plans:
            command.extend(["-i", plan["audio_path"]])
        filters, labels = [], []
        for index, plan in enumerate(plans):
            delay = int(plan["source_start_ms"])
            filters.append(f"[{index}:a]adelay={delay}|{delay}[a{index}]")
            labels.append(f"[a{index}]")
        filters.append(
            "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
            f"apad=whole_dur={duration_ms / 1000:.3f},atrim=duration={duration_ms / 1000:.3f},"
            f"loudnorm=I={settings.dubbing_target_lufs}:TP=-1.5:LRA=11[out]"
        )
        command.extend(["-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "44100", "-ac", "1", str(output)])
        self._run(command)
        return output

    def _fit_audio(self, source: Path, tempo: float, pad_ms: int, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        filters: List[str] = []
        if abs(tempo - 1.0) > 0.0001:
            filters.append(f"atempo={tempo:.5f}")
        if pad_ms:
            filters.append(f"apad=pad_dur={pad_ms / 1000:.3f}")
        self._run(["ffmpeg", "-y", "-i", str(source), *( ["-af", ",".join(filters)] if filters else [] ), str(output)])
        return output

    def _write_actual_subtitles(self, plans: Iterable[Dict[str, Any]], output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        ordinal = 1
        for plan in plans:
            for entry in plan["subtitle_entries"]:
                rows.append(f"{ordinal}\n{self._srt_time(entry['start_ms'])} --> {self._srt_time(entry['end_ms'])}\n{entry['text']}\n")
                ordinal += 1
        output.write_text("\n".join(rows), encoding="utf-8")
        return output

    @staticmethod
    def _actual_subtitles(raw: List[Dict[str, Any]], offset_ms: int, tempo: float, fallback_text: str, actual_duration_ms: int) -> List[Dict[str, Any]]:
        entries = []
        for item in raw:
            text = str(item.get("pronounce_text") or item.get("text") or "").strip()
            start = item.get("time_begin")
            end = item.get("time_end")
            if text and isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
                entries.append({"start_ms": offset_ms + round(start / tempo), "end_ms": offset_ms + round(end / tempo), "text": text})
        return entries or [{"start_ms": offset_ms, "end_ms": offset_ms + actual_duration_ms, "text": fallback_text}]

    @staticmethod
    def _split_bilingual(text: str) -> tuple[str, str]:
        if _ZH_MARKER in text:
            english, chinese = text.split(_ZH_MARKER, 1)
            return DubbingService._clean_ass(english), DubbingService._clean_ass(chinese.split("}", 1)[-1], line_break="")
        plain = DubbingService._clean_ass(text)
        chinese_lines = [line for line in plain.split("\\N") if re.search(r"[一-龥]", line)]
        return plain, "".join(chinese_lines)

    @staticmethod
    def _clean_ass(text: str, line_break: str = " ") -> str:
        return re.sub(r"\s+", " ", _ASS_TAG.sub("", text).replace(r"\N", line_break).replace(r"\h", " ")).strip()

    def _safety_gate(self, job: Dict[str, Any], chunks: Sequence[Dict[str, Any]]) -> None:
        text = "\n".join(chunk["zh_text"] for chunk in chunks)
        result = check_text(zh_text=text, en_text="")
        if result.hit:
            raise RuntimeError(f"配音稿安全检查阻断: {result.tag}")

    def _source_assets(self, job: Dict[str, Any]) -> tuple[Path, Path]:
        stem = job["youtube_id"] if int(job["slice_index"]) == 0 else f"{job['youtube_id']}_{job['slice_index']}"
        video = self.project_root / "output" / "original_video" / f"{stem}.mp4"
        ass = self.project_root / "output" / "original_video" / f"{stem}.ass"
        if not video.is_file() or not ass.is_file():
            raise RuntimeError(f"源视频或字幕不存在: {video} / {ass}")
        return video, ass

    def _workspace(self, job: Dict[str, Any]) -> Path:
        root = self.project_root / "output" / "dubbing" / job["youtube_id"] / f"v{job['version']}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _write_qa_report(self, job: Dict[str, Any], source: Path, output: Path, plans: List[Dict[str, Any]], workspace: Path) -> Path:
        report = {
            "job_id": job["id"], "source": str(source), "output": str(output), "output_duration_ms": self._duration_ms(output),
            "source_duration_ms": self._duration_ms(source), "provider": job.get("provider"), "model": job.get("model"),
            "voice_id": job.get("voice_id"), "config": self._config_snapshot(self._profile_from_job(job)),
            "audio_policy": settings.dubbing_audio_policy,
            "usage_characters": sum(int(plan.get("usage_characters") or 0) for plan in plans),
            "alignment": [{key: plan[key] for key in ("source_start_ms", "source_end_ms", "actual_duration_ms", "speed", "alignment_strategy", "synthesis_attempts")} for plan in plans],
        }
        path = workspace / "qa_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _record_source_snapshot(self, job: Dict[str, Any], source_video: Path, source_ass: Path, workspace: Path) -> None:
        snapshot = {
            "source_video_path": str(source_video), "source_ass_path": str(source_ass),
            "source_ass_sha256": self._sha256(source_ass), "source_title": job["source_title"],
            "source_zh_title": job.get("source_zh_title"),
            "source_youtube_id": job["youtube_id"], "source_slice_index": job["slice_index"],
            "source_upload_date": job.get("source_upload_date"),
            "source_date_stamp": self._source_date_stamp(job),
        }
        path = workspace / "source_snapshot.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.db.upsert_dubbing_artifact(job["id"], "source_snapshot", str(path), sha256=self._sha256(path), metadata=snapshot)

    def _publish_one(self, job: Dict[str, Any], platform: str) -> None:
        output = Path(str(job.get("output_video_path") or ""))
        if not output.is_file():
            raise RuntimeError("成片不存在，拒绝投递。")
        workspace = self._workspace(job)
        title, copy, cover, category, horizontal_cover = self._variant_publish_assets(job, workspace)
        evidence_dir = workspace / "publish" / "evidence" / platform
        commands = {
            "wechat": ["scripts/wechat_uploader.py", "--video", str(output), "--copy", str(copy), "--title-file", str(title), "--cover", str(cover), "--cover-provenance", str(self._cover_provenance_path(cover)), "--category-file", str(category), "--fail-fast-login", "--evidence-dir", str(evidence_dir)],
            "douyin": ["scripts/douyin_uploader.py", "--video", str(output), "--copy", str(copy), "--title-file", str(title), "--cover", str(cover), "--publish", "--fail-fast-login"],
            "kuaishou": ["scripts/kuaishou_uploader.py", "--video", str(output), "--copy", str(copy), "--cover", str(cover), "--publish", "--fail-fast-login"],
        }
        result = subprocess.run(
            [str(self.project_root / ".venv" / "bin" / "python"), *commands[platform]],
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )
        try:
            self._record_publish_evidence(job["id"], platform, workspace, result, evidence_dir)
        except Exception as exc:
            # 投递已是外部动作；证据归档异常不能掩盖其真实退出码或阻止账本落状态。
            logger.warning("归档 %s 投递证据失败: %s", platform, exc)
        if result.returncode in {0, 6}:
            # 上传器本地成功只表示已提交/已接受，仍需创作者后台可见证据，故保守记为待核验。
            self.db.update_dubbing_publication(job["id"], platform, "UNDER_REVIEW", error_message="已提交，等待平台作品管理页确认可见。")
            return
        if result.returncode == 7:
            state = "BANNED"
        elif result.returncode == 3:
            state = "UNCERTAIN"
        else:
            state = "RETRYABLE_FAILED"
        detail = (result.stderr or result.stdout or f"uploader exit {result.returncode}").strip()[-1000:]
        self.db.update_dubbing_publication(job["id"], platform, state, error_message=detail)

    def _record_publish_evidence(self, job_id: int, platform: str, workspace: Path, result, evidence_dir: Path) -> None:
        """归档本次人工投递的上传器输出和页面截图，供审核使用。"""
        publish_dir = workspace / "publish"
        publish_dir.mkdir(parents=True, exist_ok=True)
        log_path = publish_dir / f"{platform}_uploader.log"
        log_text = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
        log_path.write_text(log_text, encoding="utf-8")
        self.db.upsert_dubbing_artifact(job_id, f"{platform}_uploader_log", str(log_path), sha256=self._sha256(log_path))
        if evidence_dir.is_dir():
            for screenshot in sorted(evidence_dir.glob("*.png")):
                self.db.upsert_dubbing_artifact(
                    job_id,
                    f"{platform}_evidence_{screenshot.stem}",
                    str(screenshot),
                    sha256=self._sha256(screenshot),
                )

    def _variant_publish_assets(self, job: Dict[str, Any], workspace: Path) -> tuple[Path, Path, Path, Path, Optional[Path]]:
        yid = job["youtube_id"]
        title_src = self.project_root / "output" / f"{yid}_title.txt"
        copy_src = self.project_root / "output" / f"{yid}_copy.txt"
        cover = workspace / "publish" / "cover_wechat.jpg"
        if not self._is_dedicated_cover(cover):
            raise RuntimeError("普通话配音版缺少已验收的非视频帧版本专属封面来源清单，禁止投递。")
        category = self.project_root / "output" / f"{yid}_category.txt"
        if not copy_src.is_file() or not cover.is_file() or not category.is_file():
            raise RuntimeError("原发布文案或封面不完整，拒绝投递。")
        publish_dir = workspace / "publish"
        publish_dir.mkdir(exist_ok=True)
        title = publish_dir / "title.txt"
        copy = publish_dir / "copy.txt"
        original_title = title_src.read_text(encoding="utf-8").strip() if title_src.is_file() else job["source_title"]
        concise_title = original_title.replace("之谜", "").strip()
        title.write_text((concise_title[:10] + "普通话译制")[:16] + "\n", encoding="utf-8")
        copy.write_text(copy_src.read_text(encoding="utf-8").strip() + "\n\n普通话译制版\n", encoding="utf-8")
        horizontal = self.project_root / "output" / f"{yid}_cover_douyin_horizontal.png"
        return title, copy, cover, category, horizontal if horizontal.is_file() else None

    @staticmethod
    def _cover_provenance_path(cover_file: Path) -> Path:
        return cover_file.with_name(f"{cover_file.stem}_provenance.json")

    def _is_dedicated_cover(self, cover_file: Path) -> bool:
        """人工译制版也必须显式证明封面不是视频内截图且版式未遮挡底图。"""
        provenance_file = self._cover_provenance_path(cover_file)
        return validate_dedicated_cover_file(cover_file, provenance_file)

    def _display_title(self, job: Dict[str, Any]) -> str:
        """优先使用已审核的短标题，确保新版两行头部不以省略号损失关键信息。"""
        title_file = self.project_root / "output" / f"{job['youtube_id']}_title.txt"
        if title_file.is_file():
            title = title_file.read_text(encoding="utf-8").strip()
            if title:
                return title
        return str(job.get("source_zh_title") or job["source_title"])

    def _refine_script(self, job: Dict[str, Any], chunks: List[Dict[str, Any]], workspace: Path) -> List[Dict[str, Any]]:
        """把历史机器译稿收敛为可直接朗读的普通话稿，并保存版本化审计产物。"""
        if not settings.dubbing_deepseek_script_refinement:
            return chunks
        refined = DubbingScriptRefiner().refine(chunks, video_title=self._display_title(job))
        path = workspace / "refined_script.json"
        path.write_text(json.dumps(refined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.db.upsert_dubbing_artifact(job["id"], "refined_script", str(path), sha256=self._sha256(path))
        return refined

    def _source_date_stamp(self, job: Dict[str, Any]) -> Optional[str]:
        """遵循主流程的日期规则：切片缺日期时回退同源母片。"""
        if not settings.enable_source_date_stamp:
            return None
        raw_upload_date = job.get("source_upload_date")
        if not raw_upload_date and int(job.get("slice_index") or 0):
            parent = self.db.get_video_by_youtube_id(str(job["youtube_id"]), 0)
            raw_upload_date = parent.get("upload_date") if parent else None
        return format_upload_date(raw_upload_date)

    def _normalize_platforms(self, requested: Sequence[str], job: Dict[str, Any]) -> List[str]:
        selected = [item.lower() for item in requested]
        configured = json.loads(job.get("requested_platforms") or "[]")
        if not selected or "all" in selected:
            selected = configured or ["wechat", "douyin", "kuaishou"]
        if any(item not in {"wechat", "douyin", "kuaishou"} for item in selected):
            raise ValueError("存在不支持的平台。")
        return list(dict.fromkeys(selected))

    def _require_latest_job(self, youtube_id: str, slice_index: int) -> Dict[str, Any]:
        job = self.db.get_dubbing_job_by_source(youtube_id, slice_index=slice_index)
        if not job:
            raise ValueError("未找到该源视频的配音任务。")
        return job

    def _job_view(self, job_id: int) -> Dict[str, Any]:
        job = self.db.get_dubbing_job(job_id)
        if not job:
            raise ValueError("配音任务不存在。")
        job["artifacts"] = self.db.get_dubbing_artifacts(job_id)
        job["publications"] = self.db.get_dubbing_publications(job_id)
        return job

    def _voice_profile_for_source(self, youtube_id: str, slice_index: int) -> DubbingVoiceProfile:
        source = self.db.get_video_by_youtube_id(youtube_id, slice_index)
        return resolve_dubbing_voice_profile(source.get("channel_id") if source else None, project_root=self.project_root)

    @staticmethod
    def _profile_from_job(job: Dict[str, Any]) -> DubbingVoiceProfile:
        try:
            snapshot = json.loads(job.get("config_json") or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("配音任务的音色配置快照损坏。") from exc
        return profile_from_snapshot(snapshot if isinstance(snapshot, dict) else {})

    @staticmethod
    def _tts_client(profile: DubbingVoiceProfile) -> Any:
        if profile.provider == "minimax":
            return MiniMaxTTSClient(
                api_key=settings.minimax_api_key or "", model=profile.model,
                voice_id=profile.voice_id, request_interval_sec=settings.minimax_tts_request_interval_sec,
            )
        if profile.provider == "volc_speech":
            return VolcSpeechTTSClient(
                api_key=settings.volc_speech_api_key or "", resource_id=profile.model,
                voice_id=profile.voice_id, sample_rate=profile.sample_rate,
                request_interval_sec=settings.volc_speech_request_interval_sec,
            )
        raise RuntimeError(f"不支持的配音 TTS provider: {profile.provider}")

    @staticmethod
    def _config_snapshot(profile: DubbingVoiceProfile) -> Dict[str, Any]:
        return profile.snapshot(audio_policy=settings.dubbing_audio_policy)

    @staticmethod
    def _duration_ms(path: Path) -> int:
        completed = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
        return round(float(completed.stdout.strip()) * 1000)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _srt_time(milliseconds: int) -> str:
        hours, residue = divmod(max(0, milliseconds), 3_600_000)
        minutes, residue = divmod(residue, 60_000)
        seconds, millis = divmod(residue, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    @staticmethod
    def _run(command: List[str]) -> None:
        subprocess.run(command, check=True, capture_output=True)
