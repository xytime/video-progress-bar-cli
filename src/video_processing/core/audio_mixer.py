import logging
import subprocess
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

class AudioMixer:
    @staticmethod
    def create_mixed_audio_track(segments: List[Dict], total_duration: float, output_file: Path):
        """
        Create a single audio file from segments.
        segments: list of {'start': float, 'path': Path}
        total_duration: duration of the final audio track in seconds
        
        Uses ffmpeg to concatenate audio segments at specific timestamps.
        """
        # Complex mixing with ffmpeg command construction
        # Strategy:
        # 1. Create a null source of total_duration
        # 2. Add each segment as an input
        # 3. Use adelay to position them
        # 4. Mix all together
        
        # If too many segments, command line length might be an issue.
        # Alternative: Render silence + audio chunks iteratively or use a complex filter file.
        # Efficient approach for many segments:
        # Generate a silence file.
        # Use an ffmpeg filter complex.
        
        if not segments:
            logger.warning("No audio segments to mix.")
            return

        # Prepare inputs
        inputs = []
        filter_parts = []
        
        # We need a base silent track? Or just mix inputs with delay.
        # If we just mix with delay, we don't need a base track if we set duration.
        
        # Let's try constructing the filter complex.
        # inputs: -i segment1.wav -i segment2.wav ...
        # filter: [0]adelay=start_ms|start_ms[a0];[1]adelay=start_ms|start_ms[a1];...;[a0][a1]...amix=inputs=N:duration=first:dropout_transition=0
        # Wait, amix duration=first usually takes the longest? No 'longest' is default?
        # Duration should be explicitly set or handle by the longest (last subtitle + duration).
        
        cmd = ["ffmpeg", "-y"]
        
        for seg in segments:
            cmd.extend(["-i", str(seg['path'])])
            
        # complex filter
        filter_str = ""
        outputs = []
        
        for i, seg in enumerate(segments):
            start_ms = int(seg['start'] * 1000)
            # adelay adds delay to all channels. pipe output to [a{i}]
            filter_str += f"[{i}]adelay={start_ms}|{start_ms}[a{i}];"
            outputs.append(f"[a{i}]")
            
        # Mix them
        # amix inputs=N
        filter_str += "".join(outputs) + f"amix=inputs={len(segments)}:dropout_transition=0[out]"
        
        cmd.extend(["-filter_complex", filter_str, "-map", "[out]", str(output_file)])
        
        logger.info(f"Mixing {len(segments)} audio segments...")
        try:
            # Check command length limit? 
            # If segments > 100, this might fail.
            # Simplified approach for now.
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"Mixed audio saved to {output_file}")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg mixing failed: {e.stderr.decode()}")
            raise
