"""真实临时 SQLite 验证字幕冷却、不可重置预算与各领取入口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 覆盖幂等、跨重启、显式修复、投稿保护及正常候选/恢复领取。 |
"""
import hashlib
import json
import time
import uuid
from types import SimpleNamespace

import pytest

from config.settings import settings
from video_processing.db import subtitle_recovery as recovery_module
from video_processing.db.database import PipelineDB
from video_processing.db.publishing_recovery import revision
from video_processing.publishing_recovery import PublishingRecoveryService
import video_processing.publishing_recovery as service_module


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(recovery_module, 'time', SimpleNamespace(time=lambda: clock[0]))
    out = tmp_path / 'output'
    out.mkdir()
    db = PipelineDB(str(out / 'subtitle.db'))
    db.add_video('subtitle-test', 'test', 'test-channel', score=90, source='AUTO')
    db.update_video_status('subtitle-test', 'TRANSCRIBING')
    return db, clock, tmp_path


def receipt(category='network', **extra):
    return dict(attempt_id=str(uuid.uuid4()), input_sha256=digest('input'),
                contract_sha256=digest('translation-v1'), failure_fingerprint=digest(category),
                category=category, code=str(category).upper(), retry_at=0, evidence_path='safe-evidence',
                quality_details=[]) | extra


def record(fixture, value=None, yid='subtitle-test'):
    db, _, root = fixture
    value = receipt() if value is None else value
    path = root / f"{value['attempt_id']}.json"
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False)
    path.write_text(raw)
    return db.record_subtitle_failure(yid, 0, value, str(path), digest(raw))


def video(db):
    return db.get_video_by_youtube_id('subtitle-test')


def test_failure_is_persistent_and_attempt_idempotent(fixture):
    db, clock, _ = fixture
    value = receipt()
    first = record(fixture, value)
    assert first['state'] == 'WAITING' and first['attempt_count'] == 1
    assert first['next_attempt_at'] == clock[0] + 300
    assert first['notify'] is True
    repeated = record(fixture, value)
    assert repeated['deduplicated'] and repeated['notify'] is False
    reopened = PipelineDB(db.db_path)
    assert reopened.get_subtitle_recovery(video(db)['id'])['attempt_count'] == 1
    assert reopened.subtitle_recovery_blocker(video(db)['id'])['code'] == 'SUBTITLE_BACKOFF'
    assert video(db)['status'] == 'PENDING' and video(db)['retry_count'] == 0
    with db.get_connection() as c:
        assert c.execute('SELECT count(*) FROM subtitle_recovery_events').fetchone()[0] == 1


def test_service_attempts_have_5_15_minute_then_repair_budget(fixture):
    db, clock, _ = fixture
    one = record(fixture)
    clock[0] = one['next_attempt_at'] + 1
    two = record(fixture)
    assert two['attempt_count'] == 2 and two['next_attempt_at'] == clock[0] + 900
    assert two['notify'] is False
    clock[0] = two['next_attempt_at'] + 1
    three = record(fixture)
    assert three['attempt_count'] == 3 and three['state'] == 'NEEDS_REPAIR' and three['notify']
    four = record(fixture, receipt('timeout'))
    assert four['attempt_count'] == 3 and four['suppressed'] and not four['notify']
    assert four['last_receipt_sha'] == three['last_receipt_sha']
    assert video(db)['status'] == 'FAILED' and video(db)['retry_count'] == 0


@pytest.mark.parametrize('category', ['authentication', 'quality', 'budget'])
def test_non_service_failure_never_becomes_automatic_retry(fixture, category):
    db, _, _ = fixture
    result = record(fixture, receipt(category))
    assert result['state'] == 'NEEDS_REPAIR' and result['attempt_count'] == 0
    assert db.subtitle_recovery_blocker(video(db)['id'])['state'] == 'NEEDS_REPAIR'
    assert not db.claim_video_for_processing('subtitle-test')


def test_busy_does_not_consume_budget_and_provider_due_is_honored(fixture):
    db, clock, _ = fixture
    for _ in range(5):
        row = record(fixture, receipt('busy'))
        assert row['attempt_count'] == 0 and row['next_attempt_at'] == clock[0] + 60
        clock[0] += 61
    future = record(fixture, receipt('quota', retry_at=clock[0] + 3600))
    assert future['next_attempt_at'] == clock[0] + 3600
    assert future['attempt_count'] == 1
    too_far = record(fixture, receipt('busy', retry_at=clock[0] + 86401))
    assert too_far['state'] == 'NEEDS_REPAIR'


