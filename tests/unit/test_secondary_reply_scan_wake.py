"""准确释放时间、重启、并发、配置变化和原生计费的离线回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 临时状态文件及合成时钟；零平台、零真实留言、零出站通知。 |
"""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

from video_processing.interaction.secondary_reply_scan_wake import (
    ScanWakeStore, resume_scan_wait, scope_key, window_open_at,
)
from tests.unit.test_wechat_operations_policy import active, state, event
from tests.unit.test_runtime_configuration import configured, save
from tests.unit.test_secondary_reply_cli_real_entry import cli

SCOPE = scope_key("synthetic-account", "synthetic-finder")


class Clock:
    def __init__(self):
        self.wall, self.elapsed, self.after_sleep = 10000.0, 0.0, None
    def now(self):
        return self.wall
    def monotonic(self):
        return self.elapsed
    def sleep(self, seconds):
        self.wall += seconds
        self.elapsed += seconds
        if self.after_sleep:
            self.after_sleep()


class Environment:
    def __init__(self, release):
        self.release, self.enabled, self.limit, self.revision = release, True, 5, "initial"
        self.unknown_block = False
    def inspect(self, now):
        return {"enabled": self.enabled, "window_until": now, "scan_limit": self.limit,
                "revision": self.revision,
                "admission": {"allowed": now >= self.release and not self.unknown_block,
                    "until": None if self.unknown_block else max(now, self.release),
                    "blockers": [] if now >= self.release else [{"code": "OPERATION_INTERVAL"}]}}


def pending(tmp_path, release=10007):
    wakes = ScanWakeStore(tmp_path / "scan.json")
    wakes.defer(SCOPE, until=release, scan_limit=5, codes=["OPERATION_INTERVAL"])
    return wakes


def run(wakes, clock, env, execute, cadence=72):
    return resume_scan_wait(wakes, SCOPE, env, execute, cadence=cadence,
                            now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)


@pytest.mark.parametrize("delay", [7, 6.222003, 71.9])
def test_known_release_waits_exactly_then_only_one_scan(tmp_path, delay):
    clock = Clock(); wakes = pending(tmp_path, clock.wall + delay); env = Environment(clock.wall + delay)
    calls = []
    out = run(wakes, clock, env, lambda cap: calls.append((clock.wall, cap)) or {"ok": True})
    assert calls == [(10000 + delay, 5)]
    assert out["scan_wake_resumed"] and wakes.read() is None
    assert run(wakes, clock, env, lambda _cap: pytest.fail("duplicate scan")) is None


def test_long_wait_survives_restart_without_sleep_or_charge(tmp_path):
    clock = Clock(); wakes = pending(tmp_path, 13600); env = Environment(13600)
    assert run(wakes, clock, env, lambda _cap: pytest.fail("early scan")) is None
    assert clock.elapsed == 0 and wakes.read()["wake_at"] == 13600
    restarted = ScanWakeStore(wakes.path)
    clock.wall = 13593
    out = run(restarted, clock, env, lambda cap: {"ok": True, "cap": cap})
    assert out["cap"] == 5 and clock.wall == 13600


def test_configuration_change_extends_or_shortens_without_old_deadline_bypass(tmp_path):
    clock = Clock(); wakes = pending(tmp_path); env = Environment(10007)
    def extend():
        env.release, env.revision = 13600, "stricter"
    clock.after_sleep = extend
    assert run(wakes, clock, env, lambda _cap: pytest.fail("stale admission")) is None
    assert clock.elapsed == 1 and wakes.read()["wake_at"] == 13600
    env.release, env.limit, env.revision = clock.wall, 2, "relaxed"
    out = run(wakes, clock, env, lambda cap: {"ok": True, "cap": cap})
    assert out["cap"] == 2


@pytest.mark.parametrize("blocked", ["disabled", "unknown", "maintenance", "bad_config"])
def test_changed_safety_gates_stop_without_scan_or_clearing_history(tmp_path, blocked):
    from video_processing.core.maintenance import MaintenanceDenied
    clock = Clock(); wakes = pending(tmp_path); env = Environment(10007)
    def change():
        if blocked == "disabled": env.enabled = False
        elif blocked == "unknown": env.unknown_block = True
        else:
            def deny(_now):
                raise MaintenanceDenied() if blocked == "maintenance" else ValueError("bad configuration")
            env.inspect = deny
    clock.after_sleep = change
    if blocked in {"maintenance", "bad_config"}:
        with pytest.raises((MaintenanceDenied, ValueError)):
            run(wakes, clock, env, lambda _cap: pytest.fail("unsafe scan"))
    else:
        assert not run(wakes, clock, env, lambda _cap: pytest.fail("unsafe scan"))["status"].startswith("COMPLETED")
    assert wakes.read() and clock.elapsed == 1


def test_one_lease_and_cas_keep_concurrent_replacement(tmp_path):
    clock = Clock(); wakes = pending(tmp_path, 10000); env = Environment(10000)
    def execute(_cap):
        second = run(ScanWakeStore(wakes.path), clock, env, lambda _n: pytest.fail("concurrent scan"))
        assert second["status"] == "SCAN_WAKE_ALREADY_RUNNING"
        wakes.defer(SCOPE, until=13600, scan_limit=5, codes=["OPERATION_INTERVAL"])
        return {"ok": True}
    run(wakes, clock, env, execute)
    assert wakes.read()["wake_at"] == 13600


