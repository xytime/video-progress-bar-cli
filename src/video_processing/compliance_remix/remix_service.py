# -*- coding: utf-8 -*-
"""合规二创提案、不可变审批与一次性生产服务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-25 | GPT-6.1 Sol | 独立身份、带证据提案、事务审批与生产隔离 |
| 1.0.0 | 2026-10-25 | Antigravity | 两阶段服务初版 |
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.db.compliance_remix import manifest_digest
from .commentary_generator import CommentaryGenerator
from .censor_guard import ComplianceCensorGuard
from .manifest_contract import validate_manifest, validate_identifier
from .remix_pipeline import ComplianceVideoRemixPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _extract_video_id(url: str) -> str:
    """只接受精确 YouTube 域名和完整 11 位 ID。"""
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url):
        return url
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}):
        raise ValueError("仅支持 HTTPS YouTube 视频链接或 11 位视频 ID")
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.lstrip("/")
    elif parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v", [])
        video_id = values[0] if len(values) == 1 else ""
    else:
        match = re.fullmatch(r"/(?:embed|shorts)/([a-zA-Z0-9_-]{11})", parsed.path)
        video_id = match.group(1) if match else ""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
        raise ValueError("无效的 YouTube 视频 ID")
    return video_id


def _run_bounded(cmd: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess:
    """子进程独立进程组；超时杀全树并回收。"""
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    if process.returncode:
        raise RuntimeError(f"来源提取失败 (exit {process.returncode}): {stderr[-400:]}")
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


async def run_bounded_async(cmd: list[str], *, cwd=None, timeout: int = 300) -> tuple[int, str, str]:
    """异步子进程取消/超时均清理全进程组，供可信外层入口使用。"""
    process = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                  stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        # 先允许可信 CLI 的 SIGTERM handler 清理其独立媒体子进程组。
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.communicate(), 5)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.communicate()
        # 即便父进程已退出，仍杀掉同组遗留孙进程。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _time_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def parse_timestamped_vtt(raw: str, *, duration: float | None = None) -> list[tuple[float, float, str]]:
    """只解析真实 cue，NOTE/STYLE/REGION 和空正文不构成来源证据。"""
    if not isinstance(raw, str) or not raw.startswith("WEBVTT") or len(raw) > 12000:
        raise ValueError("来源字幕头部无效或超出完整证据预算（不截断）")
    cues = []
    timing = re.compile(r"((?:\d{2}:)?[0-5]\d:[0-5]\d\.\d{3})\s+-->\s+((?:\d{2}:)?[0-5]\d:[0-5]\d\.\d{3})(?:\s+.*)?")
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n")):
        lines = block.strip().splitlines()
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        index = 0 if timing.fullmatch(lines[0]) else 1
        if index >= len(lines) or not (match := timing.fullmatch(lines[index])):
            raise ValueError("来源字幕 cue 时间格式错误")
        start, end = map(_time_seconds, match.groups())
        text = re.sub(r"<[^>]*>", "", " ".join(lines[index + 1:])).strip()
        if not text or not re.search(r"[A-Za-z]{2}", text) or end <= start:
            raise ValueError("来源字幕 cue 正文为空或范围无效")
        if cues and start < cues[-1][0]:
            raise ValueError("来源字幕 cue 顺序错误")
        if duration is not None and end > duration + 1:
            raise ValueError("来源字幕越出原片时长")
        cues.append((start, end, text))
    if not cues or (duration is not None and cues[-1][1] < duration * .90):
        raise ValueError("来源字幕缺失或明显截断")
    return cues


def validate_source_comparison(manifest: dict, transcript: str) -> None:
    cues = parse_timestamped_vtt(transcript)
    for row in manifest["comparison_table"]:
        bounds = re.split(r"\s*[-–]\s*", row["timestamp_range"])
        if len(bounds) != 2:
            raise ValueError("对照时码错误")
        start, end = map(_time_seconds, bounds)
        if start < 0 or end <= start or end > cues[-1][1] + 1:
            raise ValueError("对照时码越出来源字幕")
        excerpt = " ".join(text for a, b, text in cues if a < end and b > start)
        normal = lambda text: re.sub(r"\s+", " ", text).casefold().strip()
        if not normal(row["source_english_gist"]) or normal(row["source_english_gist"]) not in normal(excerpt):
            raise ValueError("对照表来源摘录无法追溯对应时码的字幕")
    for start, length in manifest["raw_shots"]:
        if start + length > cues[-1][1] + 1:
            raise ValueError("拟用镜头越出来源证据时长")


def fetch_source_metadata_and_subtitles(url: str, output_dir: Path) -> tuple[str, str, Path, str]:
    """阶段一仅抓元数据与完整时间戳 VTT，不下载母片。"""
    video_id = _extract_video_id(url)
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(_run_bounded([settings.ytdlp_path, "--skip-download", "--no-playlist", "--dump-single-json", canonical_url]).stdout)
    if metadata.get("id") != video_id or not metadata.get("title"):
        raise ValueError("来源元数据缺失或 ID 不匹配")
    duration = metadata.get("duration")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("来源时长缺失")
    _run_bounded([settings.ytdlp_path, "--skip-download", "--no-playlist", "--write-subs", "--write-auto-subs",
                  "--sub-lang", "en.*,en", "--sub-format", "vtt", "-o", str(output_dir / f"{video_id}_sub.%(ext)s"), canonical_url])
    vtts = sorted(output_dir.glob(f"{video_id}_sub*.vtt"))
    if not vtts:
        raise ValueError("缺少来源字幕，提案已阻断")
    raw = vtts[0].read_text(encoding="utf-8", errors="strict")
    parse_timestamped_vtt(raw, duration=duration)
    return video_id, str(metadata["title"]), output_dir / f"{video_id}.mp4", raw


class ComplianceRemixService:
    """入口注入外层能力；核心不导入 scripts。"""

    def __init__(self, db: PipelineDB | None = None, *, generator=None, pipeline_factory=None, source_fetcher=None):
        self.db = db if db is not None else PipelineDB()
        self.generator = generator
        self.pipeline_factory = pipeline_factory or ComplianceVideoRemixPipeline
        self.source_fetcher = source_fetcher or fetch_source_metadata_and_subtitles

    def propose_remix(self, url: str, custom_work_dir: Path | str | None = None, *,
                      actor: str = "local", chat: str = "local", purpose: str = "produce") -> dict[str, Any]:
        source_id = _extract_video_id(url)
        proposal_id = "remix_" + uuid.uuid4().hex
        base = Path(custom_work_dir) if custom_work_dir else PROJECT_ROOT / "output/compliance_remix"
        work_dir = (base / proposal_id).resolve()
        source_url = f"https://www.youtube.com/watch?v={source_id}"
        vid_id, title, source_video, transcript = self.source_fetcher(source_url, work_dir)
        if vid_id != source_id or not parse_timestamped_vtt(transcript):
            raise ValueError("缺少有时间证据的源字幕")
        generator = self.generator or CommentaryGenerator()
        manifest, report, provider = generator.generate_proposal(source_title=title, transcript_text=transcript, video_id=source_id)
        if not report.passed:
            raise ValueError("提案内容检查未通过")
        manifest.update(id=proposal_id, source_id=source_id, source_url=source_url, source_title=title,
                        source_video_path=str(source_video.resolve()), work_dir=str(work_dir), provider_used=provider,
                        source_evidence={"kind": "timestamped_vtt", "sha256": hashlib.sha256(transcript.encode()).hexdigest(),
                                         "transcript": transcript})
        validate_manifest(manifest)
        validate_source_comparison(manifest, transcript)
        comparison = generator.render_comparison_markdown(manifest, report)
        review_text = (f"# 人工审核材料\n\n提案：{proposal_id}\n来源：{source_url}\n"
                       f"全部拟用镜头 [起点秒,时长秒]：{json.dumps(manifest['raw_shots'])}\n\n"
                       f"{comparison}\n\n# 全部拟制作内容\n\n"
                       f"{json.dumps({k: v for k, v in manifest.items() if k != 'source_evidence'}, ensure_ascii=False, indent=2)}"
                       f"\n\n# 完整来源字幕\n\n{transcript}")
        manifest["review_document_sha256"] = hashlib.sha256(review_text.encode()).hexdigest()
        work_dir.mkdir(parents=True, exist_ok=True)
        record = self.db.create_compliance_remix(proposal_id=proposal_id, source_id=source_id, manifest=manifest,
                   work_dir=str(work_dir), actor=actor, chat=chat, purpose=purpose)
        (work_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (work_dir / "comparison_table.md").write_text(review_text, encoding="utf-8")
        return {"success": True, "video_id": proposal_id, "source_id": source_id, "source_title": title,
                "remix_title": manifest["title"], "manifest_path": str(work_dir / "manifest.json"),
                "content_hash": record["content_hash"], "expires_at": record["expires_at"],
                "comparison_md": comparison, "review_text": review_text, "source_url": source_url, "raw_shots": manifest["raw_shots"], "comparison_md_path": str(work_dir / "comparison_table.md"),
                "censor_passed": True, "provider_used": provider, "source_video": str(source_video)}

    def load_proposal(self, proposal_id: str) -> tuple[dict, dict, Path]:
        validate_identifier(proposal_id)
        record = self.db.get_compliance_remix(proposal_id)
        manifest = json.loads(record["manifest_json"])
        if manifest_digest(manifest) != record["content_hash"]:
            raise ValueError("提案快照已篡改")
        work_dir = Path(record["work_dir"]).resolve()
        if str(work_dir) != record["work_dir"] or (work_dir.exists() and any(p.is_symlink() for p in work_dir.rglob("*"))):
            raise ValueError("审批工作目录或子文件已被符号链接替换")
        display = work_dir / "manifest.json"
        if not display.is_file() or manifest_digest(json.loads(display.read_text("utf-8"))) != record["content_hash"]:
            raise ValueError("展示清单与不可变审批快照不一致，请重新提案")
        review_path = work_dir / "comparison_table.md"
        if (not review_path.is_file() or hashlib.sha256(review_path.read_bytes()).hexdigest()
                != manifest.get("review_document_sha256")):
            raise ValueError("人工审阅文档与审批快照不一致")
        validate_manifest(manifest)
        source = Path(manifest["source_video_path"]).resolve()
        if not source.is_relative_to(work_dir) or source == work_dir:
            raise ValueError("来源文件越出工作目录")
        evidence = manifest.get("source_evidence", {})
        transcript = evidence.get("transcript", "")
        if (evidence.get("kind") != "timestamped_vtt" or "-->" not in transcript
                or hashlib.sha256(transcript.encode()).hexdigest() != evidence.get("sha256")):
            raise ValueError("来源字幕证据无效")
        validate_source_comparison(manifest, transcript)
        return record, manifest, work_dir

    def approve_remix(self, proposal_id: str, *, actor: str, chat: str, content_hash: str,
                      purpose: str = "produce", source_reviewed: bool = False) -> None:
        self.load_proposal(proposal_id)
        self.db.approve_compliance_remix(proposal_id, actor=actor, chat=chat, content_hash=content_hash, purpose=purpose, source_reviewed=source_reviewed)

    async def execute_approved_remix(self, video_id: str, upload_now: bool = False, dry_run: bool = False, *,
                                      actor: str = "local", chat: str = "local", content_hash: str = "") -> dict[str, Any]:
        record, manifest, work_dir = self.load_proposal(video_id)
        pipeline = self.pipeline_factory(work_dir=work_dir)
        if dry_run:
            return await pipeline.execute_full_pipeline(manifest=manifest, source_video=manifest["source_video_path"], dry_run=True, upload_now=upload_now)
        purpose = "publish" if upload_now else "produce"
        # 目前提案仅有字幕，不能声称源画面已人工审阅；发布保持明确阻断。
        if upload_now:
            raise PermissionError("尚无可核验的拟用源画面审核证据；发布被阻断")
        report = ComplianceCensorGuard().validate_script_manifest(manifest)
        if not report.passed:
            raise PermissionError("制作前内容检查未通过")
        from video_processing.core.maintenance import gate
        with gate().admit("compliance-remix", video_id) as ticket:
            ticket.start()
            self.db.claim_compliance_remix(video_id, actor=actor, chat=chat, content_hash=content_hash, purpose=purpose)
            try:
                source = Path(manifest["source_video_path"])
                # 不复用无法验证的旧母片，下载至本次临时文件后原子替换。
                temp = source.with_name(source.stem + ".download.mp4")
                rc, _, stderr = await run_bounded_async([settings.ytdlp_path, "--no-playlist", "-f",
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "--merge-output-format", "mp4", "-o", str(temp), manifest["source_url"]], timeout=300)
                if rc:
                    raise RuntimeError(f"源片下载失败 (exit {rc}): {stderr[-300:]}")
                if not temp.is_file() or temp.stat().st_size == 0:
                    raise ValueError("母片下载未产生有效文件")
                temp.replace(source)
                def execution_guard(candidate, candidate_dir):
                    live = self.db.get_compliance_remix(video_id)
                    if (live["state"] != "PROCESSING" or live["claimed_at"] is None or live["human_reviewed_hash"] != live["content_hash"] or live["human_reviewed_at"] is None
                            or manifest_digest(candidate) != live["content_hash"]
                            or Path(candidate_dir).resolve() != work_dir):
                        raise PermissionError("生产许可或快照不匹配")
                    return True
                pipeline.execution_guard = execution_guard
                receipt = await pipeline.execute_full_pipeline(manifest=manifest, source_video=str(source), dry_run=False, upload_now=False)
                state = "COMPLETED" if receipt.get("status") == "PRODUCED" else "FAILED"
                self.db.finish_compliance_remix(video_id, state=state, receipt=receipt)
                return receipt
            except BaseException as exc:
                self.db.finish_compliance_remix(video_id, state="FAILED", error=type(exc).__name__)
                raise
