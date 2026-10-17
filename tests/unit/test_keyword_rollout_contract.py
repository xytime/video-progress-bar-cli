"""阶段配置合同隔离验收；不连接 Cloud、不读取凭据、不写宿主配置。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-15 | Codex | 新旧合同兼容、长期精确额度与回退 |
| 1.0.0 | 2026-10-14 | Codex | 阶段跳跃、过期、类型、额度、项目及保护字段漂移反例 |
"""
from copy import deepcopy
import pytest
from config.keyword_rollout import (FIELDS, PHASES, RolloutDenied, phase_values, identify,
                                    transition, validate_transition, expected_protections)

NOW = 1791914000
PROJECT = "gen-lang-client-0993011647"


def evidence():
    return dict(project=PROJECT, credential_resource_id="286cb0f6-4231-4ca2-831f-1e4646829b55",
        binding_result="CONFIG_MATCH_RESTART_REQUIRED",
        binding_basis="user_local_file_and_loaded_launchd_comparison", external_shared_callers=[],
        local_callers=["scripts/monitor_channels.py", "scripts/rescore_refresh.py",
            "src/video_processing/english_world/research.py", "src/video_processing/utils/topic_search.py"],
        observed_at=NOW - 60, search_remaining=100, general_remaining=9800,
        trial_job_ids=["a" * 32], scheduled_job_ids=["b" * 32], refresh_job_ids=["c" * 32])


@pytest.mark.parametrize("index", range(4))
def test_adjacent_phase_has_fixed_capabilities(index):
    before = phase_values(PHASES[index], PROJECT if index else "")
    plan = transition(before, PHASES[index + 1], evidence(), NOW)
    assert validate_transition(plan, NOW) == phase_values(PHASES[index + 1], PROJECT)
    assert identify(plan["after"]) == PHASES[index + 1]
    assert plan["after"]["topic_admission_total_limit"] == 1


@pytest.mark.parametrize("source", PHASES[1:])
def test_off_recovery_needs_no_expired_external_evidence(source):
    plan = transition(phase_values(source, PROJECT), "OFF", {}, NOW)
    assert validate_transition(plan, NOW) == phase_values("OFF")


@pytest.mark.parametrize("source,target", [("OFF", "MANUAL"), ("TRIAL", "ADMISSION"),
    ("MANUAL", "TRIAL"), ("SCHEDULED", "TRIAL"), ("OFF", "OFF"), ("ADMISSION", "ADMISSION")])
def test_phase_jumps_and_replaying_same_phase_are_denied(source, target):
    with pytest.raises(RolloutDenied, match="KEYWORD_PHASE_JUMP"):
        transition(phase_values(source, PROJECT if source != "OFF" else ""), target, evidence(), NOW)


@pytest.mark.parametrize("field,value,code", [
    ("binding_result", "probably_matches", "KEYWORD_BINDING_UNVERIFIED"),
    ("binding_basis", "similar_name", "KEYWORD_BINDING_UNVERIFIED"),
    ("credential_resource_id", "unknown", "KEYWORD_BINDING_MISMATCH"),
    ("external_shared_callers", ["unknown-host"], "KEYWORD_SHARED_CALLERS_UNSUPPORTED"),
    ("local_callers", [], "KEYWORD_LOCAL_CALLERS_UNVERIFIED"),
    ("observed_at", NOW - 3601, "KEYWORD_QUOTA_EVIDENCE_EXPIRED"),
    ("observed_at", NOW + 1, "KEYWORD_QUOTA_EVIDENCE_EXPIRED"),
    ("observed_at", float("nan"), "KEYWORD_QUOTA_EVIDENCE_EXPIRED"),
    ("search_remaining", True, "KEYWORD_QUOTA_INSUFFICIENT"),
    ("search_remaining", 2, "KEYWORD_QUOTA_INSUFFICIENT"),
    ("general_remaining", 5, "KEYWORD_QUOTA_INSUFFICIENT"),
    ("trial_job_ids", ["a" * 32] * 2, "KEYWORD_JOB_EVIDENCE_INVALID"),
])
def test_incomplete_facts_fail_closed(field, value, code):
    proof = evidence(); proof[field] = value
    with pytest.raises(RolloutDenied, match=code):
        transition(phase_values("OFF"), "TRIAL", proof, NOW)


