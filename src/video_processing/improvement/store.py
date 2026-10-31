"""独立改进记录：互斥写入、原子发布、方案版本批准与分层验收。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 不改业务数据库，以不可变批次和单指针提交报告与审核账本。 |
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import uuid

from .analysis import LABELS, clean, digest

PLAN_FIELDS = {"kind", "title", "problem", "hypothesis", "confidence", "scope", "change",
               "risk", "cost", "rollback", "acceptance", "protections", "observation_days"}
DECISIONS = {"APPROVED", "RETURNED", "DEFERRED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict) -> None:
    pending = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    try:
        with pending.open("x", encoding="utf-8") as stream:
            os.chmod(pending, 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def evidence_receipt(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("证据必须是已有普通文件")
    data = path.read_bytes()
    if not data:
        raise ValueError("证据不能为空")
    import hashlib
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def render(record: dict) -> str:
    a = record["analysis"]
    lines = [f"# 异常改进分析 {a['report_day']}", "", f"采样：{a['observed_at']}；范围：全部当前存量、昨日新增事件、七日事件趋势。",
             "", f"昨日失败事件 **{a['yesterday_event_count']}** 次，涉及 **{a['yesterday_families']}** 个主任务族；当前未解决 **{a['backlog_families']}** 个主任务族。",
             "", "| 当前互斥分类 | 主任务族 |", "| --- | ---: |"]
    lines += [f"| {label} | {a['primary_buckets'].get(key, 0)} |" for key, label in LABELS.items()]
    lines += ["", "注意：原因组可能交叉，不能相加；供应商错误次数不等于失败任务数。", "", "## 本次重点（最多三项）", ""]
    candidates = [i for i in record["issues"].values() if i.get("present")
                  and i["cause_code"] != "DEPENDENCY_COOLDOWN_BACKOFF"
                  and i["state"] in {"PENDING_REVIEW", "RETURNED", "DEFERRED", "REOPENED"}
                  and (i["first_seen"][:10] == a["report_day"] or i.get("overdue")
                       or i["metrics"]["trend"] == "WORSENING" or i["state"] == "REOPENED")]
    candidates.sort(key=lambda i: (i["bucket"] in {"technical", "blocked", "observation"}, i.get("overdue", False),
                                   i["metrics"]["trend"] == "WORSENING", i["metrics"]["affected_families"], i["metrics"]["yesterday_event_count"]), reverse=True)
    for item in candidates[:3]:
        lines += [f"- **{item['id']} · {item['title']}**：{item['metrics']['affected_families']} 个存量主任务族，昨日 {item['metrics']['yesterday_event_count']} 次；状态 {item['state']}。",
                  f"  建议：{item['plan']['change']} 根因置信度：{item['plan']['confidence']}。"]
    if not candidates:
        lines += ["本次无新增可审核事项；继续跟踪已有事项。"]
    lines += ["", "## 事项及人工审核", "", "自动分析不会批准方案、修复代码、重试任务或投稿。默认提案仅为调查；具体修复须改为 FIX 方案并重新批准。", ""]
    for item in sorted(record["issues"].values(), key=lambda i: i["id"]):
        m, p = item["metrics"], item["plan"]
        lines += [f"### {item['id']} · {item['title']}", "", f"状态：{item['state']}；方案 v{item['plan_version']}；指纹 `{item['plan_sha']}`。",
                  f"本次可见：{item['present']}；{'本次' if item['present'] else '上次可见时'}受影响主任务族 {m['affected_families']}，切片 {len(m['slices'])}；对应昨日事件 {m['yesterday_event_count']}；七日及当日事件 {len(m['event_ids'])}。",
                  f"首次记录 {item['first_seen']}；最近可见 {item['last_seen']}；累计记录事件 {len(item['seen_event_ids'])}；逾期 {item.get('overdue', False)}。",
                  f"原分类 `{item['cause_code']}`；细分错误 `{item['detail'] or '无'}`；归并仅代表相似症状。",
                  "", f"事实：关联任务 {m['task_ids']}；昨日受影响主任务族 {len(m['yesterday_families'])}。",
                  f"假设：{p['hypothesis']}（{p['confidence']}）", f"方案类型：{p['kind']}；建议：{p['change']}",
                  f"涉及范围：{'；'.join(p['scope'])}", f"风险：{p['risk']} 成本：{p['cost']}", f"回退：{p['rollback']}",
                  f"验收：{'；'.join(p['acceptance'])}", f"保护：{'；'.join(p['protections'])}", ""]
        for sample in m["samples"]:
            lines += [f"- 任务 #{sample['video_id']} `{sample.get('youtube_id') or '已删除/未知'}` / 切片 {sample.get('slice_index')}；状态 {sample.get('status')}。",
                      "  ```text", "  " + sample.get("sanitized_error_excerpt", "").replace("```", "'''").replace("\n", "\n  "), "  ```"]
        for ev in item["history"][-5:]:
            lines += [f"- 审核/验收记录：{ev['at']} · {ev['action']} · {ev.get('reviewer', '运行记录')}；方案 {ev.get('plan_sha', '')}。"]
        lines.append("")
    if a["weekly"]:
        lines += ["## 周度复盘", "", "逐项检查复发、逾期与改善证据；未出现同类运行样本不等于修复有效。", ""]
        lines += [f"- {i['id']}：{i['state']}；复发 {i.get('recurrences', 0)} 次；本次可见 {i['present']}。" for i in record["issues"].values()]
    totals = {}
    for issue in a["issues"]:
        for day, count in issue["daily_events"].items():
            totals[day] = totals.get(day, 0) + count
    lines += ["", "## 七日事件趋势", "", "| 北京日期 | 失败事件次数 |", "| --- | ---: |"]
    end = datetime.fromisoformat(a["report_day"])
    lines += [f"| {(end-timedelta(days=offset)).date().isoformat()} | {totals.get((end-timedelta(days=offset)).date().isoformat(), 0)} |" for offset in range(7, 0, -1)]
    lines += ["", "## 证据限制", "", a["coverage"]["note"],
              f"孤立事件 {a['coverage']['orphaned_events']}；历史覆盖不足：{a['source_summary'].get('has_insufficient_history', True)}。",
              a["source_summary"].get("window_history_note", ""), a["effectiveness"]["reason"],
              "原诊断 system_fault 指标可能包含投递待核实；本报告已按类别分开。没有公开证明不代表未发布。",
              f"本次执行代码摘要：`{record.get('implementation_sha', 'UNKNOWN')}`。",
              "本地报告、人工批准、测试通过、运行采用及平台公开回读分别记账。", ""]
    return "\n".join(lines)


class ReviewStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("记录目录不能是符号链接")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def locked(self):
        with (self.root / ".lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def read(self) -> dict | None:
        pointer = self.root / "current.json"
        if not pointer.exists():
            return None
        p = json.loads(pointer.read_text())
        if not re.fullmatch(r"[0-9a-f]{32}", p["generation"]):
            raise ValueError("报告指针不合法")
        record = json.loads((self.root / "runs" / p["generation"] / "record.json").read_text())
        if digest(record) != p["record_sha"]:
            raise ValueError("报告账本摘要不匹配")
        return record

    def commit(self, record: dict) -> Path:
        generation = uuid.uuid4().hex
        run = self.root / "runs" / generation
        run.mkdir(parents=True, mode=0o700)
        atomic_json(run / "record.json", record)
        report = run / "report.md"
        with report.open("x", encoding="utf-8") as stream:
            os.chmod(report, 0o600)
            stream.write(render(record))
            stream.flush()
            os.fsync(stream.fileno())
        # 指针最后提交；此前中断只留下未引用批次，不会污染已完整报告和审核状态。
        atomic_json(self.root / "current.json", {"generation": generation, "record_sha": digest(record)})
        return report

    def merge(self, analysis: dict, implementation_sha: str) -> Path:
        previous = self.read()
        issues = deepcopy(previous["issues"]) if previous else {}
        for item in issues.values():
            item["present"] = False
        for incoming in analysis["issues"]:
            key = incoming["id"]
            if key not in issues:
                plan = incoming["plan"]
                issues[key] = dict(id=key, title=incoming["title"], cause_code=incoming["cause_code"],
                                   detail=incoming["detail"], bucket=incoming["bucket"],
                                   state="PENDING_REVIEW", plan=plan, plan_version=1, plan_sha=digest(plan),
                                   first_seen=analysis["observed_at"], last_seen=analysis["observed_at"],
                                   seen_event_ids=[], seen_task_ids=[], history=[], recurrences=0)
            item = issues[key]
            new_events = set(incoming["event_ids"]) - set(item["seen_event_ids"])
            new_tasks = set(incoming["task_ids"]) - set(item["seen_task_ids"])
            if item["state"] == "CLOSED" and (new_events or new_tasks):
                item["state"] = "REOPENED"
                item["recurrences"] += 1
                item["history"].append(dict(at=analysis["observed_at"], action="REOPENED", plan_sha=item["plan_sha"]))
            item.update(present=True, last_seen=analysis["observed_at"], metrics={k: v for k, v in incoming.items() if k != "plan"})
            item["seen_event_ids"] = sorted(set(item["seen_event_ids"]) | set(incoming["event_ids"]))
            item["seen_task_ids"] = sorted(set(item["seen_task_ids"]) | set(incoming["task_ids"]))
        for item in issues.values():
            item["overdue"] = item["state"] != "CLOSED" and (
                datetime.fromisoformat(analysis["observed_at"]) - datetime.fromisoformat(item["first_seen"])
            ).total_seconds() >= 7 * 86400
        return self.commit(dict(schema=1, analysis=analysis, issues=issues, implementation_sha=implementation_sha))

    def set_plan(self, issue_id: str, plan: dict) -> Path:
        if set(plan) != PLAN_FIELDS or plan["kind"] not in {"FIX", "INVESTIGATION"}:
            raise ValueError("方案字段不完整或类型无效")
        if not all(plan[k] for k in PLAN_FIELDS) or not isinstance(plan["observation_days"], int) or plan["observation_days"] < 7:
            raise ValueError("方案必须包含实质内容和至少七天观察期")
        for k in ("scope", "acceptance", "protections"):
            if not isinstance(plan[k], list) or not all(isinstance(v, str) and v.strip() for v in plan[k]):
                raise ValueError("范围、验收与保护必须为非空文本列表")
        record = self.read()
        item = record["issues"][issue_id]
        sha = digest(plan)
        if sha == item["plan_sha"]:
            raise ValueError("方案未发生变化")
        item["plan"], item["plan_sha"] = plan, sha
        item["plan_version"] += 1
        item["state"] = "PENDING_REVIEW"
        item.pop("approval", None)
        item.pop("observing_since", None)
        item["history"].append(dict(at=utc_now(), action="PLAN_REVISED", plan_sha=sha))
        return self.commit(record)

    def review(self, issue_id: str, decision: str, sha: str, reviewer: str, evidence: Path) -> Path:
        if decision not in DECISIONS or not reviewer.strip():
            raise ValueError("必须提供有效决定和审核人")
        record = self.read()
        item = record["issues"][issue_id]
        if sha != item["plan_sha"] or item["state"] not in {"PENDING_REVIEW", "RETURNED", "DEFERRED", "REOPENED"}:
            raise ValueError("方案版本或审核状态已改变")
        event = dict(at=utc_now(), action=decision, reviewer=clean(reviewer), plan_sha=sha, evidence=evidence_receipt(evidence))
        item["history"].append(event)
        item["state"] = decision
        item.pop("approval", None)
        if decision == "APPROVED":
            item["approval"] = event
        return self.commit(record)

    def advance(self, issue_id: str, state: str, sha: str, evidence: Path) -> Path:
        record = self.read()
        item = record["issues"][issue_id]
        if sha != item["plan_sha"] or item.get("approval", {}).get("plan_sha") != sha:
            raise ValueError("缺少当前版本的人工批准")
        transitions = {"APPROVED": "IMPLEMENTING", "IMPLEMENTING": "LOCAL_VERIFIED", "LOCAL_VERIFIED": "RUNTIME_ADOPTED",
                       "RUNTIME_ADOPTED": "OBSERVING", "OBSERVING": "CLOSED"}
        if item["plan"]["kind"] == "INVESTIGATION":
            transitions = {"APPROVED": "INVESTIGATING", "INVESTIGATING": "ANALYZED"}
        if transitions.get(item["state"]) != state:
            raise ValueError("不得跳过实施、验证或运行采用阶段")
        receipt = evidence_receipt(evidence)
        proof = json.loads(evidence.read_text())
        if proof.get("plan_sha") != sha or proof.get("state") != state or proof.get("passed") is not True:
            raise ValueError("验收证据未绑定本方案和目标阶段")
        now = utc_now()
        if state == "CLOSED":
            elapsed = datetime.fromisoformat(now) - datetime.fromisoformat(item["observing_since"])
            if elapsed.total_seconds() < item["plan"]["observation_days"] * 86400 or type(proof.get("sample_count")) is not int or proof["sample_count"] < 1:
                raise ValueError("观察期或同类实际运行样本不足，不能关闭")
        if state == "OBSERVING":
            item["observing_since"] = now
        item["state"] = state
        item["history"].append(dict(at=now, action=state, plan_sha=sha, evidence=receipt))
        return self.commit(record)
