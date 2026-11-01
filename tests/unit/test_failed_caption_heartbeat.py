"""失败后的残留心跳不遮蔽修复入口；实际进程和内核锁仍优先。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 覆盖7031/7059真实失败与遗留心跳、实际活动、观测未知。 |
"""
from dataclasses import replace
import pytest
from video_processing.funnel_diagnosis import TaskUnitFacts, RuntimeEnvironmentFacts, DiagnosisThresholds, diagnose_task_unit
from video_processing.funnel_diagnosis.rules import is_task_actively_running


@pytest.mark.parametrize('code,action', [('total_timeout','repair_subtitle'), ('reviewed_timeline','retry_task')])
@pytest.mark.parametrize('age', [0, 120, 899])
def test_failed_task_with_residual_caption_heartbeat_exposes_real_failure(code, action, age):
    now=1800000000.
    error='SUBTITLE_NEEDS_REPAIR: 字幕翻译需修复后恢复: total_timeout' if code=='total_timeout' else '具名故障版式对白或时间轴变化，需要重新复核'
    task=TaskUnitFacts(video_id=7059, youtube_id='w21d64pB9jk', status='FAILED', error_msg=error, failed_epoch=now-20, updated_epoch=now-20, caption_progress_updated_epoch=now-age, caption_stage='TRANSLATING', subtitle_recovery={'state':'NEEDS_REPAIR'} if code=='total_timeout' else {})
    env=RuntimeEnvironmentFacts(now_epoch=now,now_bj_iso="fixture")
    assert not is_task_actively_running(task,env,DiagnosisThresholds())
    diag=diagnose_task_unit(task,env)
    assert diag.unresolved and diag.is_system_fault and not diag.is_recovered
    assert diag.handling_state!='RUNNING' and diag.action_kind==action


@pytest.mark.parametrize('evidence', [{'process_alive':True}, {'has_active_task_lock':True}])
def test_real_activity_still_protects_failed_task_from_concurrent_retry(evidence):
    task=TaskUnitFacts(video_id=7031, youtube_id='CatuGloDkTQ', status='FAILED', error_msg='technical failure', caption_progress_updated_epoch=1799999990., **evidence)
    env=RuntimeEnvironmentFacts(now_epoch=1800000000.,now_bj_iso="fixture")
    assert is_task_actively_running(task,env,DiagnosisThresholds())
    diag=diagnose_task_unit(task,env)
    assert diag.handling_state=='RUNNING' and diag.action_kind=='none' and diag.unresolved


def test_fresh_heartbeat_for_active_caption_and_unknown_observation_remain_protected():
    env=RuntimeEnvironmentFacts(now_epoch=1800000000.,now_bj_iso="fixture")
    task=TaskUnitFacts(video_id=1,youtube_id='x',status='TRANSCRIBING',caption_progress_updated_epoch=1799999990.)
    assert is_task_actively_running(task,env,DiagnosisThresholds())
    task=replace(task,status='FAILED',runtime_observation_available=False,error_msg='technical failure')
    diag=diagnose_task_unit(task,replace(env,runtime_available=False))
    assert diag.action_kind=='none' and diag.cause_code=='RUNTIME_OBSERVATION_UNAVAILABLE'
