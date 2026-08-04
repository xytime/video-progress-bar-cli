"""管线阶段运行态上报测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-04 | Codex | 验证可选状态回调不向核心层引入脚本依赖 |
"""

from video_processing.pipeline_manager import PipelineManager


def test_pipeline_reports_stage_through_optional_callback(tmp_path):
    reported = []
    manager = PipelineManager(str(tmp_path / "pipeline.db"), status_reporter=reported.append)

    manager._report_runtime_stage("video-id", "RENDERING", slice_index=2, preparation_only=True)

    assert reported == [{
        "current_video": "video-id",
        "current_slice_index": 2,
        "stage": "RENDERING",
        "preparation_only": True,
    }]
