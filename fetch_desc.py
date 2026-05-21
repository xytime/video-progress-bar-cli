import subprocess
import json

urls = [
    "https://youtu.be/5cIINWjQ0Pg",
    "https://www.youtube.com/watch?v=BxG_ysI3xr4",
    "https://www.youtube.com/watch?v=beBRtz_VSGU",
    "https://www.youtube.com/watch?v=8qVbE9DHkEk"
]

for url in urls:
    cmd = ["yt-dlp", "-J", "--no-warnings", "--cookies-from-browser", "safari", url]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        print(f"[{data.get('id')}]")
        print(f"TITLE: {data.get('title')}")
        desc = data.get('description', '')
        print(f"DESC: {desc[:600]}")
        print("-" * 40)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