def test_provided_secrets_or_unknown_fields_are_not_accepted_or_echoed():
    proof = evidence(); proof["key"] = "synthetic-sensitive-value"
    with pytest.raises(RolloutDenied) as caught:
        transition(phase_values("OFF"), "TRIAL", proof, NOW)
    assert str(caught.value) == "KEYWORD_EVIDENCE_FIELDS_INVALID"


@pytest.mark.parametrize("phase,field", [("MANUAL", "trial_job_ids"),
    ("ADMISSION", "scheduled_job_ids"), ("ADMISSION", "refresh_job_ids")])
def test_later_phases_require_runtime_evidence_references(phase, field):
    proof = evidence(); proof[field] = []
    source = PHASES[PHASES.index(phase) - 1]
    with pytest.raises(RolloutDenied, match="EVIDENCE_REQUIRED"):
        transition(phase_values(source, PROJECT), phase, proof, NOW)


def test_project_change_cannot_reuse_previous_phase():
    proof = evidence(); proof["project"] = "another-project"
    with pytest.raises(RolloutDenied, match="KEYWORD_PROJECT_CHANGED"):
        transition(phase_values("TRIAL", PROJECT), "MANUAL", proof, NOW)


def test_plan_expiry_and_tampering_are_distinct():
    plan = transition(phase_values("OFF"), "TRIAL", evidence(), NOW)
    with pytest.raises(RolloutDenied, match="KEYWORD_PLAN_EXPIRED"):
        validate_transition(plan, NOW + 1801)
    assert validate_transition(plan, NOW + 86400, fresh=False) == plan["after"]
    altered = deepcopy(plan); altered["after"]["topic_search_daily_limit"] = 20
    with pytest.raises(RolloutDenied, match="KEYWORD_TRANSITION_DRIFT"):
        validate_transition(altered, NOW)


def test_preserves_every_unrelated_protection_and_detaches_inputs():
    before = phase_values("OFF")
    protections = dict(before, enable_market_hours_guard=True, wechat_publishing_paused=True,
                       unrelated={"future_guard": True})
    plan = transition(before, "TRIAL", evidence(), NOW)
    expected = expected_protections(protections, plan, NOW)
    assert {k: v for k, v in expected.items() if k not in FIELDS} == {
        k: v for k, v in protections.items() if k not in FIELDS}
    expected["unrelated"]["future_guard"] = False
    assert protections["unrelated"]["future_guard"] is True
    protections["topic_trial_mode"] = True
    with pytest.raises(RolloutDenied, match="KEYWORD_PROTECTION_BASELINE_MISMATCH"):
        expected_protections(protections, plan, NOW)


@pytest.mark.parametrize("field,value", [("topic_search_enabled", 0),
    ("topic_search_daily_limit", True), ("topic_admission_total_limit", 2),
    ("topic_search_daily_limit", 21)])
def test_unknown_configuration_is_not_normalized_into_approval(field, value):
    config = phase_values("OFF"); config[field] = value
    with pytest.raises(RolloutDenied, match="KEYWORD_CONFIGURATION_UNKNOWN"):
        identify(config)


def test_long_term_is_versioned_and_can_rollback_without_enlarging_other_flags():
    before=phase_values('ADMISSION',PROJECT)
    plan=transition(before,'LONG_TERM',evidence(),NOW)
    assert plan['schema']==2 and identify(validate_transition(plan,NOW))=='LONG_TERM'
    assert {k for k in FIELDS if plan['after'][k]!=before[k]}=={'topic_admission_total_limit'}
    rollback=transition(plan['after'],'ADMISSION',evidence(),NOW)
    assert rollback['schema']==2 and validate_transition(rollback,NOW)==before
    legacy=transition(phase_values('SCHEDULED',PROJECT),'ADMISSION',evidence(),NOW)
    assert legacy['schema']==1
    altered=deepcopy(plan);altered['schema']=1
    with pytest.raises(RolloutDenied,match='DRIFT'):validate_transition(altered,NOW)


@pytest.mark.parametrize('limit',[0,2,3,5,7,True])
def test_long_term_does_not_accept_unapproved_limits(limit):
    config=phase_values('LONG_TERM',PROJECT);config['topic_admission_total_limit']=limit
    with pytest.raises(RolloutDenied,match='CONFIGURATION_UNKNOWN'):identify(config)