def test_browser_busy_keeps_wait_without_consuming_scan(tmp_path):
    clock = Clock(); wakes = pending(tmp_path, 10000); env = Environment(10000)
    def busy(_cap):
        wakes.defer(SCOPE, until=10300, scan_limit=5, codes=["RESOURCE_OR_ADMISSION_WAIT"])
        return {"ok": True, "scan_deferred": "browser busy"}
    assert run(wakes, clock, env, busy)["scan_deferred"]
    assert run(wakes, clock, env, lambda _cap: pytest.fail("resource wait skipped")) is None
    assert wakes.read()["wake_at"] == 10300 and clock.elapsed == 0


def test_window_closed_and_cross_midnight():
    ts = lambda text: datetime.fromisoformat(text).timestamp()
    now = ts("2026-10-25T00:00:00+08:00")
    assert window_open_at(now, "05:30", "21:00") == ts("2026-10-25T05:30:00+08:00")
    assert window_open_at(now, "00:00", "24:00") == now
    assert window_open_at(now, "23:00", "02:00") == now


def test_invalid_record_and_other_account_never_execute(tmp_path):
    clock = Clock(); wakes = pending(tmp_path); env = Environment(10000)
    assert resume_scan_wait(wakes, "0" * 64, env, lambda _cap: pytest.fail("wrong account"), cadence=72) is None
    old = wakes.path.read_bytes()
    with pytest.raises(ValueError): wakes.defer(SCOPE, until=float("nan"), scan_limit=5)
    assert wakes.path.read_bytes() == old
    wakes.path.write_text('{"schema":1}')
    with pytest.raises(ValueError): run(wakes, clock, env, lambda _cap: pytest.fail("invalid state"))


def test_wait_has_zero_debits_then_one_native_batch_and_preserves_failed_watermark(active, tmp_path):
    from video_processing.core.wechat_account_schedule import evaluate, admission
    from video_processing.db.database import PipelineDB
    clock = Clock(); row = state([event(6407, "comment_scan")]); old = copy.deepcopy(row)
    wakes = pending(tmp_path); env = Environment(10007)
    env.inspect = lambda now: {"enabled": True, "window_until": now, "scan_limit": 5,
                              "revision": "native", "admission": evaluate(row, now, "评论扫描", account_only=True)}
    db = PipelineDB(db_path=str(tmp_path / "pipeline.db"))
    def execute(cap):
        assert row == old  # 7秒等待及反复预检均不登记访问。
        assert admission(row, clock.wall, "评论扫描", "batch", consume=True) == ""
        for n in range(cap):
            db.record_comment_scan_state(account_key="a", platform_post_id="export/synthetic" + str(n),
                top_level_status="INCOMPLETE", complete=False, last_error="synthetic read failure")
        return {"ok": True}
    run(wakes, clock, env, execute)
    assert len(row["schedule"]["sessions"]) == 2
    assert db.get_comment_scan_state("a", "export/synthetic0")["last_complete_scan_at"] is None
    assert not evaluate(row, clock.wall, "评论扫描", account_only=True)["allowed"]


def test_real_cli_resumes_only_scan_not_send_reconcile_or_draft(configured, cli, monkeypatch, tmp_path, capsys):
    from config.settings import settings
    from tests.unit.test_secondary_reply_m35_runner import _seed_published_post, TEST_POST, TEST_ACCT, TEST_FINDER
    from video_processing.interaction.secondary_reply_approval import FakeApprovalTransport
    from video_processing.interaction.secondary_reply_fake_platform import FakeSecondaryReplyPlatform
    from video_processing.interaction import secondary_reply_scan_wake as wake
    from video_processing.core import reply_send_schedule
    first, db = configured
    domains = first.domains(); domains['interaction_controls']['automatic_replies_enabled'] = True
    save(domains, first.revision, 'scan_wake_cli_test_000001')
    monkeypatch.setattr(settings, 'wechat_reply_account_key', TEST_ACCT)
    monkeypatch.setattr(settings, 'wechat_reply_author_finder_id', TEST_FINDER)
    monkeypatch.setattr(settings, 'enable_wechat_secondary_reply_live_submission', True)
    _seed_published_post(db)
    class Platform(FakeSecondaryReplyPlatform):
        adapter = SimpleNamespace(state_path=tmp_path/'state.json')
        reads = 0
        def discover_comments(self, **kwargs):
            self.reads += 1
            return {'ok': True, 'payload': {'errCode': 0, 'data': {'comment': [], 'downContinueFlag': 0}}}
        def send_reply(self, **kwargs):
            pytest.fail('resume must not send')
    platform = Platform(); env = Environment(0)
    monkeypatch.setattr(wake, 'NativeScanWakeEnvironment', lambda _p: env)
    monkeypatch.setattr(reply_send_schedule, 'verified_cadence', lambda: 72)
    wakes = wake.store(); wakes.defer(scope_key(TEST_ACCT, TEST_FINDER), until=0, scan_limit=5)
    out = cli.main(['tick', '--db-path', str(tmp_path/'pipeline.db'), '--max-reconcile', '0',
        '--max-submit', '1', '--scan-posts', '0', '--max-drafts', '0'],
        platform_factory=lambda _args: platform, approval_transport=FakeApprovalTransport())
    import json
    report = json.loads(capsys.readouterr().out)
    assert out == 0 and report['scan_wake_resumed']
    assert len(report['scanned_posts']) == platform.reads == 1
    assert report['submitted'] == report['reconciled'] == report['drafted'] == []
    assert wakes.read() is None
