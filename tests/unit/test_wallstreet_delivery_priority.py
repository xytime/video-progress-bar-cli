"""历史回查必须让出有资格的待发成片，不能越过既有评分与窗口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 用真实 DAL 验证待发优先、未加工及低分不抢占、已受理保护和窗口外恢复回查。 |
"""
import pytest

from config.settings import settings
from scripts.run_wallstreet_ab import _yield_to_ready_wechat_delivery
from video_processing.db.database import PipelineDB


@pytest.mark.parametrize('score,ready,submitted,window,expected', [
    (90, True, False, True, True),
    (60, True, False, True, False),
    (90, False, False, True, False),
    (90, True, True, True, False),
    (90, True, False, False, False),
])
def test_readback_yields_only_to_eligible_delivery(tmp_path, monkeypatch, score, ready, submitted, window, expected):
    db = PipelineDB(str(tmp_path / 'db.sqlite'))
    db.add_video('ready-queue', '既有成片', 'channel', score=score)
    db.set_video_preparation_ready('ready-queue', ready)
    if submitted:
        db.record_wechat_publication_confirmation('ready-queue', state='SUBMITTED_BOUND',
                platform_post_id='native', evidence_path='receipt.png')
        db.update_video_status('ready-queue', 'SUBMITTED_BOUND')
    monkeypatch.setattr(type(settings), 'default_output_dir', property(lambda _: tmp_path))
    monkeypatch.setattr(type(settings), 'is_public_publish_window', lambda _: window)
    monkeypatch.setattr(settings, 'wechat_publishing_paused', False)
    assert _yield_to_ready_wechat_delivery(db, 'wechat') is expected
    assert _yield_to_ready_wechat_delivery(db, 'douyin') is False
