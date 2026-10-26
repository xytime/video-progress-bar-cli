"""真实临时账本验证50分边界、只读准入、成片保留及公平领取。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| backlog-v1 | 2026-10-26 | Codex | 覆盖老成片指标与人工分、提交防重及界面/候选一致性。 |
"""
from contextlib import contextmanager

import pytest

from config.settings import settings, Settings
from video_processing.db.database import PipelineDB
from video_processing.pipeline_manager import PipelineManager
from video_processing.scoring import TED_AUTO_PUBLISH_CHANNEL_IDS, THE_ECONOMIST_CHANNEL_ID

TED, TEDX = TED_AUTO_PUBLISH_CHANNEL_IDS


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'ted_auto_publish_after_id', 0)
    monkeypatch.setattr(settings, 'ted_publish_score_line', 50)
    return PipelineDB(str(tmp_path / 'eligibility.db'))


def add(db, yid, score=50, likes=7, *, channel=TED, ready=True):
    db.add_video(yid, yid, channel, score=score, view_count=1000, like_count=likes)
    if ready:
        db.mark_video_ready_for_publication(yid)
    return db.get_video_by_youtube_id(yid)


@pytest.mark.parametrize('channel', [TED, TEDX])
@pytest.mark.parametrize('score,allowed', [(49, False), (50, True), (51, True)])
def test_49_50_51_readonly_selection_and_submission_policy(db, channel, score, allowed):
    row = add(db, 'boundary', score, channel=channel)
    facts = db.get_publication_eligibility([row['id']])[row['id']]
    assert facts['score_line'] == 50 and facts['eligible'] is allowed
    assert bool(db.get_high_score_pending_videos(ready_only=True)) is allowed
    assert bool(db.get_high_score_pending_videos(ready_only=True,min_score=40)) is allowed
    # 即使旧消费者传40，也不能降低TED专属线。
    assert bool(db.get_high_score_pending_videos(ready_only=True, channel_min_scores={channel:40})) is allowed
    manager = PipelineManager.__new__(PipelineManager)
    assert manager._is_auto_publish_score_eligible(row) is allowed
    with db.get_connection() as c:
        c.execute('UPDATE processed_videos SET preparation_ready=0 WHERE id=?', (row['id'],))
    assert bool(db.get_high_score_preparation_candidates()) is allowed


def test_other_speech_and_economist_policy_not_relaxed(db):
    other = next(c for c in settings.speech_channel_id_set if c not in (TED,TEDX))
    assert settings.auto_publish_channel_min_scores[other] == 40
    add(db, 'econ', 60, channel=THE_ECONOMIST_CHANNEL_ID)
    db.update_video_score('econ',100,force=True)
    econ = db.get_video_by_youtube_id('econ')
    assert econ['score'] == 60
    assert not db.get_publication_eligibility([econ['id']])[econ['id']]['eligible']
    assert not db.get_high_score_pending_videos(ready_only=True)


def test_evaluation_and_candidate_read_are_select_only(db, monkeypatch):
    row = add(db, 'read-only')
    real = db.get_connection
    @contextmanager
    def query_only():
        with real() as c:
            c.execute('PRAGMA query_only=ON')
            yield c
    monkeypatch.setattr(db, 'get_connection', query_only)
    assert db.get_publication_eligibility([row['id']])[row['id']]['eligible']
    assert db.get_high_score_pending_videos(ready_only=True)


def test_all_reasons_and_rate_boundary_precede_limit(db):
    blocked = add(db, 'blocked', 49, likes=6)
    passing = add(db, 'passing', 50)
    facts = db.get_publication_eligibility([blocked['id'],passing['id']])
    assert {b['code'] for b in facts[blocked['id']]['blockers']} == {'SCORE','TED_LIKE_RATE'}
    assert [r['id'] for r in db.get_high_score_pending_videos(ready_only=True,limit=1)] == [passing['id']]


def test_eligible_old_ready_is_not_starved_by_higher_score_newcomers(db):
    old = add(db, 'old', 50)
    with db.get_connection() as c:
        c.execute("UPDATE processed_videos SET publication_ready_at=datetime('now','-10 days') WHERE id=?", (old['id'],))
    for i in range(25):
        add(db, f'new-{i}', 99)
        assert db.get_high_score_pending_videos(ready_only=True,limit=1)[0]['id'] == old['id']


def test_ready_and_submit_intent_excluded_from_both_ageing_cleanups(db):
    ready = add(db, 'retained', 40)
    add(db, 'expired-low', 40, ready=False)
    add(db, 'retained-high', 100)
    with db.get_connection() as c:
        c.execute("UPDATE processed_videos SET created_at=datetime('now','-40 days'),upload_date='20200101'")
    assert db.cleanup_expired_waitlist_videos() == 1
    assert db.get_video_by_youtube_id('retained')['preparation_ready'] == 1
    assert db.discard_stale_queue_videos() == 0
    assert db.get_video_by_youtube_id('retained-high')['status'] == 'PENDING'
    assert db.get_video_by_youtube_id('retained')['publication_ready_at'] == ready['publication_ready_at']


