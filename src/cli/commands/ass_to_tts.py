import os
import json
import logging
import subprocess
import shutil
import click
import pysubs2
from pathlib import Path
from config.settings import settings

logger = logging.getLogger(__name__)

@click.command()
@click.argument('input_file', type=click.Path(exists=True, path_type=Path))
@click.option('--output-dir', type=click.Path(path_type=Path), help="Directory to save audio files. Defaults to input_file_dir/tts_output")
@click.option('--voice-prompt', type=str, help="Path to voice prompt audio file (wav).")
@click.option('--index-tts-path', type=str, default="/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/indexTTS2.0/index-tts", help="Path to IndexTTS project root.")
def ass_to_tts(input_file: Path, output_dir: Path, voice_prompt: str, index_tts_path: str):
    """
    Generate speech from ASS subtitle file using IndexTTS.
    
    INPUT_FILE: Path to the .ass subtitle file.
    """
    logger.info(f"Processing subtitle file: {input_file}")
    
    if not output_dir:
        output_dir = input_file.parent / f"{input_file.stem}_tts"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")

    # Validate IndexTTS path
    index_tts_path = Path(index_tts_path)
    if not index_tts_path.exists():
        logger.error(f"IndexTTS path not found: {index_tts_path}")
        return
    
    worker_script = index_tts_path / "runner_worker.py"
    if not worker_script.exists():
        logger.error(f"Worker script not found at {worker_script}. Please ensure implementation is correct.")
        return

    # Check for venv python
    venv_python = index_tts_path / ".venv" / "bin" / "python"
    if not venv_python.exists():
        logger.warning(f"Virtual env python not found at {venv_python}. Trying system python in that dir (might fail due to deps).")
        venv_python = "python" # Fallback

    # Parse ASS file
    try:
        subs = pysubs2.load(str(input_file))
    except Exception as e:
        logger.error(f"Failed to load subtitle file: {e}")
        return

    # Prepare jobs
    jobs = []
    
    # Use provided prompt or default
    if voice_prompt:
        if not Path(voice_prompt).is_absolute() and not Path(voice_prompt).exists():
             # If relative, check if it is relative to index-tts examples 
             # But better to enforce absolute or relative to pwd
             pass 
    
    for i, event in enumerate(subs):
        if event.is_comment:
            continue
        
        text = event.plaintext.strip()
        if not text:
            continue
            
        # Naming convention: line_{index}_{start_time}.wav
        filename = f"line_{i:04d}.wav"
        out_path = output_dir / filename
        
        job = {
            "text": text,
            "output_path": str(out_path),
            "voice_prompt": voice_prompt # If None, worker uses default
        }
        jobs.append(job)
        
    logger.info(f"Found {len(jobs)} lines to process.")
    
    if not jobs:
        logger.warning("No text found in subtitles.")
        return

    # Create job file
    job_file = output_dir / "tts_jobs.json"
    with open(job_file, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Job file created: {job_file}")
    
    # Call worker script
    logger.info("Starting IndexTTS Worker...")
    
    cmd = [
        str(venv_python),
        str(worker_script),
        "--job_file", str(job_file)
    ]
    
    try:
        # Run in the index-tts dir to ensure imports work
        subprocess.run(cmd, cwd=str(index_tts_path), check=True)
        logger.info("TTS generation completed successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"TTS generation failed with exit code {e.returncode}")
    except Exception as e:
        logger.error(f"Error executing worker: {e}")

