"""单视频子进程入口；真实归属随 FD 继承，视频数据经 stdin 传入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 替换 Web 内联执行并保持单项维护归属 |
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_processing.core.maintenance import current, MaintenanceDenied
from video_processing.core.maintenance_child import single_script
from video_processing.pipeline_manager import PipelineManager


@single_script
def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trigger-source", required=True)
    parser.add_argument("--object-key", required=True)
    args = parser.parse_args()
    video = json.load(sys.stdin)
    key = f"{video['youtube_id']}:{int(video.get('slice_index') or 0)}"
    if key != args.object_key or (current().row.get("parent") and current().key != key):
        raise MaintenanceDenied("INVALID_CONTINUATION")
    manager = PipelineManager(trigger_source=args.trigger_source)
    manager._process_single_video(video)
    manager.wait_for_review_notifications(timeout=120.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
