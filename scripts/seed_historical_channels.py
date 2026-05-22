import sys
from pathlib import Path
import subprocess
import json

# Add src to sys path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from video_processing.db import PipelineDB

HISTORICAL_URLS = [
    "https://www.youtube.com/watch?v=A1kX8fJx53c",
    "https://www.youtube.com/watch?v=oE5lNDhz9oo",
    "https://youtu.be/5cIINWjQ0Pg",
    "https://www.youtube.com/watch?v=MHiVBoWB3OE",
    "https://youtu.be/tNH43a1EI7s"
]

def main():
    print("Initializing Database...")
    db = PipelineDB()
    
    print("Extracting Channel IDs from historical URLs...")
    for url in HISTORICAL_URLS:
        print(f"Fetching metadata for {url}...")
        try:
            cmd = ["yt-dlp", "--print", "%(channel_id)s|||%(channel)s|||%(id)s|||%(title)s", "--no-playlist", "--no-warnings", "--cookies-from-browser", "safari", url]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = result.stdout.strip()
            
            if output:
                parts = output.split("|||", 3)
                if len(parts) == 4:
                    channel_id, channel_name, video_id, title = parts
                else:
                    channel_id, channel_name, video_id, title = None, None, None, None
            else:
                channel_id, channel_name, video_id, title = None, None, None, None
            
            if channel_id and channel_name:
                print(f"-> Found channel: {channel_name} ({channel_id})")
                db.add_channel(channel_id, channel_name, status="APPROVED", reason="Historical processed video")
                
                # Also record the video as COMPLETED
                if video_id and title:
                    db.add_video(video_id, title, channel_id, score=100)
                    db.update_video_status(video_id, "COMPLETED")
                    print(f"-> Recorded video: {title}")
        except subprocess.CalledProcessError as e:
            print(f"Error fetching {url}: yt-dlp failed (maybe blocked or cookie error). Error: {e.stderr}")
        except Exception as e:
            print(f"Error fetching {url}: {e}")

if __name__ == "__main__":
    main()
