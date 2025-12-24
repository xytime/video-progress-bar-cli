"""Subtitle Extraction Processor - Extract subtitles without translation or burning"""
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import os
import pysubs2
from datetime import timedelta

from .caption_processor import AutoCaptionProcessor
from ..core.base import VideoProcessingError

logger = logging.getLogger(__name__)

class SubtitleExtractionProcessor(AutoCaptionProcessor):
    """
    Subtitle Extraction Processor
    
    Functions:
    1. Extract audio
    2. Transcribe using Whisper (ASR)
    3. Output subtitles (SRT/ASS/VTT)
    """
    
    def __init__(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        model_size: str = "small",
        device: str = "cpu",
        output_format: str = "srt"
    ):
        # Initialize parent with defaults for unused params
        super().__init__(
            input_path=input_path,
            output_path=output_path,
            model_size=model_size,
            src_lang="auto", # Allow auto-detection
            target_lang=None, # No translation
            device=device
        )
        self.output_format = output_format.lower()

    def process(self, **kwargs) -> Path:
        """
        Process video: Extract Audio -> Transcribe -> Save Subtitles
        """
        logger.info(f"Extracting subtitles for: {self.input_path}")
        
        # 1. Load Model
        self._load_model()
        
        # 2. Extract Audio
        audio_path = self._extract_audio()
        
        try:
            # 3. Transcribe
            logger.info("Transcribing audio...")
            segments = self._transcribe_audio(audio_path)
            
            # 4. Generate Output File
            output_file = self._save_subtitles(segments)
            logger.info(f"Subtitles saved to: {output_file}")
            
            return output_file
            
        finally:
            # Cleanup
            if audio_path.exists():
                os.remove(audio_path)

    def _save_subtitles(self, segments: List[Dict[str, Any]]) -> Path:
        """Generate subtitle file in specified format"""
        
        # Determine output path
        if self.output_path and self.output_path.suffix.lower() == f'.{self.output_format}':
            out_path = self.output_path
        elif self.output_path and self.output_path.is_dir():
             out_path = self.output_path / f"{self.input_path.stem}.{self.output_format}"
        else:
             out_path = self.input_path.with_suffix(f'.{self.output_format}')
             
        # Use pysubs2 for compatible formats
        if self.output_format in ['srt', 'ass', 'ssa', 'vtt']:
            subs = pysubs2.SSAFile()
            
            for seg in segments:
                start_ms = int(seg['start'] * 1000)
                end_ms = int(seg['end'] * 1000)
                text = seg.get('text', '').strip()
                
                event = pysubs2.SSAEvent(
                    start=start_ms, 
                    end=end_ms, 
                    text=text
                )
                subs.events.append(event)
            
            subs.save(str(out_path))
        
        # Fallback or manual handling if needed (txt, etc)
        else:
             # Simple text dump
             with open(out_path, 'w', encoding='utf-8') as f:
                 for seg in segments:
                     f.write(f"[{timedelta(seconds=seg['start'])} -> {timedelta(seconds=seg['end'])}] {seg['text'].strip()}\n")

        return out_path