def test_expired_chain_is_readonly_blocker_and_explicit_repair_preserves_budget(fixture):
    db, clock, _ = fixture
    row = record(fixture)
    clock[0] = row['expires_at'] + 1
    with db.get_connection() as c:
        before = c.execute('SELECT state,expires_at,attempt_count FROM subtitle_recovery').fetchone()
    assert db.get_subtitle_recovery(video(db)['id'])['state'] == 'WAITING'
    assert db.subtitle_recovery_blocker(video(db)['id'])['state'] == 'NEEDS_REPAIR'
    with db.get_connection() as c:
        assert tuple(c.execute('SELECT state,expires_at,attempt_count FROM subtitle_recovery').fetchone()) == tuple(before)
    assert db.release_subtitle_recovery_after_repair(video(db)['id'], row['last_receipt_sha'])
    released = db.get_subtitle_recovery(video(db)['id'])
    assert released['state'] == 'RELEASED' and released['attempt_count'] == 1 and released['expires_at'] == row['expires_at']
    assert not db.subtitle_recovery_blocker(video(db)['id'])
    assert not db.release_subtitle_recovery_after_repair(video(db)['id'], row['last_receipt_sha'])
    assert record(fixture)['state'] == 'NEEDS_REPAIR'


def test_explicit_repair_after_attempt_cap_allows_only_one_failed_trial(fixture):
    db, _, _ = fixture
    for _ in range(3):
        row = record(fixture)
    assert row['attempt_count'] == 3
    assert not db.release_subtitle_recovery_after_repair(video(db)['id'], digest('stale-receipt'))
    db.update_process_pid('subtitle-test', 123)
    assert not db.release_subtitle_recovery_after_repair(video(db)['id'], row['last_receipt_sha'])
    db.update_process_pid('subtitle-test', None)
    assert db.release_subtitle_recovery_after_repair(video(db)['id'], row['last_receipt_sha'])
    assert db.claim_video_for_processing('subtitle-test')
    failed = record(fixture)
    assert failed['attempt_count'] == 3 and failed['state'] == 'NEEDS_REPAIR'


def test_success_resolves_matching_chain_without_state_score_or_retry_reset(fixture):
    db, _, _ = fixture
    row = record(fixture)
    before = video(db)
    assert not db.resolve_subtitle_recovery(before['id'], input_sha256=digest('different'))
    assert not db.resolve_subtitle_recovery(before['id'], contract_sha256=digest('different'))
    assert db.resolve_subtitle_recovery(before['id'], row['input_sha256'], row['contract_sha256'])
    assert db.get_subtitle_recovery(before['id'])['state'] == 'RESOLVED'
    assert not db.subtitle_recovery_blocker(before['id'])
    assert not db.resolve_subtitle_recovery(before['id'])
    assert video(db) == before


def test_unrelated_new_contract_does_not_unlock_needs_repair(fixture):
    db, _, _ = fixture
    first = record(fixture, receipt('quality'))
    changed = record(fixture, receipt(contract_sha256=digest('unrelated-change')))
    assert changed['suppressed'] and not changed['notify']
    assert changed['contract_sha256'] == first['contract_sha256']
    assert not db.claim_video_for_processing('subtitle-test')
    assert db.release_subtitle_recovery_after_repair(video(db)['id'], first['last_receipt_sha'])
    repaired = record(fixture, receipt(contract_sha256=digest('fixed-translation')))
    assert repaired['state'] == 'WAITING' and repaired['attempt_count'] == 1
    # 回退旧合同不会获得已耗尽质量链的新预算。
    old = record(fixture, receipt('quality'))
    assert old['state'] == 'NEEDS_REPAIR' and old['attempt_count'] == 0
    assert record(fixture, receipt('quality'))['suppressed']


