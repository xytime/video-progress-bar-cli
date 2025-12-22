import os
import subprocess
from pathlib import Path
import logging
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from video_processing.processors.caption_processor import AutoCaptionProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_captioning")

def create_test_video(path: Path):
    """Generate a test video with speech using macOS 'say' and ffmpeg"""
    try:
        # 1. Generate Audio
        audio_path = path.parent / "test_audio.aiff"
        text = "Welcome to the automatic captioning system test."
        subprocess.run(["say", text, "-o", str(audio_path)], check=True)
        
        # 2. Merge with black video
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=640x480:d=4",
            "-i", str(audio_path),
            "-c:v", "libx264", "-c:a", "aac",
            "-shortest",
            str(path)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Clean up audio
        os.remove(audio_path)
        logger.info(f"Created test video at: {path}")
        
    except Exception as e:
        logger.error(f"Failed to create test video: {e}")
        # Build a fallback dummy file just to test extraction flow if say fails? 
        # But 'say' should work on mac.
        raise

def test_transcription():
    test_dir = Path("draft-code/test_data")
    test_dir.mkdir(parents=True, exist_ok=True)
    video_path = test_dir / "test_speech.mp4"
    
    if not video_path.exists():
        create_test_video(video_path)
        
    processor = AutoCaptionProcessor(
        input_path=video_path,
        model_size="base", # Use base for speed in test
        src_lang="en"
    )
    
    try:
        processor.process()
        logger.info("Test passed: Transcribe ran without error.")
        
        # Verify ASS file
        ass_path = video_path.with_suffix('.ass')
        if ass_path.exists():
            logger.info(f"ASS file generated at: {ass_path}")
            with open(ass_path, 'r', encoding='utf-8') as f:
                content = f.read()
                logger.info("ASS Content Preview:")
                logger.info(content[:500])  # Print first 500 chars
        else:
            logger.error(f"ASS file NOT found at: {ass_path}")
            raise FileNotFoundError("ASS file not generated")
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

if __name__ == "__main__":
    test_transcription()
