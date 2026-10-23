"""历史批准与当前技术失败的 API/分集展示边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 技术失败拒绝复核放行且保留批准，读取近期真实加工阶段。 |
"""
import json
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from video_processing.core.censorship_state import review_state
from video_processing.db.database import PipelineDB
from web import app as web_app


@pytest.mark.parametrize('index', [0, 1])
def test_historical_tag_cannot_reapprove_technical_failure(tmp_path, monkeypatch, index):
    db = PipelineDB(str(tmp_path/'db.sqlite'))
    db.add_video('review', 'Review', 'channel', score=90)
    if index: db.add_video('review', 'Slice', 'channel', score=90, slice_index=index)
    db.update_video_censor_status('review', '🔴 政治安全违禁', 95, slice_index=index)
    db.set_bypass_censorship('review', True, slice_index=index)
    db.record_censorship_incident('review',slice_index=index,stage='manual_review',level='P0',
        action='MANUAL_BYPASS',tag='🔴 政治安全违禁',score=None,matched='rule',channel='operator',decision='MANUAL_P0_APPROVED')
    db.update_video_status('review', 'FAILED', error_msg='ValueError: 第 169 帧原字幕位置或文字不确定，停止出片：O', slice_index=index)
    trigger = Mock()
    monkeypatch.setattr(web_app,'db',db)
    monkeypatch.setattr(web_app,'_OUT_DIR',tmp_path)
    monkeypatch.setattr(web_app,'_trigger_video_async',trigger)
    before = db.get_video_by_youtube_id('review',slice_index=index)
    with TestClient(web_app.app) as client:
        result = client.post(f'/api/videos/review/bypass-censor?slice_index={index}',
                             json=dict(confirm_p0_review=True,confirm_pipeline_resume=True))
    assert result.json()['success'] is False
    trigger.assert_not_called()
    assert db.get_video_by_youtube_id('review',slice_index=index) == before
    row = web_app._attach_publish_display_fields([dict(before)])[0]
    assert row['censorship_state']['can_review'] is False
    assert row['censorship_state']['approval_label'] == 'P0 已人工放行'
    assert row['failure_summary'] == '原字幕定位失败'
    assert len(db.get_censorship_incidents('review',slice_index=index)) == 1
    assert not review_state(dict(before),p0_approved=False)['approval_label']


def test_new_review_layer_does_not_hide_behind_old_p0_approval():
    row = dict(status='FAILED',error_msg='Social Unrest Review: matched=Strike + Street',
               censor_tag='🔴 政治安全违禁',bypass_censorship=1)
    state = review_state(row,True)
    assert state['current_layer'] == 'RISK' and state['can_review']
    assert state['approval_label'] == 'P0 已人工放行'
    row['error_msg'] = 'Traceback: Censorship P0 mentioned in a technical error'
    assert not review_state(row,True)['can_review']


def test_processing_detail_uses_current_fresh_heartbeat_only(tmp_path,monkeypatch):
    monkeypatch.setattr(web_app,'_OUT_DIR',tmp_path)
    path=tmp_path/'review_s1_caption_progress.json'
    data=dict(stage='SOURCE_CAPTION_LOCATING',updated_at=time.time(),reused_steps=['copy','asr','translation'])
    path.write_text(json.dumps(data))
    row=dict(youtube_id='review',slice_index=1,status='TRANSCRIBING')
    assert web_app._caption_processing_detail(row) == '复用已有文案 · 复用转录 · 复用翻译 · 继续原字幕定位'
    assert web_app._caption_processing_detail(dict(row,status='FAILED')) == ''
    data['updated_at'] -= 100
    path.write_text(json.dumps(data))
    assert web_app._caption_processing_detail(row) == ''
