"""普通加工和发布入口的二创来源拒绝回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | GPT-6.1 Sol | 无媒体、数据库和平台动作的入口拒绝证据 |
"""
import pytest

from video_processing.pipeline_manager import PipelineManager


@pytest.mark.parametrize('options',[{},dict(preparation_only=True),dict(submission_only=True),dict(claim=True)])
def test_ordinary_processing_rejects_remix_before_resources(options):
    # 不初始化管理器：若拒绝前访问任何数据库、锁或产物属性，测试会直接失败。
    manager=object.__new__(PipelineManager)
    video=dict(youtube_id='remix',source='COMPLIANCE_REMIX')
    assert PipelineManager._process_single_video.__wrapped__(manager,video,**options) is False


def test_ordinary_publication_rejects_remix_before_artifact_reads():
    manager=object.__new__(PipelineManager)
    assert manager._publish_prepared_assets(dict(source='COMPLIANCE_REMIX'),None,None,None,None) is False
