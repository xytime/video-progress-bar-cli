"""自动字幕阶段心跳回归测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-27 | Codex | 验证 CLI 阶段心跳原子落盘且包含阶段与时间戳 |
| 1.1.0 | 2026-09-03 | Codex | 锁定阶段开始时间在同阶段心跳间保持稳定，供父进程执行阶段上限。 |
"""

import json

from cli.commands.auto_caption import _build_progress_reporter


def test_progress_reporter_writes_atomic_stage_payload(tmp_path):
    progress_file = tmp_path / "caption_progress.json"
    reporter = _build_progress_reporter(progress_file)

    assert reporter is not None
    reporter("TRANSLATING")

    payload = json.loads(progress_file.read_text(encoding="utf-8"))
    assert payload["stage"] == "TRANSLATING"
    assert isinstance(payload["updated_at"], float)
    assert isinstance(payload["stage_started_at"], float)
    assert payload["stage_started_at"] <= payload["updated_at"]
    assert not (tmp_path / ".caption_progress.json.tmp").exists()
