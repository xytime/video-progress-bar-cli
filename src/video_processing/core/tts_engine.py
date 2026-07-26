# -*- coding: utf-8 -*-
"""TTS 引擎核心模块 — 统一本地与 Edge 语音合成接口。

支持的 Provider：
- EDGE: Microsoft Edge TTS（应急可用，不作为高品质中文配音默认值）
- INDEXTTS: IndexTTS 2.0 本地推理（高品质中文配音默认值）

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-05-20 | Gemini_3.1_Pro_High_planning | 初始创建，支持 EDGE / INDEXTTS |
| 3.0.0   | 2026-07-17 | Codex | 移除 CosyVoice/DashScope；TTS 保持本地 IndexTTS 优先，避免云端质量降级 |
"""

import asyncio
import json
import logging
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_INDEX_TTS_PATH = Path("/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/indexTTS2.0/index-tts")
_DEFAULT_INDEX_TTS_PROMPT = "test_audio.wav"


class TTSProvider(Enum):
    EDGE = "edge"
    INDEXTTS = "indextts"


class TTSEngine:
    """按 Provider 分发语音合成；IndexTTS 是高品质中文配音路径。"""

    def __init__(self, provider: TTSProvider, index_tts_path: Optional[Path] = None):
        self.provider = provider
        self.index_tts_path = Path(index_tts_path or _DEFAULT_INDEX_TTS_PATH)
        if self.provider == TTSProvider.INDEXTTS:
            self._validate_indextts_installation()

    def _validate_indextts_installation(self) -> None:
        worker = self.index_tts_path / "runner_worker.py"
        prompt = self.index_tts_path / _DEFAULT_INDEX_TTS_PROMPT
        if not self.index_tts_path.is_dir() or not worker.is_file():
            raise FileNotFoundError(f"IndexTTS 安装不完整: {self.index_tts_path}")
        if not prompt.is_file():
            raise FileNotFoundError(f"IndexTTS 参考音频不存在: {prompt}")

    def generate_audio(
        self,
        text: str,
        output_file: Path,
        voice: str = "zh-CN-XiaoxiaoNeural",
    ) -> list[dict]:
        """合成单条音频；当前两个 provider 均不提供字级时间戳。"""
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if self.provider == TTSProvider.EDGE:
            self._generate_edge(text, output_file, voice)
        elif self.provider == TTSProvider.INDEXTTS:
            # generate_audio 的默认 voice 是 Edge 音色名；只有真实存在的本地音频才作为 IndexTTS 参考音频。
            custom_prompt = Path(voice)
            if not custom_prompt.is_absolute():
                custom_prompt = self.index_tts_path / custom_prompt
            prompt_value = str(custom_prompt) if custom_prompt.is_file() else None
            self._run_indextts_jobs([self._indextts_job(text, output_file, prompt_value)])
        else:
            raise ValueError(f"未知的 TTS Provider: {self.provider}")
        return []

    def batch_generate(
        self,
        items: list[dict],
        output_dir: Path,
        voice_prompt: Optional[str] = None,
    ) -> dict[str, list[dict]]:
        """批量合成音频，任何缺失输出都视为失败，防止静默降级。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamps_map: dict[str, list[dict]] = {}
        if self.provider == TTSProvider.EDGE:
            voice = voice_prompt or "zh-CN-XiaoxiaoNeural"
            for item in items:
                output = output_dir / item["filename"]
                if not output.exists():
                    self._generate_edge(item["text"], output, voice)
                timestamps_map[item["filename"]] = []
            return timestamps_map

        jobs = []
        for item in items:
            output = output_dir / item["filename"]
            if not output.exists():
                jobs.append(self._indextts_job(item["text"], output, voice_prompt))
            timestamps_map[item["filename"]] = []
        if jobs:
            self._run_indextts_jobs(jobs)
        return timestamps_map

    def _indextts_job(self, text: str, output_file: Path, voice_prompt: Optional[str]) -> dict:
        prompt = Path(voice_prompt or _DEFAULT_INDEX_TTS_PROMPT)
        if not prompt.is_absolute():
            prompt = self.index_tts_path / prompt
        if not prompt.is_file():
            raise FileNotFoundError(f"IndexTTS 参考音频不存在: {prompt}")
        return {"text": text, "output_path": str(output_file), "voice_prompt": str(prompt)}

    def _run_indextts_jobs(self, jobs: list[dict]) -> None:
        job_file = Path(jobs[0]["output_path"]).parent / "tts_batch_jobs.json"
        job_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        venv_python = self.index_tts_path / ".venv" / "bin" / "python"
        python = str(venv_python) if venv_python.is_file() else "python"
        logger.info("[IndexTTS] 批量合成 %s 条", len(jobs))
        subprocess.run(
            [python, str(self.index_tts_path / "runner_worker.py"), "--job_file", str(job_file)],
            cwd=str(self.index_tts_path),
            check=True,
        )
        missing = [job["output_path"] for job in jobs if not Path(job["output_path"]).is_file()]
        if missing:
            raise RuntimeError(f"IndexTTS 未生成全部音频: {', '.join(missing[:3])}")

    @staticmethod
    def _generate_edge(text: str, output_file: Path, voice: str) -> None:
        import edge_tts

        async def run() -> None:
            await edge_tts.Communicate(text, voice).save(str(output_file))

        asyncio.run(run())
