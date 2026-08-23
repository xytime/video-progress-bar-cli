"""视频号原创声明发布前审计测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-23 | Codex | 验证切片回退父源时间与本地决策证据 |
"""

import json
from unittest.mock import MagicMock

from video_processing.pipeline_manager import PipelineManager


def test_original_declaration_policy_for_slice_uses_parent_and_writes_evidence(tmp_path):
    manager = PipelineManager.__new__(PipelineManager)
    manager.db = MagicMock()
    manager.db.get_video_by_youtube_id.return_value = {
        "source_published_at": "2020-01-01T00:00:00Z",
    }
    evidence_dir = tmp_path / "wechat_evidence"

    declare_original = manager._original_declaration_for_submission(
        {"source_published_at": "2099-01-01T00:00:00Z"},
        yid="slice-source", slice_index=1, evidence_dir=evidence_dir,
    )

    assert declare_original is False
    manager.db.get_video_by_youtube_id.assert_called_once_with("slice-source", 0)
    payload = json.loads((evidence_dir / "original_declaration_policy.json").read_text(encoding="utf-8"))
    assert payload["source_published_at"] == "2020-01-01T00:00:00Z"
    assert payload["reason"] == "source_older_than_24_hours"
