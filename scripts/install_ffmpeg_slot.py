"""把第三方工具（yt-dlp / Whisper 等）的 FFmpeg 入口接入项目单名额。"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import sysconfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if Path(sys.prefix).resolve() != (root / ".venv").resolve():
        raise SystemExit("必须使用本项目 .venv/bin/python；禁止修改全局 Python")
    target = Path(sysconfig.get_path("purelib")) / "video_ffmpeg_slot.pth"
    content = "import video_processing.core.ffmpeg_slot as _vp_ffmpeg_slot; _vp_ffmpeg_slot.install()\n"
    if args.install:
        temporary = target.with_suffix(".pth.tmp")
        temporary.write_text(content)
        temporary.replace(target)
    # 新解释器验证，而不是把当前解释器已导入当作安装采用。
    code = "import subprocess,json; print(json.dumps({'enabled':subprocess.Popen.__module__=='video_processing.core.ffmpeg_slot'}))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    print(json.dumps({"hook": str(target), "installed": target.exists(),
                      "fresh_interpreter": json.loads(result.stdout)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