def test_old_locked_ready_metrics_can_refresh_without_rewriting_score_or_assets(db, tmp_path):
    row = add(db, 'old-locked', 80, likes=6)
    db.update_video_score('old-locked', 80, force=True)
    artifact = tmp_path / 'old-locked.mp4';artifact.write_bytes(b'keep-existing-render')
    with db.get_connection() as c:
        c.execute("UPDATE processed_videos SET created_at=datetime('now','-40 days') WHERE id=?", (row['id'],))
    assert [r['id'] for r in db.get_ready_metric_refresh_candidates()] == [row['id']]
    before = db.get_video_by_youtube_id('old-locked')
    assert db.record_ready_metric_refresh('old-locked',0,1000,7) == (80,80)
    after = db.get_video_by_youtube_id('old-locked')
    assert after['is_manually_scored'] == 1
    for key in ('score','publication_ready_at','preparation_ready','status','retry_count','score_computed_at'):
        assert after[key] == before[key]
    assert db.get_publication_eligibility([row['id']])[row['id']]['eligible']
    assert db.get_ready_metric_refresh_candidates() == []
    assert artifact.read_bytes() == b'keep-existing-render'


def test_auto_ready_refresh_uses_50_floor_and_failure_cooldown(db):
    row = add(db, 'auto', 40, likes=6)
    with db.get_connection() as c:
        c.execute('UPDATE processed_videos SET id=10 WHERE id=?', (row['id'],))
    settings.ted_auto_publish_after_id = 1
    assert db.record_ready_metric_refresh('auto',0,1000,7) == (40,50)
    assert db.record_ready_metric_refresh('auto',0,None,None) == (50,50)
    assert db.get_ready_metric_refresh_candidates() == []


@pytest.mark.parametrize('state', ['UNCERTAIN','SUBMITTED_UNBOUND','SUBMITTED_BOUND'])
def test_refresh_cannot_revive_or_modify_submitted_identity(db, state):
    row = add(db, 'protected', 80)
    db.record_wechat_publication_confirmation('protected',state=state,evidence_path=None,
        platform_post_id='export/exact-fixture' if state=='SUBMITTED_BOUND' else None)
    before = db.get_video_by_youtube_id('protected')
    assert not db.get_ready_metric_refresh_candidates()
    assert db.record_ready_metric_refresh('protected',0,2000,30) is None
    assert db.get_video_by_youtube_id('protected') == before
    assert not db.get_publication_eligibility([row['id']])[row['id']]['eligible']


def test_refresh_reserves_bounded_share_and_rotates_after_failed_fetch(db):
    for i in range(8):
        add(db,f'old-{i}',80)
    first = db.get_ready_metric_refresh_candidates(limit=999)
    assert len(first) == 5
    for r in first:
        db.record_ready_metric_refresh(r['youtube_id'],0,None,None)
    assert len(db.get_ready_metric_refresh_candidates()) == 3


def test_ted_setting_is_exactly_approved_value():
    assert Settings(_env_file=None).ted_publish_score_line == 50
    for bad in (40,49,51):
        with pytest.raises(ValueError):
            Settings(_env_file=None,ted_publish_score_line=bad)


def test_all_ted_list_score_consumers_share_50_and_ready_not_expired(db):
    add(db,'low49',49,ready=False)
    add(db,'line50',50,ready=False)
    add(db,'above51',51,ready=False)
    queue = db.get_paginated_videos('queue',1,20)
    assert {r['youtube_id'] for r in queue[0]} == {'line50','above51'}
    assert set(db.get_waitlist_clearable_ids()) == {'low49'}
    assert db.get_tab_counts()['queue'] == 2
    assert db.get_tab_counts()['waitlist'] == 1
    with db.get_connection() as c:
        c.execute("UPDATE processed_videos SET created_at=datetime('now','-40 days'),upload_date='20200101'")
    assert db.cleanup_expired_waitlist_videos() == 1
    assert db.get_video_by_youtube_id('line50')['status'] == 'PENDING'
    assert db.get_video_by_youtube_id('above51')['status'] == 'PENDING'


@pytest.mark.parametrize('ready_only',[False,True])
def test_refresh_runner_keeps_existing_total_cap_and_deduplicates(monkeypatch,ready_only):
    from types import SimpleNamespace
    from scripts import rescore_refresh as runner
    recorded=[];calls=[]
    class DB:
        def get_rescore_candidates(self,**kwargs):
            assert not ready_only and kwargs['limit']==50
            return [dict(youtube_id=f'r-{i}',slice_index=0,channel_id=TED,score=49) for i in range(2)] + [dict(youtube_id=f'l-{i}',slice_index=0,channel_id=TED,score=49) for i in range(48)]
        def get_ready_metric_refresh_candidates(self,**kwargs):
            assert kwargs['limit']==5
            return [dict(youtube_id=f'r-{i}',slice_index=0,channel_id=TED,score=49) for i in range(5)]
        def record_ready_metric_refresh(self,yid,si,views,likes):
            recorded.append(('ready',yid));return 49,50
        def record_rescore_attempt(self,yid,si,views,likes):
            recorded.append(('low',yid));return 49,50
    monkeypatch.setattr(runner,'PipelineDB',DB)
    monkeypatch.setattr(runner,'settings',SimpleNamespace(enable_ready_metric_refresh=True,youtube_data_api_key='fixture',youtube_data_api_timeout_sec=2,auto_publish_channel_min_scores={TED:50}))
    def fetch(ids,**kwargs):
        calls.append(ids);return {y:(1000,7) for y in ids}
    monkeypatch.setattr(runner,'fetch_video_statistics',fetch)
    runner.main(ready_only=ready_only)
    expected=5 if ready_only else 50
    assert len(calls)==1 and len(set(calls[0]))==expected
    assert len(recorded)==expected and sum(kind=='ready' for kind,y in recorded)==5
