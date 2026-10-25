# -*- coding: utf-8 -*-
"""专属复刻音色与深度财经配乐合成引擎 (audio_mixer.py)

特性：
1. 默认采用 Dragon 专属复刻音色 (S_brUsXErh2)，1.5 倍速 (speech_rate=50)，
   通过火山引擎豆包流式协议 (DoubaoTTSClient, seed-icl-2.0) 生成母带级清晰口播。
2. 精密章节气口控制：章节间插入 350ms 紧凑气口，片尾追加 600ms 余音，避免仓促截断。
3. -17dB 深度财经律动配乐：自动循环覆盖全片，1000ms 淡入 + 2500ms 柔和淡出，
   原片英文 100% 静音，彻底摆脱外媒解说干扰。

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.2.0 | 2026-10-25 | GPT-6.1 Sol | 文本与音色指纹缓存、媒体校验及原子产物 |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，实现 Dragon 音色 TTS 合成与 -17dB 动态配乐混音 |
| 1.1.0   | 2026-10-25 | Antigravity | 修复 PROJECT_ROOT 路径解析，增强技能内置资源/assets/audio 多级 BGM 回退检索 |
"""

from __future__ import annotations

import hashlib
import math
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydub import AudioSegment


from video_processing.utils.doubao_tts import DoubaoTTSClient, DoubaoTTSError

logger = logging.getLogger(__name__)

BGM_CANDIDATE_PATHS = [Path(__file__).resolve().parents[3] / "assets/audio/bgm_investigative_pulse.mp3"]


def resolve_bgm_path(preferred_path: Optional[Path | str] = None) -> Optional[Path]:
    """解析系统可用的深度财经 BGM 路径。"""
    if preferred_path:
        p = Path(preferred_path)
        if p.exists():
            return p
    for candidate in BGM_CANDIDATE_PATHS:
        if candidate.exists():
            return candidate
    return None


