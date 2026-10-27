"""后台发布恢复服务；固定范围、审计恢复和正式流水线续跑。

# Modification History
| backlog-v1 | 2026-10-26 | Codex | TED 专属50分、真实资格展示与成片积压治理。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 发布恢复控制台领域服务，保留审批、产物、互斥及提交防重。 |
| subtitle-recovery-v1 | 2026-10-27 | Codex | 展示字幕退避与待修复原因，恢复批次不绕过字幕链或永久占用等待。 |
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import time
import uuid
from zoneinfo import ZoneInfo

from config.settings import settings
from .core.maintenance import running
from .core.task_lease import read_lease_owner
from .core.wechat_request_guard import WeChatRequestGuard, WeChatRequestDeferred
from .core.wechat_session_lock import inspect_wechat_session_lock
from .db.publishing_recovery import revision

BJ = ZoneInfo("Asia/Shanghai")
PROTECTED = {"PUBLISHING", "UNDER_REVIEW", "SUBMITTED_UNBOUND", "SUBMITTED_BOUND", "UNCERTAIN",
             "PUBLISHED", "COMPLETED", "REJECTED", "HISTORICAL_UNRESOLVED", "HISTORICAL_ARCHIVED", "NOT_FOUND"}
ACTIVE = {"PROCESSING", "PUBLISH_PRECHECK", "DOWNLOADING", "COPYWRITING", "TRANSCRIBING", "RENDERING"}


def failure_summary(value):
    """旧记录可能保存整段子进程日志；列表只展示末尾有效错误，完整记录仍留在原任务。"""
    lines = [line.strip() for line in str(value or "").splitlines()
             if line.strip() and line.strip() not in {"Aborted!", "Traceback (most recent call last):"}]
    return (lines[-1] if lines else "")[:240]


def prefix_for(video):
    yid, index = video["youtube_id"], int(video.get("slice_index") or 0)
    prefix = f"{yid}_s{index}" if index else yid
    if not re.fullmatch(r"[A-Za-z0-9_-]+", prefix):
        raise ValueError("任务身份无效")
    return prefix


def task_paths(root, video):
    prefix = prefix_for(video)
    return [str((root / "output" / f"{prefix}{suffix}.mp4").resolve())
            for suffix in ("_vertical_interactive", "_vertical", "_vocab", "_insight")]


def has_account_submission(row, video):
    """兼容历史绝对成片路径及单片 ID；不因恢复或文件名变体丢失提交身份。"""
    prefix = prefix_for(video)
    stems = {prefix, *(prefix + s for s in ("_vertical", "_vertical_interactive", "_vocab", "_insight"))}
    state = row.get("schedule", {})
    tasks = list(state.get("submit_intents", {})) + [v.get("task", "") for v in state.get("publications", {}).values()]
    return any(str(task) == prefix or Path(str(task)).stem in stems for task in tasks)


def time_window(window, start=None, end=None, *, now=None):
    now = datetime.fromtimestamp(time.time(), timezone.utc) if now is None else now
    if window == "today":
        first, last = now.astimezone(BJ).replace(hour=0, minute=0, second=0, microsecond=0), now
    elif window == "24h":
        first, last = now - timedelta(hours=24), now
    elif window == "custom":
        try:
            first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        except (ValueError, TypeError) as exc:
            raise ValueError("请填写有效的起止时间") from exc
        if first.tzinfo is None or last.tzinfo is None:
            raise ValueError("自定义时间必须带时区")
        if last > now + timedelta(seconds=5):
            raise ValueError("结束时间不能在未来")
    else:
        raise ValueError("请选择今天、最近 24 小时或自定义时间")
    if first >= last or last - first > timedelta(days=30):
        raise ValueError("时间范围必须大于零且不超过 30 天")
    return {"start": first.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "end": last.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "start_bj": first.astimezone(BJ).isoformat(), "end_bj": last.astimezone(BJ).isoformat(),
            "window": window}


class PublishingRecoveryService:
    def __init__(self, db, root):
        self.db, self.root = db, Path(root)
        self.out = self.root / "output"
        self.guard = WeChatRequestGuard(self.out / "wechat_state.json")

    def status(self):
        result = self.guard.evaluate(account_only=True)
        browser = inspect_wechat_session_lock(self.out / "wechat_state.json")
        result["browser_owner"] = browser.owner
        result["maintenance"] = not running()
        result["publishing_paused"] = settings.wechat_publishing_paused
        result["market_avoidance"] = settings.is_us_market_guard_window()
        result["processing_owner"] = read_lease_owner(self.out / "pipeline.lock")
        result["account"] = "当前视频号账户"
        extras = []
        if browser.locked:
            extras.append({"code": "BROWSER_BUSY", "reason": "真实浏览器会话正在使用账号", "until": None})
        if result["maintenance"]:
            extras.append({"code": "MAINTENANCE", "reason": "系统处于维护或停止状态", "until": None})
        if settings.wechat_publishing_paused:
            extras.append({"code": "PUBLISHING_PAUSED", "reason": "视频号发布已暂停", "until": None})
        result["blockers"].extend(extras)
        result["allowed"] = not result["blockers"]
        if extras:
            result["until"] = None
        return result

    def classify(self, record, account, *, operation_id=None):
        video, flags = record["video"], record["flags"]
        prefix = prefix_for(video)
        state = video["status"]
        subtitle = self.db.subtitle_recovery_blocker(video["id"])
        raw_reason = video.get("error_msg") or video.get("publication_wait_reason") or ""
        content_gate = bool(re.search(r"Censorship[ _]P[012]|Social Unrest Review|Channel Policy Reject|政策敏感拦截|频道策略限制|平台题材风险", raw_reason, re.I))
        quality_gate = bool(re.search(r"需人工处理|门禁|商品绑定|PRODUCT_.*BLOCK|COPY_QUALITY|停止出片|原字幕位置或文字不确定|整片 [AB].*安全位置|TRANSLATION_QUALITY", raw_reason, re.I))
        item = {"id": video["id"], "youtube_id": video["youtube_id"], "slice_index": video.get("slice_index", 0),
                "title": video.get("zh_title") or video.get("title") or prefix, "status": state,
                "revision": revision(video), "failed_at": video.get("failed_at") or video.get("updated_at"),
                "estimated": not bool(video.get("failed_at")), "score": video.get("score"),
                "reason": failure_summary(raw_reason),
                "ready": bool(video.get("preparation_ready")), "eligible": False, "category": "manual",
                "source": video.get("source"), "approval": "需处理" if video.get("publication_review_required") else "已人工放行；发布前核对绑定" if video.get("bypass_censorship") else "发布前按现有绑定复核"}
        if state in PROTECTED or flags["submission_protected"] or has_account_submission(account, video):
            item.update(category="protected", reason="已有提交意图、回执或结果待确认，禁止重投")
        elif state in ACTIVE or video.get("process_pid") or read_lease_owner(self.out / "task_locks" / f"{prefix}.lock"):
            item.update(reason="任务已在执行或持有实际租约，等待当前任务结束")
        elif flags["active_operation"] and flags["active_operation"] != operation_id:
            item.update(reason="已在恢复批次中，请查看原批次", operation_id=flags["active_operation"])
        elif flags["active_lease"] and not operation_id:
            item.update(reason="已有活动人工执行授权，请等待原任务")
        elif (flags["blacklisted"] or not flags["keyword_allowed"] or video.get("source") == "DISCOVERY"
              or state in {"IGNORED", "SEGMENTED", "CANCELED"}):
            item.update(reason="浏览素材、黑名单或非生产任务不能通过恢复提权")
        elif video.get("source") in {"ENGLISH_WORLD", "WALLSTREET_AB", "DOUYIN", "BAIJU_GUOXI"}:
            item.update(category="other", reason="属于独立制作流程，请使用所属流程入口", href="/?view=operations")
        elif state == "LOGIN_REQUIRED":
            item.update(reason="需要登录，完成后台扫码登录后重新预览", href="/?view=operations")
        elif video.get("publication_review_required"):
            item.update(reason="内容审批尚未完成，请先在审核队列处理", href="/?view=production&tab=review")
        elif subtitle:
            item.update(reason=subtitle['reason'], subtitle_recovery=subtitle,
                        next_attempt_at=subtitle['next_attempt_at'], href="/?view=production&tab=error")
        elif quality_gate or (content_gate and not video.get("bypass_censorship")):
            item.update(reason="质量、内容或商品门禁需先处理：" + item["reason"], href="/?view=production&tab=error")
        elif state not in {"FAILED", "PENDING", "WECHAT_DEFERRED"}:
            item.update(reason="当前状态不适用技术恢复")
        else:
            blockers = self.guard.evaluate(task=task_paths(self.root, video)[0])["blockers"]
            item.update(eligible=True, category="recoverable" if blockers else "ready")
            item["blockers"] = blockers
            if item['ready'] and state == 'PENDING':
                from .utils.wechat_product_execution import blocked_product_task_keys
                qualification = self.db.get_publication_eligibility([video['id']],
                    source_subtitle_retry_hours=settings.source_subtitle_retry_hours,
                    excluded_product_tasks=blocked_product_task_keys(self.out, settings.wechat_product_policy_path))[video['id']]
                if not qualification['eligible']:
                    item.update(eligible=False, category='qualification',
                        reason='；'.join(b['reason'] for b in qualification['blockers']),
                        blockers=qualification['blockers'] + blockers)
        item["artifacts"] = "成片已就绪；完整验证后直接发布检查" if item["ready"] else "保留有效缓存，从最早失效步骤续跑"
        item["stage"] = "发布检查" if item["ready"] else "加工续跑"
        return item

    def preview(self, *, window="24h", start=None, end=None, include_ready=False):
        bounds = time_window(window, start, end)
        account = self.guard.snapshot()
        items = [self.classify(r, account) for r in self.db.publishing_recovery_candidates(bounds["start"], bounds["end"], include_ready=include_ready)]
        payload = {**bounds, "items": items, "account_version": self.guard.recovery_version(account),
                   "include_ready": include_ready, "created_at": time.time()}
        return {**payload, "preview_id": self.db.save_publishing_recovery_preview(payload), "total": len(items)}

    def execute(self, request):
        """本机 UI 明确确认后的调用；同操作 ID 重放不会重新恢复或扩展目标。"""
        try:
            uuid.UUID(request["operation_id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("操作 ID 无效") from exc
        existing = self.db.get_publishing_recovery_operation(request["operation_id"])
        if existing:
            if existing["request"] != request:
                raise ValueError("操作 ID 已用于不同请求")
            if existing["state"] == "PLANNED":
                self.resume_setup(existing["id"], request)
            return self.db.get_publishing_recovery_operation(existing["id"])
        if not running():
            raise ValueError("维护状态禁止恢复，请等待维护结束")
        selected = []
        if request.get("selected_ids"):
            preview = self.db.get_publishing_recovery_preview(request.get("preview_id"))
            by_id = {i["id"]: i for i in preview["items"]}
            ids = request["selected_ids"]
            if len(set(ids)) != len(ids) or len(ids) > 1000:
                raise ValueError("选择项重复或超过 1000 项，请分批恢复")
            for key in ids:
                if key not in by_id or not by_id[key]["eligible"]:
                    raise ValueError("所选项不在本次可恢复预览中")
                selected.append(by_id[key])
            if request.get("expected_version") != preview["account_version"]:
                raise ValueError("账户确认与预览不一致，请重新预览")
        elif not (request.get("reset_quota") or request.get("reset_cooldown")):
            raise ValueError("请选择任务或恢复操作")
        self.db.create_publishing_recovery_operation(request["operation_id"], request, selected)
        self.resume_setup(request["operation_id"], request)
        return self.db.get_publishing_recovery_operation(request["operation_id"])

    def resume_setup(self, key, request):
        try:
            operation = self.db.get_publishing_recovery_operation(key)
            if not operation or operation["state"] != "PLANNED":
                return
            priority = []
            if request.get("priority") or request.get("reset_quota") or request.get("reset_cooldown"):
                for item in operation["items"]:
                    if item["state"] == "RESERVED":
                        priority.extend(task_paths(self.root, item))
            receipt = None
            if request.get("reset_quota") or request.get("reset_cooldown") or priority:
                receipt = self.guard.recover_local(operation_id=key, expected_version=request["expected_version"],
                    reset_quota=request.get("reset_quota", False), reset_cooldown=request.get("reset_cooldown", False),
                    priority_tasks=priority)
            self.db.finish_publishing_recovery_setup(key, receipt=receipt)
            # 取消可能先于账户文件落盘；登记结束后再撤回本批次的残余优先位置。
            if self.db.get_publishing_recovery_operation(key)["state"] == "CANCELLED":
                self.guard.cancel_recovery_priority(key)
        except (ValueError, WeChatRequestDeferred) as exc:
            self.db.finish_publishing_recovery_setup(key, error=str(exc))

    def cancel(self, key):
        if not self.db.get_publishing_recovery_operation(key):
            raise ValueError("恢复批次不存在")
        self.db.cancel_publishing_recovery(key)
        self.guard.cancel_recovery_priority(key)
        return self.db.get_publishing_recovery_operation(key)

    def dispatch_once(self, manager):
        """独立恢复 worker 每次最多正式启动一项；等待时不启动浏览器。"""
        for row in self.db.pending_publishing_recovery_setups():
            self.resume_setup(row["id"], json.loads(row["request"]))
        if not running() or settings.wechat_publishing_paused:
            return False
        for item in self.db.pending_publishing_recovery_items():
            record = self.db.publishing_recovery_video(item["video_id"])
            if not record:
                self.db.update_publishing_recovery_item(item["id"], "SKIPPED", "原任务已删除，未恢复")
                continue
            video = record["video"]
            if item["state"] == "RUNNING":
                self._finish_item(item, video, after_restart=True)
                continue
            if revision(video) != item["current_revision"]:
                self.db.update_publishing_recovery_item(item["id"], "SKIPPED", "预览后任务已变化，未执行")
                continue
            subtitle = self.db.subtitle_recovery_blocker(video['id'])
            if subtitle:
                self.db.update_publishing_recovery_item(
                    item['id'], 'ATTENTION' if subtitle['state'] == 'NEEDS_REPAIR' else 'WAITING',
                    subtitle['reason'], next_at=subtitle['next_attempt_at'])
                continue
            classified = self.classify(record, self.guard.snapshot(), operation_id=item["operation_id"])
            if not classified["eligible"]:
                self.db.update_publishing_recovery_item(item["id"], "SKIPPED", classified["reason"])
                continue
            permit = bool(item["permit_expires"] and item["permit_expires"] > time.time() and not item["permit_used"])
            ready = bool(video.get("preparation_ready"))
            if not ready and not permit and (settings.is_us_market_guard_window() or not settings.is_public_publish_window()):
                self.db.update_publishing_recovery_item(item["id"], "WAITING", "等待制作避让／制作时段" + ("；单次许可已到期" if item["permit_expires"] else ""))
                continue
            if ready:
                info = self.guard.evaluate(task=task_paths(self.root, video)[0])
                if not info["allowed"]:
                    self.db.update_publishing_recovery_item(item["id"], "WAITING", "；".join(b["reason"] for b in info["blockers"]), next_at=info["until"])
                    continue
                if inspect_wechat_session_lock(self.out / "wechat_state.json").locked:
                    self.db.update_publishing_recovery_item(item["id"], "WAITING", "等待真实浏览器会话释放")
                    continue
            elif read_lease_owner(self.out / "pipeline.lock"):
                self.db.update_publishing_recovery_item(item["id"], "WAITING", "等待实际加工锁释放")
                continue
            operation = self.db.get_publishing_recovery_operation(item["operation_id"])
            if operation["request"].get("reset_backoff") and not item["started"]:
                self.db.reset_proven_upload_backoff(video["id"])
            wait = self.db.publishing_recovery_task_wait(video["id"])
            if wait:
                self.db.update_publishing_recovery_item(item["id"], "WAITING", "等待任务提交前退避；文案服务退避保持原规则", next_at=wait)
                continue
            activated = self.db.activate_publishing_recovery_item(item["id"])
            if not activated:
                continue
            # 高分和低分统一走原流水线；最终内容、素材和投稿门禁仍由其逐项验证。
            try:
                manager._process_single_video(activated, submission_only=ready, claim=not ready)
            except Exception as exc:
                self.db.update_publishing_recovery_item(item["id"], "ATTENTION", f"执行中断，需核实任务归属：{type(exc).__name__}")
                return True
            current = self.db.get_video_by_youtube_id(video["youtube_id"], int(video.get("slice_index") or 0))
            self._finish_item(item, current)
            return True
        return False

    def _finish_item(self, item, video, *, after_restart=False):
        if not video:
            self.db.update_publishing_recovery_item(item["id"], "SKIPPED", "原任务已删除")
            return
        if read_lease_owner(self.out / "task_locks" / f"{prefix_for(video)}.lock"):
            return
        state = video["status"]
        if state == "PUBLISHING" and not self.db.publishing_recovery_video(video["id"])["flags"]["submission_protected"]:
            self.db.update_publishing_recovery_item(item["id"], "ATTENTION", "投稿进程中断，需人工核实是否提交；未自动重投")
        elif state in PROTECTED or self.db.publishing_recovery_video(video["id"])["flags"]["submission_protected"]:
            result = "PUBLISHED" if state in {"PUBLISHED", "COMPLETED"} else "SUBMITTED_UNVERIFIED"
            self.db.update_publishing_recovery_item(item["id"], result, "已有发表动作或提交证据，停止重投；平台结果以人工核实为准")
        elif (subtitle := self.db.subtitle_recovery_blocker(video['id'])):
            self.db.update_publishing_recovery_item(
                item['id'], 'ATTENTION' if subtitle['state'] == 'NEEDS_REPAIR' else 'WAITING',
                subtitle['reason'], next_at=subtitle['next_attempt_at'], refresh_revision=True)
        elif state in {"PENDING", "WECHAT_DEFERRED"}:
            self.db.update_publishing_recovery_item(item["id"], "WAITING", video.get("publication_wait_reason") or video.get("error_msg") or "等待正式调度", refresh_revision=True)
        elif state in ACTIVE and after_restart:
            if not read_lease_owner(self.out / "task_locks" / f"{prefix_for(video)}.lock"):
                self.db.update_publishing_recovery_item(item["id"], "ATTENTION", "执行进程中断，任务归属待核实；未自动重投")
        else:
            self.db.update_publishing_recovery_item(item["id"], "FAILED", video.get("error_msg") or "本次执行结束，请检查任务状态")
