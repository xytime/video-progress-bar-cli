import os
import shutil
import subprocess
from pathlib import Path
import logging
import sys
import click
from click.testing import CliRunner

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from cli.main import cli
from video_processing.processors.subtitle_extractor import SubtitleExtractionProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_extract_subs")

def create_test_video(path: Path):
    """Generate a test video with speech using macOS 'say' and ffmpeg"""
    try:
        # 1. Generate Audio
        audio_path = path.parent / "test_audio.aiff"
        text = "This is a test for subtitle extraction. No translation needed."
        subprocess.run(["say", text, "-o", str(audio_path)], check=True)
        
        # 2. Merge with black video
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=640x480:d=5",
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
        # Create a dummy file if ffmpeg fails (e.g. CI env without ffmpeg)
        # But we assume local env has ffmpeg based on user info.
        with open(path, 'wb') as f:
            f.write(b'dummy content')
        # raise # Don't raise, let the test fail later if needed or mock

def test_extract_subs_command():
    test_dir = Path("draft-code/test_data_subs")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True, exist_ok=True)
    
    video_path = test_dir / "test_speech.mp4"
    create_test_video(video_path)
    
    runner = CliRunner()
    
    # Test 1: SRT output (default)
    logger.info("Running extract_subs (SRT)...")
    result = runner.invoke(cli, [
        'extract-subs', 
        str(video_path), 
        '--model', 'tiny',  # Use tiny for speed
        '--device', 'cpu',
        '--format', 'srt'
    ])
    
    if result.exit_code != 0:
        logger.error(f"Command failed: {result.output}")
        # print traceback
        print(result.exception)
    
    assert result.exit_code == 0
    assert "Success! Subtitles saved to" in result.output
    
    srt_path = video_path.with_suffix('.srt')
    assert srt_path.exists()
    
    with open(srt_path, 'r') as f:
        content = f.read()
        logger.info(f"SRT Content:\n{content}")
        assert "This" in content or "test" in content or "Translation" in content # Basic check
        
    # Test 2: ASS output
    logger.info("Running extract_subs (ASS)...")
    result = runner.invoke(cli, [
        'extract-subs', 
        str(video_path), 
        '--model', 'tiny', 
        '--format', 'ass'
    ])
    
    assert result.exit_code == 0
    ass_path = video_path.with_suffix('.ass')
    assert ass_path.exists()
    
    
    # Cleanup
    # shutil.rmtree(test_dir) # Keep for inspection if needed

if __name__ == "__main__":
    test_extract_subs_command()