class AudioMixerEngine:
    """音频生成与混音引擎。"""

    def __init__(
        self,
        voice_id: str = "S_brUsXErh2",
        speech_rate: int = 50,
        resource_id: str = "seed-icl-2.0",
        chapter_pause_ms: int = 350,
        tail_silence_ms: int = 600,
        bgm_volume_db: float = -17.0,
        bgm_path: Optional[Path | str] = None,
    ):
        self.voice_id = voice_id
        self.speech_rate = speech_rate
        self.resource_id = resource_id
        self.chapter_pause_ms = chapter_pause_ms
        self.tail_silence_ms = tail_silence_ms
        self.bgm_volume_db = bgm_volume_db
        self.bgm_path = resolve_bgm_path(bgm_path)

    async def synthesize_chapters(
        self,
        chapters: List[Dict[str, Any]],
        cache_dir: Path | str,
    ) -> List[Tuple[int, Path, str, List[Tuple[str, float]]]]:
        """合成各个章节的语音音频片段。

        Returns:
            List of (chapter_index, audio_path, full_text, clauses_with_relative_durations)
        """
        if not chapters:
            raise ValueError("章节不能为空")
        seen = set()
        for chapter in chapters:
            index, text, clauses = chapter.get("index"), chapter.get("text"), chapter.get("clauses")
            if type(index) is not int or index <= 0 or index in seen or not isinstance(text, str) or not text.strip():
                raise ValueError("章节索引或文本无效")
            seen.add(index)
            if not clauses or any(not isinstance(c, (list, tuple)) or len(c) != 2 or
                                  not isinstance(c[0], str) or not c[0].strip() or
                                  isinstance(c[1], bool) or not isinstance(c[1], (int, float)) or
                                  not math.isfinite(c[1]) or c[1] <= 0 for c in clauses):
                raise ValueError("分句及权重无效")
            if "".join(c[0] for c in clauses) != text:
                raise ValueError("分句与口播不一致")
        cdir = Path(cache_dir)
        cdir.mkdir(parents=True, exist_ok=True)
        results = []

        client = None

        for ch in chapters:
            ch_idx = ch.get("index", 1)
            full_text = ch.get("text", "")
            clauses = ch.get("clauses", [])
            fingerprint = hashlib.sha256(json.dumps(
                [full_text, self.voice_id, self.speech_rate, self.resource_id],
                ensure_ascii=False).encode()).hexdigest()
            audio_path = cdir / f"chapter_{ch_idx}_{fingerprint}.mp3"
            def valid_audio(path):
                try:
                    return len(AudioSegment.from_file(path)) > 0
                except Exception:
                    return False

            if not valid_audio(audio_path):
                logger.info(f"Synthesizing chapter {ch_idx}: {full_text[:30]}...")
                try:
                    if client is None:
                        client = DoubaoTTSClient(resource_id=self.resource_id)
                    temporary = audio_path.with_name(audio_path.stem + ".tmp.mp3")
                    await client.async_synthesize(
                        text=full_text,
                        output_path=temporary,
                        speaker=self.voice_id,
                        speech_rate=self.speech_rate,
                    )
                    if not valid_audio(temporary):
                        raise ValueError("TTS 产物不是有效音频")
                    temporary.replace(audio_path)
                except Exception as exc:
                    logger.error(f"TTS synthesis failed for chapter {ch_idx}: {exc}")
                    raise

            results.append((ch_idx, audio_path, full_text, clauses))

        return results

    def build_master_audio(
        self,
        chapter_audio_list: List[Tuple[int, Path, str, List[Tuple[str, float]]]],
        output_dir: Path | str,
    ) -> Tuple[Path, float, List[Tuple[float, float, str]]]:
        """拼接全片口播母带，混入 -17dB 背景音乐，并生成全片分句的绝对起止时码。

        Returns:
            Tuple: (final_mixed_audio_path, total_duration_seconds, all_clauses_with_absolute_timings)
        """
        out_d = Path(output_dir)
        out_d.mkdir(parents=True, exist_ok=True)

        if not chapter_audio_list:
            raise ValueError("章节音频不能为空")
        speech_master = AudioSegment.empty()
        cur_time_s = 0.0
        all_clauses_timing: List[Tuple[float, float, str]] = []

        total_chapters = len(chapter_audio_list)
        for i, (ch_idx, audio_path, full_text, clauses) in enumerate(chapter_audio_list):
            seg_audio = AudioSegment.from_file(audio_path)
            seg_dur_s = len(seg_audio) / 1000.0
            if seg_dur_s <= 0:
                raise ValueError("章节音频为空")
            ch_start_s = cur_time_s

            speech_master += seg_audio
            cur_time_s += seg_dur_s

            # 计算分句时码
            if clauses:
                total_clause_weight = sum(
                    float(c[1]) if isinstance(c, (list, tuple)) and len(c) >= 2 else len(str(c))
                    for c in clauses
                )
                clause_cur_s = ch_start_s
                for cl in clauses:
                    if isinstance(cl, (list, tuple)) and len(cl) >= 2:
                        c_text, c_weight = str(cl[0]), float(cl[1])
                    else:
                        c_text, c_weight = str(cl), float(len(str(cl)))

                    dur = (c_weight / total_clause_weight) * seg_dur_s if total_clause_weight > 0 else seg_dur_s
                    all_clauses_timing.append((clause_cur_s, clause_cur_s + dur, c_text))
                    clause_cur_s += dur
            else:
                # 若无细分句，按整章处理
                all_clauses_timing.append((ch_start_s, cur_time_s, full_text))

            # 插入章节间气口 (除最后一章外)
            if i < total_chapters - 1 and self.chapter_pause_ms > 0:
                speech_master += AudioSegment.silent(duration=self.chapter_pause_ms)
                cur_time_s += (self.chapter_pause_ms / 1000.0)

        # 片尾余音
        if self.tail_silence_ms > 0:
            speech_master += AudioSegment.silent(duration=self.tail_silence_ms)
            cur_time_s += (self.tail_silence_ms / 1000.0)

        total_audio_ms = len(speech_master)
        total_audio_s = total_audio_ms / 1000.0
        logger.info(f"Master speech duration: {total_audio_s:.2f}s ({total_audio_ms} ms)")

        # 混入背景音乐
        final_audio_path = out_d / "master_audio_full.mp3"
        temporary = final_audio_path.with_name("master_audio_full.tmp.mp3")
        if self.bgm_path and self.bgm_path.exists():
            bgm = AudioSegment.from_file(self.bgm_path)
            if len(bgm) <= 0:
                raise ValueError("BGM 音频为空")
            loops_needed = int(total_audio_ms / len(bgm)) + 2
            bgm_looped = (bgm * loops_needed)[:total_audio_ms] + self.bgm_volume_db
            bgm_looped = bgm_looped.fade_in(1000).fade_out(2500)
            final_audio = speech_master.overlay(bgm_looped)
            final_audio.export(temporary, format="mp3")
            logger.info(f"Master audio with BGM exported to {final_audio_path}")
        else:
            speech_master.export(temporary, format="mp3")
            logger.warning(f"BGM not found at {self.bgm_path}; exported speech only to {final_audio_path}")

        if len(AudioSegment.from_file(temporary)) < total_audio_ms:
            raise ValueError("母带音频截断")
        temporary.replace(final_audio_path)
        return final_audio_path, total_audio_s, all_clauses_timing


def main():
    raise PermissionError("媒体生产必须通过 scripts/compliance_remix.py 的持久审批入口")


if __name__ == "__main__":
    main()
