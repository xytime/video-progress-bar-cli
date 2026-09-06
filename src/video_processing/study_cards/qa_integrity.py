"""最终音频 QA 与本次文件内容的不可混用绑定。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-06 | Codex | 以三份文件 SHA256 拒绝同路径覆盖、旧 PASS 和质检中途修改。 |
"""
from pathlib import Path
import json

from video_processing.english_world.package_integrity import sha256_file


def artifact_fingerprints(*, mp4: Path, manifest: Path, timeline: Path) -> dict:
    paths = {"mp4": mp4, "manifest": manifest, "timeline": timeline}
    if any(not path.is_file() or path.stat().st_size == 0 for path in paths.values()):
        raise ValueError("音频 QA 绑定文件不存在或为空")
    return {key + "_sha256": sha256_file(path) for key, path in paths.items()}


def validate_audio_qa(report_path: Path, *, mp4: Path, manifest: Path, timeline: Path | None = None) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("state") != "PASS" or report.get("passed") is not True:
        raise ValueError("音频 QA 未通过：report is not PASS")
    if not report.get("timeline"):
        raise ValueError("音频 QA 缺少 timeline 内容绑定；必须重新质检")
    timeline = timeline or Path(report["timeline"])
    for key, path in {"mp4": mp4, "manifest": manifest, "timeline": timeline}.items():
        if not report.get(key) or Path(report[key]).resolve() != path.resolve():
            raise ValueError(f"音频 QA 与当前 {key} 产物不匹配")
    for key, digest in artifact_fingerprints(mp4=mp4, manifest=manifest, timeline=timeline).items():
        if report.get(key) != digest:
            raise ValueError(f"音频 QA 内容指纹不匹配或缺失：{key}；必须重新质检")
    return report