def test_expiry_closes_waiting_once_without_resetting_evidence_or_budget(fixture):
    db, clock, _ = fixture
    original = record(fixture)
    clock[0] = original['expires_at'] + 1
    assert db.subtitle_recovery_blocker(video(db)['id'])['state'] == 'NEEDS_REPAIR'
    expired = db.expire_subtitle_recoveries()
    assert len(expired) == 1 and expired[0]['state'] == 'NEEDS_REPAIR' and expired[0]['notify']
    assert expired[0]['youtube_id'] == 'subtitle-test' and expired[0]['slice_index'] == 0
    for field in ('attempt_count', 'last_receipt_sha', 'last_receipt_path', 'expires_at'):
        assert expired[0][field] == original[field]
    assert video(db)['status'] == 'FAILED' and video(db)['retry_count'] == 0
    assert db.expire_subtitle_recoveries() == []
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM subtitle_recovery_events WHERE event_type='EXPIRED'").fetchone()[0] == 1


@pytest.mark.parametrize('active', ['pid', 'status', 'submission'])
def test_expiry_does_not_modify_active_or_submitted_task(fixture, active):
    db, clock, _ = fixture
    original = record(fixture)
    clock[0] = original['expires_at'] + 1
    if active == 'pid':
        db.update_process_pid('subtitle-test', 123)
    elif active == 'status':
        db.update_video_status('subtitle-test', 'TRANSCRIBING')
    else:
        vid = video(db)['id']
        with db.get_connection() as c:
            c.execute("INSERT INTO publication_subjects(id,kind,video_id) VALUES('expiry-subject','VIDEO_ITEM',?)", (vid,))
            c.execute("INSERT INTO wechat_publications(video_id,subject_id,state,evidence_path,platform_post_id) VALUES(?,'expiry-subject','UNCERTAIN','evidence','export/test')", (vid,))
    before = video(db)
    assert db.expire_subtitle_recoveries() == []
    assert db.get_subtitle_recovery(before['id'])['state'] == 'WAITING'
    assert video(db) == before


@pytest.mark.parametrize('category', ['network', 'quality'])
def test_safe_quality_details_and_notifications_are_transition_bound(fixture, category):
    value = receipt(category, quality_details=[dict(segment_number=80, source_id=79,
        code='NUMBER_MAGNITUDE_MISMATCH', source_signal='$115', translation_signal='missing', prompt='secret')], prompt='secret')
    first = record(fixture, value)
    assert first['quality_details'] == [dict(segment_number=80, source_id=79,
        code='NUMBER_MAGNITUDE_MISMATCH', source_signal='$115', translation_signal='missing')]
    second = record(fixture, receipt(category))
    assert second['notify'] is False
    with fixture[0].get_connection() as c:
        assert all('prompt' not in r[0] and 'secret' not in r[0] for r in c.execute('SELECT details FROM subtitle_recovery_events'))


@pytest.mark.parametrize('category', ['wrong', None])
def test_invalid_receipt_is_rejected_without_db_change(fixture, category):
    with pytest.raises(ValueError):
        record(fixture, receipt(category=category))
    assert fixture[0].get_subtitle_recovery(video(fixture[0])['id']) is None


@pytest.mark.parametrize('protection', ['wechat', 'attempt', 'archive', 'douyin', 'kuaishou', 'subject-only'])
def test_all_submission_ledgers_protect_every_recovery_write(fixture, protection):
    db, _, _ = fixture
    row = record(fixture, receipt('quality'))
    vid = video(db)['id']
    with db.get_connection() as c:
        if protection in {'wechat', 'subject-only'}:
            c.execute("INSERT INTO publication_subjects(id,kind,video_id) VALUES('test-subject','VIDEO_ITEM',?)", (vid,))
            c.execute("INSERT INTO wechat_publications(video_id,subject_id,state,evidence_path,platform_post_id) VALUES(?, 'test-subject','UNCERTAIN','receipt','export/test')",
                      (None if protection == 'subject-only' else vid,))
        elif protection == 'attempt':
            c.execute("INSERT INTO publication_subjects(id,kind,video_id) VALUES('test-subject','VIDEO_ITEM',?)", (vid,))
            c.execute("INSERT INTO wechat_submission_attempts(attempt_id,video_id,subject_id,state,final_title,evidence_path) VALUES('submit',?,'test-subject','SUBMITTED_UNBOUND','test','receipt')", (vid,))
        elif protection == 'archive':
            c.execute("INSERT INTO wechat_publications_historical_archive(video_id,archived_at,archive_reason,state) VALUES(?,CURRENT_TIMESTAMP,'test','HISTORICAL_ARCHIVED')", (vid,))
        else:
            c.execute(f"INSERT INTO {protection}_publications(video_id,asset_sha256,source_kind,state,video_path,external_post_id) VALUES(?,'asset','NEW','UNCERTAIN','video','native-id')", (vid,))
    before = video(db)
    assert record(fixture) is None
    assert not db.resolve_subtitle_recovery(vid)
    assert not db.release_subtitle_recovery_after_repair(vid, row['last_receipt_sha'])
    assert video(db) == before
    assert db.get_subtitle_recovery(vid)['last_receipt_sha'] == row['last_receipt_sha']


