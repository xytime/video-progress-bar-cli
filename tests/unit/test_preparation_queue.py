"""独立数据库验证等待/claim/让行/本地就绪；不启动任何业务处理。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 真实 SQLite owner CAS、同源互斥和发布账本边界。 |
"""
import pytest
from video_processing.db.database import PipelineDB


@pytest.fixture
def queue(tmp_path):
    return PipelineDB(str(tmp_path/'queue.db'))


def add(db, source='alpha', index=0):
    assert db.add_video(source, 'synthetic', 'channel', score=80, slice_index=index)
    assert db.enqueue_preparation(source, index, trigger_source='test')
    return db.get_video_by_youtube_id(source, slice_index=index)


def start(db, row, *, pid=123, birth='birth'):
    assert db.attach_preparation_worker(row['video_id'], row['owner_token'], pid, birth)
    return db.start_preparation_execution(row['youtube_id'], row['slice_index'], row['owner_token'], pid=pid, birth=birth)


def test_waiting_is_not_business_claim_and_duplicate_is_idempotent(queue):
    video = add(queue)
    assert not queue.enqueue_preparation('alpha', trigger_source='duplicate')
    row = queue.reserve_preparation(('alpha',))
    assert queue.get_video_by_youtube_id('alpha')['status'] == 'PENDING'
    assert not queue.enqueue_preparation('alpha', trigger_source='duplicate')
    assert queue.preparation_queue_snapshot()[0]['owner_token'] == row['owner_token']
    assert not queue.start_preparation_execution('alpha', 0, 'f'*32, pid=123, birth='birth')
    assert start(queue, row)
    assert queue.get_video_by_youtube_id('alpha')['status'] == 'PROCESSING'
    assert queue.preparation_execution_summary()['local_ready_count'] == 0


def test_same_source_slices_excluded_and_at_most_two_workers(queue):
    add(queue, 'alpha'); add(queue, 'alpha', 1); add(queue, 'beta'); add(queue, 'gamma')
    first = queue.reserve_preparation(('alpha','beta','gamma'))
    second = queue.reserve_preparation(('alpha','beta','gamma'))
    assert (first['youtube_id'], second['youtube_id']) == ('alpha','beta')
    assert queue.reserve_preparation(('alpha','beta','gamma')) is None


def test_yield_rotates_owner_without_failure_or_budget_reset(queue):
    add(queue, 'alpha'); add(queue, 'beta')
    row = queue.reserve_preparation(('alpha','beta'))
    assert start(queue, row)
    assert queue.yield_preparation_execution('alpha', 0, row['owner_token'])
    video = queue.get_video_by_youtube_id('alpha')
    assert video['status'] == 'PENDING' and video['retry_count'] == 0
    assert queue.reserve_preparation(('alpha','beta'))['youtube_id'] == 'beta'
    again = queue.reserve_preparation(('alpha','beta'))
    assert again['owner_token'] != row['owner_token']
    assert not queue.finish_preparation_execution(row['video_id'], row['owner_token'], state='DONE')
    assert queue.preparation_execution_summary()['yields'] == 1


def test_local_ready_separate_from_publisher_ready(queue):
    add(queue)
    row = queue.reserve_preparation(('alpha',)); assert start(queue, row)
    assert queue.mark_preparation_local_ready('alpha', 0, row['owner_token'])
    assert queue.finish_preparation_execution(row['video_id'], row['owner_token'], state='DONE')
    video = queue.get_video_by_youtube_id('alpha')
    assert video['status'] == 'LOCAL_READY'
    assert video['preparation_ready'] == 0
    assert video['publication_review_required'] == 1
    assert queue.preparation_queue_snapshot()[0]['stage'] == 'LOCAL_READY'
    assert queue.preparation_execution_summary()['local_ready_count'] == 1
    assert queue.get_high_score_pending_videos() == []
    assert PipelineDB.maintenance_active_work(queue.db_path) == []


def test_submitted_or_changed_business_state_never_yields_or_recovers(queue):
    add(queue)
    row = queue.reserve_preparation(('alpha',)); assert start(queue, row)
    queue.update_video_status('alpha', 'UNCERTAIN')
    assert not queue.yield_preparation_execution('alpha', 0, row['owner_token'])
    assert not queue.recover_preparation_execution(row['video_id'], row['owner_token'])
    assert queue.get_video_by_youtube_id('alpha')['status'] == 'UNCERTAIN'


def test_maintenance_sees_reserved_ticket_without_business_claim(queue):
    add(queue)
    queue.reserve_preparation(('alpha',))
    assert {'table':'preparation_execution_queue','count':1} in PipelineDB.maintenance_active_work(queue.db_path)


def test_resource_wait_releases_only_own_pre_submission_claim(queue):
    add(queue)
    row=queue.reserve_preparation(('alpha',)); assert start(queue,row)
    assert queue.finish_preparation_execution(row['video_id'],row['owner_token'],state='WAITING',reason='resource owner unknown')
    video=queue.get_video_by_youtube_id('alpha')
    assert video['status'] == 'PENDING' and video['retry_count'] == 0
    assert queue.preparation_execution_summary()['local_ready_count'] == 0


def test_allowlist_does_not_bypass_score_or_manual_content_review(queue):
    assert queue.add_video('low','synthetic','channel',score=10)
    assert not queue.enqueue_preparation('low',trigger_source='dashboard_scheduler')
    assert queue.add_video('review','synthetic','channel',score=80)
    queue.set_publication_review_required('review',True)
    assert not queue.enqueue_preparation('review',trigger_source='dashboard_scheduler')


def test_changed_score_after_enqueue_is_rechecked_before_reservation(queue):
    add(queue)
    with queue.get_connection() as c:
        c.execute("UPDATE processed_videos SET score=1 WHERE youtube_id='alpha'")
    assert queue.reserve_preparation(('alpha',)) is None
    assert queue.preparation_queue_snapshot()[0]['state'] == 'WAITING'
