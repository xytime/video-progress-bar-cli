"""复用现有诊断的改进事项归并与增量统计（纯函数）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 区分事件与存量，稳定事项/方案指纹，保守处理根因及改善指标。 |
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from ..funnel_diagnosis.models import TaskUnitFacts
from ..funnel_diagnosis.rules import extract_tail_error_signature, sanitize_error_excerpt

BJ = timezone(timedelta(hours=8))
LABELS = {"technical": "技术执行故障/识别受阻", "blocked": "流程或依赖阻塞",
          "uncertain": "投递结果待核实", "policy": "质量或策略拦截", "observation": "观测不足"}
DETAIL_CODES = ("VISUAL_REVIEW_BUDGET_EXCEEDED", "OCR_BUDGET_EXCEEDED", "OCR_INVALID_ROW")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def clean(raw: str) -> str:
    """补充隐藏 URL、Bearer 和常见凭据，禁止把完整日志写入报告。"""
    raw = re.sub(r"(?i)\bBearer\s+\S+", "Bearer <REDACTED>", str(raw))
    raw = re.sub(r"(?i)([\"']?(?:api[_-]?key|token|cookie|password|authorization|secret)[\"']?\s*[:=]\s*)(?:[\"'][^\"']*[\"']|\S+)", r"\1<REDACTED>", raw)
    raw = re.sub(r"https?://[^\s\"']+", "<REDACTED_URL>", raw)
    return sanitize_error_excerpt(raw)


def bucket(category: str, cause_code: str = "") -> str:
    if cause_code in {"RECOVERY_EVIDENCE_UNVERIFIED", "RECOVERY_IN_PROGRESS"}:
        return "observation"
    return {"DELIVERY_UNVERIFIED": "uncertain", "QUALITY_POLICY_BLOCK": "policy",
            "FLOW_STALL": "blocked", "DEPENDENCY_BLOCK": "blocked",
            "EXECUTION_FAILURE": "technical", "OBSERVATION_ANOMALY": "observation"}.get(category, "observation")


def event_diagnosis(event: dict) -> dict:
    """事件只用当时状态与原因，不套用当前审核标签和平台状态。"""
    task = TaskUnitFacts(video_id=event["video_id"], youtube_id=event.get("youtube_id") or "",
                         status=event["status"], error_msg=event.get("reason") or "")
    cat, code, title, _ = extract_tail_error_signature(task)
    if event["status"] == "LOGIN_REQUIRED":
        cat, code, title = "DEPENDENCY_BLOCK", "LOGIN_REQUIRED", "登录授权阻塞"
    return dict(category=cat, cause_code=code, cause_title=title, stage_label="失败事件",
                sanitized_error_excerpt=clean(event.get("reason") or ""))


def identity(row: dict) -> tuple[str, str]:
    """不改写上游分类；细分其具体错误证据，相似症状不宣称共同根因。"""
    code = row["cause_code"]
    text = clean(row.get("sanitized_error_excerpt") or "")
    detail = next((c for c in DETAIL_CODES if c in text), "")
    if code == "STAGE_EXECUTION_FAILED" and not detail:
        lines = [s for s in text.splitlines() if s.strip() and s.strip() != "Aborted!"]
        detail = re.sub(r"\[youtube\]\s+[^: ]+:?", "[youtube]:", lines[-1] if lines else "UNKNOWN")
        detail = re.sub(r"\b[0-9a-fA-F]{12,}\b|\d+(?:\.\d+)?", "#", detail)[:180]
    # 事件缺少可靠阶段时使用稳定原因归并，避免同一问题因报告来源分裂。
    signature = {"cause_code": code, "detail": detail}
    return "IMP-" + digest(signature)[:12].upper(), detail


def default_plan(issue: dict) -> dict:
    """默认仅是调查提案；无证据时不生成已确认的修复结论。"""
    uncertain = issue["bucket"] == "uncertain"
    return {
        "kind": "INVESTIGATION", "title": issue["title"],
        "problem": f"同类症状 {issue['cause_code']}，具体错误特征 {issue['detail'] or '未细分'}。",
        "hypothesis": "根因尚未确证，需核对代表性证据；相似错误不保证同一根因。",
        "confidence": "UNCONFIRMED", "scope": ["只读核对具名任务和已保存证据"],
        "change": "核实原生提交回执与平台身份，列出缺失证据。" if uncertain else "核对最终异常、实际阶段、输入与检查点，形成最小修复规格。",
        "risk": "错误归因可能导致无效修复；证据不足时保留未知。",
        "cost": "先抽查代表性任务，不重跑媒体，不调用付费 API。",
        "rollback": "调查无需业务回退；后续修复须另列回退步骤。",
        "acceptance": ["事实与假设分开", "证据能追溯到任务及实际错误", "修复提案包含失败与防退化反例"],
        "protections": ["不重试、重置、上传或发布", "不放宽质量门禁", "不消耗既有人工批准"],
        "observation_days": 7,
    }


def build_analysis(diagnosis: dict, events: list[dict], now: datetime) -> dict:
    """全量当前存量与七日事件分开汇总，所有窗口为北京时间自然日。"""
    now = now.astimezone(BJ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    groups: dict[str, dict] = {}
    family_buckets: dict[int, set[str]] = {}
    priority = ["uncertain", "observation", "technical", "blocked", "policy"]

    def ensure(row: dict) -> dict:
        key, detail = identity(row)
        if key not in groups:
            groups[key] = dict(id=key, cause_code=row["cause_code"], detail=detail,
                               title=clean(row["cause_title"]), bucket=bucket(row["category"], row["cause_code"]),
                               families=set(), task_ids=set(), slices=set(), event_ids=set(),
                               yesterday_ids=set(), yesterday_families=set(), previous_day_ids=set(),
                               samples=[], first_event=None, last_event=None, daily_events=Counter())
        return groups[key]

    for row in diagnosis["tasks"]:
        if not row.get("unresolved"):
            continue
        g = ensure(row)
        family = row["family_root_id"]
        g["families"].add(family)
        g["task_ids"].add(row["video_id"])
        if row.get("slice_index", 0) > 0:
            g["slices"].add(row["video_id"])
        family_buckets.setdefault(family, set()).add(g["bucket"])
        if len(g["samples"]) < 3:
            g["samples"].append({k: clean(row.get(k) or "") if k == "sanitized_error_excerpt" else row.get(k)
                                 for k in ("video_id", "youtube_id", "slice_index", "status", "handling_state", "sanitized_error_excerpt")})
    for ev in events:
        row = event_diagnosis(ev)
        g = ensure(row)
        when = datetime.fromisoformat(ev["failed_at"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(BJ)
        g["event_ids"].add(ev["event_id"])
        g["daily_events"][when.date().isoformat()] += 1
        if yesterday <= when < today:
            g["yesterday_ids"].add(ev["event_id"])
            g["yesterday_families"].add(ev["family_root_id"])
        if yesterday - timedelta(days=1) <= when < yesterday:
            g["previous_day_ids"].add(ev["event_id"])
        stamp = when.isoformat()
        g["first_event"] = min(g["first_event"] or stamp, stamp)
        g["last_event"] = max(g["last_event"] or stamp, stamp)
        if len(g["samples"]) < 3 and not any(s["video_id"] == ev["video_id"] for s in g["samples"]):
            g["samples"].append(dict(video_id=ev["video_id"], youtube_id=ev.get("youtube_id"), slice_index=ev.get("slice_index"),
                                     status=ev["status"], event_id=ev["event_id"], sanitized_error_excerpt=row["sanitized_error_excerpt"]))
    issues = []
    for g in groups.values():
        for key in ("families", "task_ids", "slices", "event_ids", "yesterday_ids", "yesterday_families", "previous_day_ids"):
            g[key] = sorted(g[key])
        g["daily_events"] = dict(sorted(g["daily_events"].items()))
        g["affected_families"] = len(g["families"])
        g["yesterday_event_count"] = len(g["yesterday_ids"])
        g["trend"] = "WORSENING" if len(g["yesterday_ids"]) > len(g["previous_day_ids"]) else "STABLE_OR_LOWER"
        g["plan"] = default_plan(g)
        issues.append(g)
    primary = Counter(next(b for b in priority if b in cats) for cats in family_buckets.values())
    yesterday_ids = {n for issue in issues for n in issue["yesterday_ids"]}
    return dict(observed_at=now.isoformat(), report_day=now.date().isoformat(),
                previous_day=yesterday.date().isoformat(), weekly=now.weekday() == 0,
                source_summary=diagnosis["summary"], source_as_of=diagnosis["as_of_bj"],
                backlog_families=len(family_buckets), primary_buckets=dict(primary), issues=issues,
                yesterday_event_count=sum(i["yesterday_event_count"] for i in issues),
                yesterday_families=len({ev["family_root_id"] for ev in events if ev["event_id"] in yesterday_ids}),
                coverage=dict(event_ledger_since="2026-10-23", orphaned_events=sum(bool(e.get("orphaned")) for e in events),
                              note="事件仅覆盖状态切换为 FAILED/LOGIN_REQUIRED；不含所有供应商错误或同状态内部重试。历史存量时间可为估算。"),
                effectiveness=dict(state="UNAVAILABLE", reason="缺少同类实际执行分母与资源账本；不从状态快照推算成功率或节省费用。"))
