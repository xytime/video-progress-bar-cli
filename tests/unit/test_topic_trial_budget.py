"""试运行累计预算：真实 SQLite、适配器调用证据和重启/跨日边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-14 | Codex | 累计预算不会因重试、跨日、项目变化或并发超发 |
"""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

import pytest

from tests.topic_candidate_fixtures import tracker, topic, run
from video_processing.core.topic_candidates import TopicError
from video_processing.db.database import PipelineDB
from video_processing.topic_tracker.service import TopicTracker
from video_processing.utils.topic_search import SearchFailure


def test_trial_counts_failed_requests_across_days_and_restart(tracker):
    tracker.config.topic_trial_mode = True
    tracker.adapter.detail_error = SearchFailure("NETWORK", "timeout", retryable=True)
    selected = topic(tracker)
    for _ in range(3):
        assert run(tracker, selected)["state"] == "PARTIAL"
        tracker.clock.advance(days=1)
    peer = TopicTracker(PipelineDB(tracker.db.db_path), tracker.config,
                        tracker.adapter, tracker.rules, clock=tracker.clock)
    peer.config.topic_quota_project = "another-project"
    before = list(peer.adapter.calls)
    job = run(peer, selected)
    assert job["code"] == "TRIAL_BUDGET"
    assert peer.adapter.calls == before
    assert len([call for call in before if call[0] == "search"]) == 3
    assert len([call for call in before if call[0] == "details"]) == 6
    assert peer.view()["trial"] == dict(enabled=True, budget={
        "search": dict(used=3, limit=3, remaining=0),
        "general": dict(used=6, limit=6, remaining=0)})


@pytest.mark.parametrize("bucket,cap", [("search", 3), ("general", 6)])
def test_trial_atomic_across_threads_and_processes(tracker, bucket, cap):
    selected = topic(tracker)
    job = tracker.db.topic_create_job(selected["id"], selected["version"],
                                      "trial-concurrency", "test", tracker.clock())
    def reserve(_):
        try:
            tracker.db.topic_reserve(job["id"], "project", bucket, 20, tracker.clock(), trial=True)
            return True
        except TopicError as exc:
            assert exc.code == "TRIAL_BUDGET"
            return False
    script = (
        "from video_processing.db.database import PipelineDB; "
        "from datetime import datetime; import sys; "
        "PipelineDB(sys.argv[1]).topic_reserve(sys.argv[2],'project',sys.argv[3],20,"
        "datetime.fromisoformat(sys.argv[4]),trial=True)"
    )
    processes = [subprocess.Popen([sys.executable, "-c", script, tracker.db.db_path,
                    job["id"], bucket, tracker.clock().isoformat()],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        thread_success = sum(pool.map(reserve, range(8)))
    for process in processes:
        process.communicate(timeout=20)
    assert thread_success + sum(p.returncode == 0 for p in processes) == cap
    assert tracker.db.topic_trial_budget()[bucket]["used"] == cap


@pytest.mark.parametrize("flag", ["topic_scheduler_enabled", "topic_admission_enabled"])
def test_trial_rejects_automatic_capabilities(tracker, flag):
    tracker.config.topic_trial_mode = True
    setattr(tracker.config, flag, True)
    with pytest.raises(TopicError) as caught:
        run(tracker)
    assert caught.value.code == "TRIAL_CONFIG"
    assert not tracker.adapter.calls


def test_entering_trial_counts_existing_reservations(tracker):
    selected = topic(tracker)
    for _ in range(3):
        run(tracker, selected)
        tracker.clock.advance(minutes=16)
    tracker.config.topic_trial_mode = True
    assert run(tracker, selected)["code"] == "TRIAL_BUDGET"
    assert len([call for call in tracker.adapter.calls if call[0] == "search"]) == 3


def test_trial_also_honors_smaller_daily_limit(tracker):
    tracker.config.topic_trial_mode = True
    tracker.config.topic_search_daily_limit = 1
    selected = topic(tracker)
    run(tracker, selected)
    tracker.clock.advance(minutes=16)
    assert run(tracker, selected)["code"] == "BUDGET"
    assert tracker.db.topic_trial_budget()["search"]["used"] == 1
