import os
import logging
import json
import subprocess
from pathlib import Path
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

class TTSProvider(Enum):
    EDGE = "edge"
    INDEXTTS = "indextts"

class TTSEngine:
    def __init__(self, provider: TTSProvider, index_tts_path: Optional[Path] = None):
        self.provider = provider
        self.index_tts_path = index_tts_path
        
        if self.provider == TTSProvider.INDEXTTS:
            if not self.index_tts_path:
                # Default path if not provided
                self.index_tts_path = Path("/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/indexTTS2.0/index-tts")
            
            if not self.index_tts_path.exists():
                raise FileNotFoundError(f"IndexTTS path not found: {self.index_tts_path}")

    def generate_audio(self, text: str, output_file: Path, voice: str = "zh-CN-XiaoxiaoNeural"):
        """
        Generate audio for a single text segment.
        """
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        if self.provider == TTSProvider.EDGE:
            self._generate_edge(text, output_file, voice)
        elif self.provider == TTSProvider.INDEXTTS:
            self._generate_indextts(text, output_file, voice)

    def _generate_edge(self, text: str, output_file: Path, voice: str):
        import asyncio
        import edge_tts
        
        async def _run():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_file))
            
        try:
            asyncio.run(_run())
        except Exception as e:
            logger.error(f"EdgeTTS failed: {e}")
            raise

    def _generate_indextts(self, text: str, output_file: Path, voice_prompt: str):
        # reuse the runner_worker.py logic via subprocess
        pass

    def batch_generate(self, items: list[dict], output_dir: Path, voice_prompt: Optional[str] = None):
        """
        Batch generate audio.
        items: list of {'text': str, 'filename': str}
        """
        if self.provider == TTSProvider.EDGE:
            # Serial processing for EdgeTTS (it's fast enough and free)
            # Default voice for EdgeTTS
            voice = voice_prompt or "zh-CN-XiaoxiaoNeural"
            
            for item in items:
                out_path = output_dir / item['filename']
                if out_path.exists(): 
                    continue
                self.generate_audio(item['text'], out_path, voice=voice)
                
        elif self.provider == TTSProvider.INDEXTTS:
            # Batch processing for IndexTTS
            jobs = []
            for item in items:
                out_path = output_dir / item['filename']
                if out_path.exists(): 
                    continue
                
                job = {
                    "text": item['text'],
                    "output_path": str(out_path),
                    "voice_prompt": voice_prompt or "examples/test_audio.wav"
                }
                jobs.append(job)
            
            if not jobs:
                return

            job_file = output_dir / "tts_batch_jobs.json"
            with open(job_file, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)

            worker_script = self.index_tts_path / "runner_worker.py"
            venv_python = self.index_tts_path / ".venv" / "bin" / "python"
            if not venv_python.exists():
                venv_python = "python"

            cmd = [
                str(venv_python),
                str(worker_script),
                "--job_file", str(job_file)
            ]
            
            logger.info(f"Running IndexTTS batch for {len(jobs)} items...")
            subprocess.run(cmd, cwd=str(self.index_tts_path), check=True)
