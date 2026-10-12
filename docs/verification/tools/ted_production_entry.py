"""使用当前生产配置，复现原片清理入口；只写独立验证目录，不初始化生产 DAL。

依赖方向：验证工具 → PipelineManager / processors → settings。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 两条真实切片、未知保留及合成损坏回退的生产入口证据。 |
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request

from config.settings import settings
from video_processing import pipeline_manager
from video_processing.pipeline_manager import PipelineManager
from video_processing.processors import ted_source_cleanup as cleanup


class TrackingOnly:
    def __init__(self):
        self.events = []

    def update_process_pid(self, *args, **kwargs):
        self.events.append({"args": args, "kwargs": kwargs})


def run(root, destination, resume=False):
    assert root == Path(pipeline_manager.__file__).resolve().parents[2]
    assert destination.parent == root / "output/verification/ted-two-openings-2026-10-12"
    assert not destination.exists() or resume, "已有入口验证目录须显式--resume"
    assert not any(destination.glob('*_vertical*.mp4')), "不能用历史成片绕过重新读取模板"
    assert settings.enable_ted_source_cleanup, "不能在诊断中强制启用生产开关"
    destination.mkdir(exist_ok=resume)
    manager = PipelineManager.__new__(PipelineManager)
    manager._OUT_DIR, manager.db = destination, TrackingOnly()
    cases = [
        ("CKAyfGItpgg", "UCAuUUnT6oDeKwE6v1NGQxug", 3.5),
        ("65LZk_S9HBY", "UCsT0YIqwnpJCM-mx7-gSA4Q", 10.0),
        ("Hgh8L_aNiCA", "UCAuUUnT6oDeKwE6v1NGQxug", 0),
    ]
    rows = []
    for yid, channel, expected_offset in cases:
        source = root / "output/original_video" / f"{yid}.mp4"
        before = cleanup.media.sha256(source)
        started = time.monotonic()
        selected = manager._prepare_speech_opening(
            {"youtube_id": yid, "channel_id": channel, "slice_index": 0}, source)
        receipt = json.loads((destination / "speech_opening" / yid / f"{yid}.opening.json").read_text())
        assert receipt["offset_seconds"] == expected_offset
        assert receipt["end_seconds"] == receipt["source_duration"]
        assert (selected != source) == bool(expected_offset)
        assert cleanup.media.sha256(source) == before
        rows.append({"id": yid, "selected": str(selected), "receipt": receipt,
                     "source_unchanged": True, "seconds": round(time.monotonic() - started, 3)})
        print(yid, receipt["offset_seconds"], receipt["reason"], flush=True)
        (destination / "cases.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    # 明确的损坏夹具，不能计入真实样本或准确率。
    fault = destination / "synthetic-truncated.mp4"
    source = root / "output/original_video/CKAyfGItpgg.mp4"
    with source.open("rb") as file:
        fault.write_bytes(file.read(256))
    selected = manager._prepare_speech_opening(
        {"youtube_id": "synthetic-truncated", "channel_id": cases[0][1], "slice_index": 0}, fault)
    assert selected == fault
    fault_receipt = json.loads((destination / "speech_opening/synthetic-truncated/synthetic-truncated.opening.json").read_text())
    assert fault_receipt["reason"].startswith("UNAVAILABLE_")
    runtime = json.load(urllib.request.urlopen("http://127.0.0.1:" + str(settings.dashboard_port) + "/api/stats", timeout=10))
    executor = json.loads((root / "output/ready_publications_status.json").read_text())
    result = {
        "time": time.time(), "production_root": str(root),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "entry_module": str(Path(pipeline_manager.__file__).resolve()),
        "entry_sha256": cleanup.media.sha256(Path(pipeline_manager.__file__)),
        "cleanup_sha256": cleanup.media.sha256(Path(cleanup.__file__)),
        "packaging_sha256": cleanup.media.sha256(cleanup.PACKAGING),
        "settings": {"ted_source_cleanup": settings.enable_ted_source_cleanup,
                     "ted_opening_trim": settings.enable_ted_opening_trim},
        "runtime": {key: runtime[key] for key in ("active", "source_preparation", "resource_control", "server_time")},
        "executor": {key: executor[key] for key in (
            "pid", "stage", "current_video", "git_revision", "heartbeat_at",
            "ted_source_cleanup_enabled", "ted_opening_trim_enabled", "ted_source_cleanup_recipe")},
        "cases": rows, "synthetic_fault": fault_receipt, "tracked_pid_events": manager.db.events,
        "no_production_dal_or_publication_called": True,
    }
    (destination / "production-entry.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve(), args.resume)
