"""真实配置文件/维护状态/部署日志验证；不调用 launchd 或真实 API。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-14 | Codex | adopt 顺序、重启、漂移及失败闭锁的真实文件验收 |
"""
from copy import deepcopy
from datetime import datetime, timezone
import time
import pytest
from config.settings import Settings, settings
from config.keyword_rollout import phase_values, transition
from video_processing.core.deployment import DeploymentDenied, digest, write_json, read_json, STEPS
from video_processing.core.maintenance import gate
from video_processing.core.maintenance_runtime import protection_snapshot
from video_processing.core.keyword_rollout import KeywordTransition, verify_loaded, values
from tests.unit.test_keyword_rollout_contract import evidence
from tests.topic_candidate_fixtures import tracker
from tests.unit.test_topic_candidates_api import topic_client


@pytest.fixture
def rollout(tmp_path, monkeypatch):
    for key, value in phase_values("OFF").items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(settings, "topic_rollout_path", tmp_path / "keyword-rollout.json")
    monkeypatch.setattr(settings, "_topic_rollout_record", None)
    monkeypatch.setattr(settings, "_topic_rollout_error", False)
    monkeypatch.setattr(settings, "enable_market_hours_guard", True)
    directory = tmp_path / "deployment"
    proof = evidence(); proof["observed_at"] = time.time()
    plan = dict(schema=1, id="isolated-stage", root=str(settings.project_root),
                keyword_transition=transition(values(settings), "TRIAL", proof, time.time()),
                protections=protection_snapshot(), keyword_profile_before=settings.topic_rollout_snapshot())
    write_json(directory / "plan.json", plan)
    journal = dict(schema=1, plan=digest(plan), done=list(STEPS[:4]), pending="adopt", state="RUNNING")
    write_json(directory / "journal.json", journal)
    gate().enter("隔离阶段配置验收")
    return KeywordTransition(plan, directory, settings), plan, directory


def test_real_adoption_restart_and_completion_required(rollout):
    adapter, plan, directory = rollout
    adapter.protections(protection_snapshot())
    adapter.apply()
    adapter.protections(protection_snapshot(), after=True)
    assert values(settings) == phase_values("TRIAL", "gen-lang-client-0993011647")
    with pytest.raises(DeploymentDenied, match="KEYWORD_DEPLOYMENT_INCOMPLETE"):
        verify_loaded(settings, complete=True)
    restarted = Settings(_env_file=None, topic_rollout_path=settings.topic_rollout_path,
                         **{k: v for k, v in protection_snapshot().items() if k not in phase_values("OFF")})
    assert values(restarted) == values(settings)
    assert verify_loaded(restarted)
    journal = read_json(directory / "journal.json")
    journal.update(done=list(STEPS), pending=None, state="COMPLETE")
    write_json(directory / "journal.json", journal)
    assert verify_loaded(restarted, complete=True)


def test_start_failure_stays_closed_but_maintenance_proof_remains_valid(rollout):
    adapter, plan, directory = rollout
    adapter.apply()
    journal = read_json(directory / "journal.json")
    journal.update(done=list(STEPS[:5]), pending="start", state="FAILED")
    write_json(directory / "journal.json", journal)
    assert verify_loaded(settings)
    with pytest.raises(DeploymentDenied, match="KEYWORD_DEPLOYMENT_INCOMPLETE"):
        verify_loaded(settings, complete=True)
    assert gate().status()["state"] == "MAINTENANCE"


@pytest.mark.parametrize("change", ["file", "plan", "journal", "effective", "protection", "missing"])
def test_changed_configuration_or_receipt_never_accepted(rollout, change, monkeypatch):
    adapter, plan, directory = rollout
    adapter.apply()
    if change == "file":
        record = read_json(settings.topic_rollout_path); record["deployment_id"] = "changed"
        write_json(settings.topic_rollout_path, record)
    elif change == "plan":
        changed = deepcopy(plan); changed["id"] = "changed"
        write_json(directory / "plan.json", changed)
    elif change == "journal":
        journal = read_json(directory / "journal.json"); journal["plan"] = "changed"
        write_json(directory / "journal.json", journal)
    elif change == "effective":
        monkeypatch.setattr(settings, "topic_search_daily_limit", 20)
    elif change == "protection":
        monkeypatch.setattr(settings, "wechat_publishing_paused", not settings.wechat_publishing_paused)
    else:
        settings.topic_rollout_path.unlink()
    with pytest.raises(DeploymentDenied):
        verify_loaded(settings)


