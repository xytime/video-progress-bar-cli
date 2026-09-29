"""把第三方工具（yt-dlp / Whisper 等）的 FFmpeg 入口接入项目共享名额。"""
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
    from video_processing.core.ffmpeg_slot import _DIRECTORY, DEFAULT_FFMPEG_SLOTS, config_status
    config = _DIRECTORY / "resource-limits.json"
    if args.install:
        _DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 首次安装创建配置，重装绝不覆盖用户已调整的名额。
        try:
            with config.open("x", encoding="utf-8") as stream:
                json.dump({"ffmpeg_slots": DEFAULT_FFMPEG_SLOTS}, stream, indent=2)
                stream.write("\n")
        except FileExistsError:
            pass
        temporary = target.with_suffix(".pth.tmp")
        temporary.write_text(content)
        temporary.replace(target)
    # 新解释器验证，而不是把当前解释器已导入当作安装采用。
    code = "import subprocess,json; print(json.dumps({'enabled':subprocess.Popen.__module__=='video_processing.core.ffmpeg_slot'}))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    print(json.dumps({"hook": str(target), "installed": target.exists(),
                      "fresh_interpreter": json.loads(result.stdout), **config_status()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
