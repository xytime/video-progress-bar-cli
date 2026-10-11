"""专题隔离夹具：真实 PipelineDB、内存官方响应、可控时钟；不使用凭据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-11 | Codex | 共享单元/浏览器数据；控制外部搜索与规则边界 |
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest
from video_processing.db.database import PipelineDB
from video_processing.topic_tracker.service import TopicTracker


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class Rules:
    fingerprint = "rules-1"
    fail = False
    hit = None

    def version(self):
        if self.fail:
            raise RuntimeError("unavailable")
        return self.fingerprint

    def check(self, meta):
        return self.hit


def video(index=1, *, title="Energy industry evidence review", duration="PT10M"):
    return dict(id=f"{index:011d}", snippet=dict(title=title, description="A source interview.",
                channelId="UC-isolated", channelTitle="Evidence Channel", publishedAt="2026-10-10T01:00:00Z", liveBroadcastContent="none"),
                contentDetails=dict(duration=duration), statistics=dict(viewCount="200", likeCount="2"))


class Adapter:
    def __init__(self):
        self.items = [video()]
        self.calls = []
        self.search_error = self.detail_error = None
        self.started = threading.Event()
        self.release = None
        self.has_key = True

    def configured(self):
        return self.has_key

    def search(self, topic, now, timeout):
        self.calls.append(("search", topic["query"], timeout))
        self.started.set()
        if self.release:
            assert self.release.wait(timeout=2)
        if self.search_error:
            raise self.search_error
        return [dict(id=dict(videoId=item["id"])) for item in self.items]

    def details(self, ids, timeout):
        self.calls.append(("details", ids, timeout))
        if self.detail_error:
            raise self.detail_error
        return self.items


@pytest.fixture
def tracker(tmp_path):
    clock, rules, adapter = Clock(), Rules(), Adapter()
    config = SimpleNamespace(topic_search_enabled=True, topic_quota_verified=True,
        topic_quota_project="isolated-project", topic_search_daily_limit=20,
        topic_general_daily_limit=40, enable_market_hours_guard=True,
        is_us_market_guard_window=lambda now: False)
    db = PipelineDB(str(tmp_path / "pipeline.sqlite"))
    service = TopicTracker(db, config, adapter, rules, clock=clock)
    service.mode("DISCOVERY_ONLY", 1, "fixture")
    yield service
    service.wait(3)


def topic(service, query="energy industry", **fields):
    value = dict(name="产业追踪", query=query, category="科技产业", lookback_days=7, valid_days=7)
    value.update(fields)
    return service.db.topic_save(value, "operator", service.clock())


def run(service, selected=None, idem=None):
    import uuid
    selected = selected or topic(service)
    job = service.start(selected["id"], selected["version"], idem or uuid.uuid4().hex, "operator")
    service.wait(3)
    return service.db.topic_jobs(idem=job["idempotency"])[0]


def decision(row, state="SAVED", reason=None):
    return dict(revision=row["revision"], decision_revision=row["decision_revision"],
                content_version=row["content_version"], state=state, reason=reason)
