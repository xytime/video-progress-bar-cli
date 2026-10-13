"""关键词受控阶段的非秘密配置合同；纯函数，不读取凭据或执行部署。

依赖：部署/维护/业务层 → 本模块 → 标准库。settings 可引用此模块，禁止反向导入。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-14 | Codex | 固定阶段、证据时效、保护字段保留及转换身份 |
"""
from copy import deepcopy
import hashlib
import json
import math
import re


PHASES = ("OFF", "TRIAL", "MANUAL", "SCHEDULED", "ADMISSION")
PROJECT = re.compile(r"[a-z][a-z0-9-]{4,61}[a-z0-9]\Z")
RESOURCE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
FIELDS = frozenset(("topic_search_enabled", "topic_trial_mode", "topic_scheduler_enabled",
                    "topic_admission_enabled", "topic_quota_verified", "topic_quota_project",
                    "topic_search_daily_limit", "topic_general_daily_limit", "topic_admission_total_limit"))
PROTECTION_FIELDS = ("enable_public_publish_windows", "market_guard_policy", "enable_market_hours_guard",
    "wechat_publishing_paused", "enable_douyin_browser_publishing", "enable_kuaishou_browser_publishing",
    "enable_wechat_comment_interaction", "wechat_keepalive_enabled", *sorted(FIELDS))


def protection_values(config):
    return {name: getattr(config, name) for name in PROTECTION_FIELDS}


class RolloutDenied(ValueError):
    """错误只返回固定代码，不将传入配置或任意文件内容放入异常。"""