@pytest.mark.parametrize('source', ['DISCOVERY', 'COMPLIANCE_REMIX', 'ENGLISH_WORLD', 'WALLSTREET_AB', 'DOUYIN', 'BAIJU_GUOXI'])
def test_independent_sources_cannot_acquire_normal_subtitle_recovery(fixture, source):
    db, _, _ = fixture
    with db.get_connection() as c:
        c.execute('UPDATE processed_videos SET source=?', (source,))
    assert record(fixture) is None


@pytest.mark.parametrize('state', ['PUBLISHED', 'UNCERTAIN', 'PUBLISHING', 'CANCELED', 'IGNORED', 'HISTORICAL_ARCHIVED'])
def test_terminal_and_publication_states_are_never_requeued(fixture, state):
    db, _, _ = fixture
    db.update_video_status('subtitle-test', state)
    assert record(fixture) is None
    assert video(db)['status'] == state


def test_shared_candidate_and_atomic_claim_gates_before_limit(fixture):
    db, _, _ = fixture
    row = record(fixture)
    db.add_video('next-task', 'next', 'test-channel', score=80, source='AUTO')
    assert [r['youtube_id'] for r in db.get_high_score_preparation_candidates(limit=1)] == ['next-task']
    assert [r['youtube_id'] for r in db.get_high_score_pending_videos(limit=1)] == ['next-task']
    assert not db.claim_video_for_processing('subtitle-test')
    assert any(b['code'] == 'SUBTITLE_RECOVERY' for b in db.get_publication_eligibility([video(db)['id']])[video(db)['id']]['blockers'])
    with db.get_connection() as c:
        c.execute('UPDATE subtitle_recovery SET next_attempt_at=? WHERE id=?', (time.time() - 5, row['id']))
    assert db.subtitle_recovery_blocker(video(db)['id']) is None
    assert db.get_high_score_preparation_candidates(limit=1)[0]['youtube_id'] == 'subtitle-test'
    assert db.claim_video_for_processing('subtitle-test')


def add_operation(db):
    row = video(db)
    key = str(uuid.uuid4())
    with db.get_connection() as c:
        c.execute("INSERT INTO publishing_recovery_operations(id,created,updated,state,request) VALUES(?,?,?,'QUEUED','{}')", (key, time.time(), time.time()))
        item = c.execute("""INSERT INTO publishing_recovery_items(operation_id,video_id,position,state,reason,original,current_revision,updated)
            VALUES(?,?,0,'WAITING','test',?,?,?)""", (key, row['id'], json.dumps(row), revision(row), time.time())).lastrowid
    return key, item


@pytest.mark.parametrize('category,expected', [('network', 'WAITING'), ('quality', 'ATTENTION')])
def test_recovery_dispatch_waits_or_requests_repair_without_model_or_upload(fixture, monkeypatch, category, expected):
    db, _, root = fixture
    failed = record(fixture, receipt(category))
    service = PublishingRecoveryService(db, root)
    classified = service.classify(db.publishing_recovery_video(video(db)['id']), {'schedule': {}})
    assert not classified['eligible'] and classified['subtitle_recovery']['state'] == failed['state']
    key, item = add_operation(db)
    assert db.activate_publishing_recovery_item(item) is None
    monkeypatch.setattr(service_module, 'running', lambda: True)
    monkeypatch.setattr(settings, 'wechat_publishing_paused', False)
    class ForbiddenManager:
        def _process_single_video(self, *a, **kw):
            raise AssertionError('waiting subtitle must not reach processing or upload')
    assert service.dispatch_once(ForbiddenManager()) is False
    stored = db.get_publishing_recovery_operation(key)['items'][0]
    assert stored['state'] == expected
    assert stored['next_at'] == failed['next_attempt_at']
    assert video(db)['retry_count'] == 0