def test_missing_or_corrupt_profile_reload_disables_capabilities(rollout):
    adapter, plan, directory = rollout
    adapter.apply()
    settings.topic_rollout_path.unlink()
    settings.reload_topic_rollout()
    assert values(settings) == phase_values("OFF")
    with pytest.raises(DeploymentDenied, match="KEYWORD_PROFILE_INVALID"):
        verify_loaded(settings)
    settings.topic_rollout_path.write_text("{invalid")
    settings.reload_topic_rollout()
    assert values(settings) == phase_values("OFF")


@pytest.mark.parametrize("change", ["running", "wrong_step", "new_file"])
def test_write_requires_maintenance_order_and_original_file(rollout, change):
    adapter, plan, directory = rollout
    if change == "running":
        gate().resume(gate().status()["version"], validated=True)
    elif change == "wrong_step":
        journal = read_json(directory / "journal.json"); journal.update(done=[], pending="baseline")
        write_json(directory / "journal.json", journal)
    else:
        settings.topic_rollout_path.write_text('{}')
    with pytest.raises(DeploymentDenied):
        adapter.apply()
    assert values(settings) == phase_values("OFF")


def test_stage_profile_does_not_replace_source_proof_or_persistent_off(rollout, tmp_path, monkeypatch):
    from tests.unit.test_maintenance_entries import proof, prepare_empty_output
    from video_processing.core.maintenance_runtime import inspection
    adapter, plan, directory = rollout
    db = prepare_empty_output(tmp_path / "output", monkeypatch)
    adapter.apply()
    source = proof(tmp_path, gate())
    denied = inspection(gate(), evidence=source, process_pids=set())
    assert {"code": "KEYWORD_PROFILE_PROOF_MISMATCH"} in denied["unknown"]
    contents = read_json(source); contents["keyword_profile"] = settings.topic_rollout_snapshot()
    write_json(source, contents)
    assert inspection(gate(), evidence=source, process_pids=set())["safe"]
    db.topic_set_mode("DISCOVERY_ONLY", db.topic_control()["version"], "isolated", datetime.now(timezone.utc))
    assert not inspection(gate(), evidence=source, process_pids=set())["safe"]


def test_running_state_cannot_search_before_deployment_complete(tracker, rollout):
    from video_processing.core.topic_candidates import TopicError
    adapter, plan, directory = rollout
    adapter.apply()
    tracker.config = settings
    gate().resume(gate().status()["version"], validated=True)
    with pytest.raises(TopicError) as caught:
        tracker._ready()
    assert caught.value.code == "ROLLOUT_UNVERIFIED"
    assert tracker.adapter.calls == []


def test_plain_environment_flags_do_not_replace_stage_adoption(tracker, rollout, monkeypatch):
    from video_processing.core.topic_candidates import TopicError
    monkeypatch.setattr(settings, 'topic_search_enabled', True)
    tracker.config = settings
    gate().resume(gate().status()['version'], validated=True)
    with pytest.raises(TopicError) as caught:
        tracker._ready()
    assert caught.value.code == 'ROLLOUT_UNVERIFIED'
    assert tracker.adapter.calls == []


def test_native_host_readback_checks_loaded_config_via_real_routes(topic_client, rollout, monkeypatch):
    from contextlib import nullcontext
    from video_processing.core import deployment_host as host
    client, tracker = topic_client
    adapter, plan, directory = rollout
    adapter.apply()
    tracker.config = settings
    instance = host.HostDeployment.__new__(host.HostDeployment)
    instance.keyword = adapter
    monkeypatch.setattr(host.httpx, "Client", lambda **kwargs: nullcontext(client))
    runtime = instance.web_readback(maintenance="MAINTENANCE")
    assert runtime["configuration"] == values(settings)
    assert runtime["configuration"]["topic_trial_mode"] is True
    assert runtime["search_open"] is False and runtime["can_enable"] is False
    assert runtime["control"]["mode"] == "OFF"


def test_explicit_off_transition_retains_previous_profile_for_recovery(rollout):
    adapter, plan, directory = rollout
    adapter.apply()
    previous = deepcopy(settings._topic_rollout_record)
    next_dir = directory.parent / "close-stage"
    next_plan = dict(schema=1, id="isolated-close", root=str(settings.project_root),
        keyword_transition=transition(values(settings), "OFF", {}, time.time()),
        protections=protection_snapshot(), keyword_profile_before=settings.topic_rollout_snapshot())
    write_json(next_dir / "plan.json", next_plan)
    write_json(next_dir / "journal.json", dict(schema=1, plan=digest(next_plan),
        done=list(STEPS[:4]), pending="adopt", state="RUNNING"))
    closer = KeywordTransition(next_plan, next_dir, settings)
    closer.apply()
    assert values(settings) == phase_values("OFF")
    assert read_json(next_dir / "keyword-profile-before.json") == previous
    assert verify_loaded(settings)
