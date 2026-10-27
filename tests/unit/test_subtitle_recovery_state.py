"""局部字幕恢复账本的跨续跑预算、独占与安全状态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-27 | Codex | 覆盖来源身份、请求预扣、累计期限、崩溃窗口和逐段失败不因重启重置。 |
"""

import json

import pytest

from video_processing.utils import subtitle_recovery_state as state
from video_processing.utils.codex_text_provider import CodexTextError


def _state(tmp_path, **kwargs):
    arguments = dict(texts=["Oil is $115."], context="context", model="gpt-5.6-luna", effort="medium",
                     batch_size=5, max_attempts=2, max_requests=2, total_timeout=600, request_timeout=120)
    arguments.update(kwargs)
    return state.SubtitleRecoveryState(tmp_path, **arguments)


def test_plan_identity_is_source_specific_and_budget_cannot_reset(tmp_path):
    first = _state(tmp_path)
    with first as ledger:
        ledger.before_execute()
    with _state(tmp_path, max_requests=99, total_timeout=900) as ledger:
        assert ledger.path == first.path
        assert ledger.data["requests_used"] == 1 and ledger.data["max_requests"] == 2
        assert ledger.data["total_timeout"] == 600
        ledger.before_execute()
        with pytest.raises(CodexTextError, match="request_budget_exhausted"):
            ledger.before_execute()
    assert _state(tmp_path, context="changed").identity != first.identity
    assert _state(tmp_path, texts=["changed"]).identity != first.identity
    assert _state(tmp_path, batch_size=1).identity != first.identity


def test_plan_lock_prevents_lost_updates(tmp_path):
    with _state(tmp_path):
        with pytest.raises(CodexTextError, match="recovery_busy"):
            with _state(tmp_path):
                pytest.fail("concurrent plan admitted")
    with _state(tmp_path) as ledger:
        assert ledger.data["requests_used"] == 0


def test_elapsed_accumulates_without_charging_normal_offline_wait(tmp_path, monkeypatch):
    clock = {"mono": 0.0, "wall": 1000.0}
    monkeypatch.setattr(state.time, "monotonic", lambda: clock["mono"])
    monkeypatch.setattr(state.time, "time", lambda: clock["wall"])
    with _state(tmp_path, total_timeout=10) as ledger:
        clock["mono"] = 7.0
        assert ledger.remaining_seconds() == 3
    clock.update(mono=100.0, wall=100000.0)
    with _state(tmp_path, total_timeout=100) as ledger:
        assert ledger.remaining_seconds() == 3
        clock["mono"] = 104.0
        with pytest.raises(CodexTextError, match="total_timeout"):
            ledger.before_execute()


def test_unclean_exit_charges_at_most_one_request_window(tmp_path, monkeypatch):
    clock = {"mono": 0.0, "wall": 1000.0}
    monkeypatch.setattr(state.time, "monotonic", lambda: clock["mono"])
    monkeypatch.setattr(state.time, "time", lambda: clock["wall"])
    plan = _state(tmp_path)
    with plan:
        pass
    data = json.loads(plan.path.read_text())
    data["active_window"] = {"started_at": 1000, "allowance_seconds": 120}
    plan.path.write_text(json.dumps(data))
    clock.update(mono=10.0, wall=100000.0)
    with _state(tmp_path) as ledger:
        assert ledger.data["elapsed_seconds"] == 120 and ledger.remaining_seconds() == 480


def test_split_and_singleton_failures_survive_restart_without_raw_text(tmp_path):
    details = [{"segment_number": 80, "source_id": 79, "code": "NUMBER_AMOUNT_MISSING",
                "source_signal": "$115", "translation_signal": "amount_not_in_segment", "prompt": "PRIVATE"}]
    error = CodexTextError("subtitle_quality_NUMBER_AMOUNT_MISSING", quality_details=details)
    with _state(tmp_path, max_requests=20) as ledger:
        ledger.mark_split(75, 5, error)
        ledger.before_execute(79)
        ledger.record_failure(error, 79)
        ledger.before_execute(79)
        ledger.record_failure(error, 79)
    with _state(tmp_path, max_requests=20) as ledger:
        assert ledger.split(75, 5)
        assert ledger.previous_failure(79)["code"] == error.code
        with pytest.raises(CodexTextError, match="subtitle_recovery_exhausted") as rejected:
            ledger.before_execute(79)
        assert rejected.value.quality_details[0]["source_id"] == 79
        assert ledger.data["requests_used"] == 2
    assert "PRIVATE" not in ledger.path.read_text()


@pytest.mark.parametrize("value", ["broken", "{}", '{"elapsed_seconds": NaN}'])
def test_invalid_state_is_not_silently_reset(tmp_path, value):
    plan = _state(tmp_path)
    plan.directory.mkdir()
    plan.path.write_text(value)
    with pytest.raises(CodexTextError, match="recovery_state_invalid"):
        with _state(tmp_path):
            pytest.fail("invalid state admitted")
    assert plan.path.read_text() == value


def test_network_attempt_exhaustion_never_becomes_quality_or_audio_evidence(tmp_path):
    with _state(tmp_path, max_requests=20) as ledger:
        for _ in range(2):
            ledger.before_execute(0)
            ledger.record_failure(CodexTextError("unavailable", 9999999999), 0)
    with _state(tmp_path, max_requests=20) as ledger:
        with pytest.raises(CodexTextError, match="request_budget_exhausted") as denied:
            ledger.before_execute(0)
        assert denied.value.quality_details == [] and denied.value.retry_at == 9999999999
        assert ledger.previous_failure(0)["code"] == "unavailable"