def require(condition, code):
    if not condition:
        raise RolloutDenied(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def phase_values(phase, project=""):
    require(phase in PHASES, "KEYWORD_PHASE_UNKNOWN")
    require(isinstance(project, str) and (not project if phase == "OFF" else PROJECT.fullmatch(project)),
            "KEYWORD_PROJECT_INVALID")
    opened = phase != "OFF"
    return dict(topic_search_enabled=opened, topic_trial_mode=phase == "TRIAL",
                topic_scheduler_enabled=phase in ("SCHEDULED", "ADMISSION"),
                topic_admission_enabled=phase == "ADMISSION", topic_quota_verified=opened,
                topic_quota_project=project, topic_search_daily_limit=3 if phase == "TRIAL" else 20,
                topic_general_daily_limit=6 if phase == "TRIAL" else 40, topic_admission_total_limit=1)


def identify(values):
    """严格类型和精确组合；bool 与 int 不互换，不接受任意更宽额度。"""
    require(isinstance(values, dict) and set(values) == FIELDS, "KEYWORD_FIELDS_INVALID")
    for phase in PHASES:
        try:
            expected = phase_values(phase, values["topic_quota_project"])
        except RolloutDenied:
            continue
        if all(type(values[k]) is type(v) and values[k] == v for k, v in expected.items()):
            return phase
    raise RolloutDenied("KEYWORD_CONFIGURATION_UNKNOWN")


def _recent(at, now, seconds):
    return (type(at) in (int, float) and math.isfinite(at) and
            type(now) in (int, float) and math.isfinite(now) and 0 <= now - at <= seconds)


def validate_evidence(evidence, project, target, now):
    """核实记录属于操作者提供的事实；不把 True 当成 API 查询或运行证据。"""
    keys = {"project", "credential_resource_id", "binding_result", "binding_basis",
            "external_shared_callers", "local_callers", "observed_at", "search_remaining",
            "general_remaining", "trial_job_ids", "scheduled_job_ids", "refresh_job_ids"}
    require(isinstance(evidence, dict) and set(evidence) == keys, "KEYWORD_EVIDENCE_FIELDS_INVALID")
    require(evidence["project"] == project and isinstance(evidence["credential_resource_id"], str)
            and RESOURCE.fullmatch(evidence["credential_resource_id"]), "KEYWORD_BINDING_MISMATCH")
    require(evidence["binding_result"] == "CONFIG_MATCH_RESTART_REQUIRED"
            and evidence["binding_basis"] == "user_local_file_and_loaded_launchd_comparison",
            "KEYWORD_BINDING_UNVERIFIED")
    require(evidence["external_shared_callers"] == [] and type(evidence["external_shared_callers"]) is list,
            "KEYWORD_SHARED_CALLERS_UNSUPPORTED")
    callers = ["scripts/monitor_channels.py", "scripts/rescore_refresh.py",
               "src/video_processing/english_world/research.py", "src/video_processing/utils/topic_search.py"]
    require(evidence["local_callers"] == callers, "KEYWORD_LOCAL_CALLERS_UNVERIFIED")
    require(_recent(evidence["observed_at"], now, 3600), "KEYWORD_QUOTA_EVIDENCE_EXPIRED")
    for name, minimum in (("search_remaining", 3 if target == "TRIAL" else 20),
                          ("general_remaining", 6 if target == "TRIAL" else 40)):
        require(type(evidence[name]) is int and evidence[name] >= minimum, "KEYWORD_QUOTA_INSUFFICIENT")
    for name in ("trial_job_ids", "scheduled_job_ids", "refresh_job_ids"):
        ids = evidence[name]
        require(type(ids) is list and len(ids) <= 3 and len(set(str(v) for v in ids)) == len(ids)
                and all(type(v) is str and re.fullmatch(r"[a-f0-9]{32}", v) for v in ids),
                "KEYWORD_JOB_EVIDENCE_INVALID")
    if target in ("MANUAL", "SCHEDULED", "ADMISSION"):
        require(bool(evidence["trial_job_ids"]), "KEYWORD_TRIAL_EVIDENCE_REQUIRED")
    if target == "ADMISSION":
        require(bool(evidence["scheduled_job_ids"]) and bool(evidence["refresh_job_ids"]),
                "KEYWORD_COLLECTION_EVIDENCE_REQUIRED")


def transition(before, target, evidence, now):
    """仅编制不可变计划；调用方还必须核实作业、运行来源及原生九步维护。"""
    source = identify(before)
    require(target in PHASES, "KEYWORD_PHASE_UNKNOWN")
    require(target == "OFF" and source != "OFF" or
            PHASES.index(target) == PHASES.index(source) + 1, "KEYWORD_PHASE_JUMP")
    project = evidence.get("project") if isinstance(evidence, dict) else None
    if target == "OFF":
        require(evidence == {}, "KEYWORD_OFF_EVIDENCE_INVALID")
        project = ""
    else:
        validate_evidence(evidence, project, target, now)
        require(source == "OFF" or project == before["topic_quota_project"], "KEYWORD_PROJECT_CHANGED")
    value = dict(schema=1, source=source, target=target, created_at=now,
                 before=deepcopy(before), after=phase_values(target, project), evidence=deepcopy(evidence))
    return dict(value, identity=digest(value))


def validate_transition(value, now, *, fresh=True):
    require(isinstance(value, dict) and set(value) ==
            {"schema", "source", "target", "created_at", "before", "after", "evidence", "identity"},
            "KEYWORD_TRANSITION_INVALID")
    require(type(value["schema"]) is int and value["schema"] == 1, "KEYWORD_TRANSITION_INVALID")
    # 使用原时刻重建，避免运行后证据自然过期导致误改业务状态；实际采用须 fresh。
    rebuilt = transition(value["before"], value["target"], value["evidence"], value["created_at"])
    require(value == rebuilt, "KEYWORD_TRANSITION_DRIFT")
    if fresh:
        require(_recent(value["created_at"], now, 1800), "KEYWORD_PLAN_EXPIRED")
        if value["target"] != "OFF":
            validate_evidence(value["evidence"], value["after"]["topic_quota_project"], value["target"], now)
    return deepcopy(value["after"])


def expected_protections(original, value, now, *, fresh=True):
    after = validate_transition(value, now, fresh=fresh)
    require(isinstance(original, dict) and FIELDS <= original.keys()
            and {k: original[k] for k in FIELDS} == value["before"], "KEYWORD_PROTECTION_BASELINE_MISMATCH")
    require(original.get("enable_market_hours_guard") is True, "KEYWORD_GUARD_REQUIRED")
    return {**deepcopy(original), **after}
