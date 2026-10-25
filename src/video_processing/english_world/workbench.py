"""英语世界桌面工作台编排：身份绑定查询、资格判断和安全动作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-25 | Codex | 重开研究任务时沿用原任务明确来源并保留原失败记录。 |
| 1.1.0 | 2026-10-25 | Codex | 将缺少近期心跳的执行状态标为待核实，并提供阶段中文名。 |
| 1.0.0 | 2026-10-25 | Codex | 提供任务视图、详情、固定证据及受控动作服务。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from urllib.parse import urlparse

from .console import EnglishConsole, clean


class EnglishWorldWorkbench:
    PAGE_SIZE = 20
    ACTIONS = {"research", "select_candidate", "confirm_production", "approve_submission", "hold", "resume", "record_outcome"}

    def __init__(self, db, output):
        self.db = db
        self.console = EnglishConsole(db, Path(output))

    @staticmethod
    def _revision(item):
        material = {k: item.get(k) for k in ("task_id", "status", "last_activity", "current_step", "block_reason", "_rev_seq")}
        return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]

    def _item(self, row):
        record = row["_record"]
        is_run = row["id"].startswith("run:")
        task_id = row["id"]
        status = row["state"]
        identity = self._run_identity(record) if is_run else None
        bound_attempts = identity.get("attempts", []) if identity else []
        attempt = bound_attempts[-1] if bound_attempts else None
        block = row.get("error") or ("历史关联不足：没有明确的运行身份记录" if is_run and not identity else "")
        if is_run and not block and not record.get("_run_status", {}).get("phase"):
            block = "没有与本次run配对的阶段状态/heartbeat；当前运行状态无法核实"
        current_step = (record.get("production_state") or status) if not is_run else ("candidate:"+str(attempt.get("candidate_id") or "unknown") if attempt else "run_record")
        unverified_activity = None
        if not is_run and status == "RESEARCHING":
            unverified_activity = "研究状态待核实"
        elif not is_run and (record.get("production_state") or status) == "PRODUCING":
            unverified_activity = "制作状态待核实"
        if unverified_activity:
            current_step = unverified_activity
            block = "没有近期执行心跳；账本状态保留，但无法确认当前仍在执行"
        item = {"task_id": task_id, "record_type": "run" if is_run else "task",
                "title": row["title"], "source": row["source"], "current_step": current_step,
                "block_reason": block, "last_activity": row.get("updated_at"),
                "created_at": row.get("created_at"), "status": status,
                "display_status": unverified_activity or row["label"], "trigger": row["trigger"],
                "age_bucket": "history" if row.get("created_at") and
                    (datetime.now(timezone.utc)-datetime.fromisoformat(row["created_at"])).days >= 7 else "current"}
        item["_rev_seq"] = self.db.english_world_workbench_revision(task_id)
        row["_revision_seq"] = item["_rev_seq"]
        if is_run:
            item["association"] = "BOUND" if identity and attempt else "HISTORICAL_UNBOUND"
            item["run_id"] = identity.get("run_id") if identity else None
            item["source_attempt_id"] = attempt.get("source_attempt_id") if attempt else None
        item["revision"] = self._revision(item)
        item["action_eligibility"] = self._eligibility(row)
        item.pop("_rev_seq", None)
        return item

    def _run_identity(self, record):
        """仅沿请求引用或具名 run log 的固定配对 sidecar 查关联。"""
        try:
            request = self.console.read(record.get("_request")) if record.get("_request") else {}
            identity_path = request.get("workbench_run_identity_path")
            if identity_path:
                identity_path = self.console.local(identity_path)
            elif record.get("_run_log"):
                identity_path = Path(record["_run_log"]).with_suffix(".identity.json")
                identity_path = self.console.local(identity_path)
            else:
                return None
            data = self.console.read(identity_path)
            expected_run_id = request.get("workbench_run_id")
            if data.get("identity_schema") != 1 or not data.get("run_id") or (expected_run_id and data.get("run_id") != expected_run_id):
                return None
            attempts = data.get("attempts")
            if not isinstance(attempts, list):
                return None
            expected_run_id = expected_run_id or data.get("run_id")
            valid = [a for a in attempts if isinstance(a, dict) and a.get("source_attempt_id")
                     and a.get("run_id", expected_run_id) == expected_run_id]
            result = dict(data)
            result["attempts"] = valid
            return result
        except (OSError, ValueError, TypeError):
            return None

    def _eligibility(self, row):
        state = row["state"]
        is_run = row["id"].startswith("run:")
        candidates = self.db.get_english_world_candidates(str(row["_job"]["id"])) if row.get("_job") else []
        failed_research = bool(row.get("_job") and row["_job"].get("state") == "FAILED"
                               and not row["_job"].get("production_state"))
        product_ok, product_reason = self._product_context_status(row.get("_record", {}))
        hashes_ok = all(isinstance(row.get("_record", {}).get(field), str)
                        and len(row["_record"][field]) == 64 for field in
                        ("artifact_sha256", "manifest_sha256", "title_sha256", "copy_sha256", "cover_sha256", "cover_provenance_sha256"))
        approve_ok = not is_run and state == "READY_FOR_REVIEW" and hashes_ok and product_ok
        approve_reason = "可执行" if approve_ok else ("复核记录缺少六项完整包哈希" if not hashes_ok else product_reason if not product_ok else "仅成片待复核项可授权投稿")
        choices = {"research": (not is_run and (state == "RESEARCH_QUEUED" or failed_research), "仅研究任务可启动候选研究"),
                   "select_candidate": (not is_run and state == "CANDIDATES_READY" and bool(candidates), "当前没有可选候选"),
                   "confirm_production": (not is_run and state == "CANDIDATE_SELECTED", "先选择候选并核验来源准入"),
                   "approve_submission": (approve_ok, approve_reason),
                   "hold": (not is_run and state == "READY_FOR_REVIEW", "仅待审核成片可暂缓"),
                   "resume": (self._resume_request(row) is not None, self._resume_block_reason(row)),
                   "record_outcome": (not is_run and state in {"UNCERTAIN", "UNDER_REVIEW", "SUBMITTED_BOUND"}, "仅投稿结果待核验项可登记人工结果")}
        return {k: {"allowed": bool(ok), "reason": "可执行" if ok else reason} for k, (ok, reason) in choices.items()}

    def _product_context_status(self, record):
        try:
            manifest_path = self.console.local(record.get("manifest_path"))
            manifest = self.console.read(manifest_path)
            context = manifest.get("product_context")
            if not isinstance(context, dict):
                if record.get("id") and self.db.is_legacy_product_review(record["id"], record.get("manifest_sha256") or ""):
                    return True, "兼容历史包；商品在投稿前按原策略核验"
                return False, "缺少随成片冻结的商品制作意图，不能授权投稿"
            intent = context.get("product_intent")
            if intent not in {"AUTO", "PRODUCT", "NONE"}:
                return False, "成片商品制作意图无效，需重新核验"
            if intent == "PRODUCT" and (not context.get("product_id") or not context.get("product_title")):
                return False, "必需商品身份不完整，不能授权投稿"
            if intent == "AUTO":
                source = manifest.get("source_provenance") or {}
                from video_processing.english_world.product_production import production_task_id
                task_id = production_task_id({"content_type": manifest.get("content_type"), "source_provenance": source})
                registered = self.db.get_product_production(task_id)
                if not registered or manifest.get("product_production") != registered:
                    return False, "必需商品制作登记缺失或与成片清单不一致，不能授权投稿"
            return True, "商品制作意图已随成片冻结；平台实际选择仍由投稿前回读核验"
        except (OSError, ValueError, TypeError, KeyError):
            return False, "商品制作意图清单缺失或不可核验"

    def _resume_request(self, row):
        """资格限于本次具名run sidecar明确绑定的完整production delivery request。"""
        if not row["id"].startswith("run:"):
            return None
        record = row["_record"]
        try:
            request_path = self.console.local(record.get("_request"))
            receipt_path = request_path.with_name(request_path.name.replace(".delivery-request.json", ".delivery.json"))
            if not request_path.name.endswith(".delivery-request.json") or receipt_path.exists():
                return None
            request = self.console.read(request_path)
            identity = self._run_identity(record)
            marker_path = request_path.with_name(request_path.name.replace(".delivery-request.json", ".host-phase.json"))
            marker = self.console.read(marker_path)
            if (request.get("kind") != "production" or not identity
                    or request.get("workbench_run_id") != identity.get("run_id")
                    or not identity.get("attempts") or marker.get("host_phase_schema") != 1
                    or marker.get("run_id") != identity.get("run_id")
                    or marker.get("state") != "FAILED_BEFORE_NOTIFIER"
                    or marker.get("notifier_started") is not False
                    or marker.get("request_sha256") != hashlib.sha256(request_path.read_bytes()).hexdigest()):
                return None
            matched_attempt = next((a for a in identity["attempts"] if a.get("source_attempt_id") == marker.get("source_attempt_id")), None)
            if not matched_attempt or request.get("source_attempt_id") != marker.get("source_attempt_id"):
                return None
            mp4 = self.console.local(request.get("mp4"))
            manifest = self.console.local(request.get("manifest"))
            if not manifest.name.endswith(".json"):
                return None
            data = self.console.read(manifest)
            hashes = {"mp4_sha256": self._sha256_file(mp4), "manifest_sha256": self._sha256_file(manifest)}
            audio_report = self.console.local(request.get("audio_qa_report"))
            safety_ref = request.get("safety_report")
            safety_report = self.console.local(safety_ref) if safety_ref else None
            hashes["audio_qa_report_sha256"] = self._sha256_file(audio_report)
            hashes["safety_report_sha256"] = self._sha256_file(safety_report) if safety_report else None
            if any(marker.get(key) != value for key,value in hashes.items()):
                return None
            from video_processing.english_world.package_integrity import sha256_file
            existing = self.db.get_english_world_review_by_artifact(sha256_file(mp4))
            if existing:
                # 现有审核项需要按原ID继续；当前手动续做执行器只会创建审核项，不能安全复用旧项。
                return None
            # 只接受明确未绑定平台投稿身份的包；执行器仍会重新核验维护/租约/来源/哈希。
            if data.get("platform_post_id") or data.get("submission_state") in {"SUBMITTED_BOUND", "UNDER_REVIEW", "PUBLISHED", "UNCERTAIN"}:
                return None
            return str(request_path)
        except (OSError, ValueError, TypeError):
            return None

    def _resume_block_reason(self, row):
        if not row["id"].startswith("run:"):
            return "该任务没有可续做的 host delivery request"
        record = row["_record"]
        if not record.get("_request"):
            return "原始 delivery request 不存在，不能恢复输入身份"
        try:
            request = self.console.read(record["_request"])
        except (OSError, ValueError, TypeError):
            return "原始 delivery request 不可读取"
        if request.get("kind") != "production":
            return "只有完整 production 成片请求支持待审核续做；failure request 不可恢复"
        if self._run_identity(record) is None:
            return "缺少明确绑定的 run 身份、attempt 与来源输入记录"
        marker_path = Path(record["_request"]).with_name(Path(record["_request"]).name.replace(".delivery-request.json", ".host-phase.json"))
        try:
            marker = self.console.read(marker_path)
        except (OSError, ValueError, TypeError):
            return "没有host-phase证明；旧请求或缺少notifier未调用证据，不可续做"
        if marker.get("state") != "FAILED_BEFORE_NOTIFIER" or marker.get("notifier_started") is not False:
            return "host-phase未证明通知器启动前失败；缺失、PENDING或通知器已启动均不可续做"
        if not self._resume_request(row):
            return "host-phase request/run/attempt或MP4、manifest、音频、安全哈希不匹配；或已有提交状态，不能安全续做"
        return "可继续交付待审核成片"

    def resume_request_path(self, task_id):
        row = self.console.find(task_id)
        path = self._resume_request(row)
        if not path:
            raise PermissionError("具名交付请求不满足未提交、包完整或身份绑定条件")
        return path

    @staticmethod
    def _sha256_file(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def view(self, *, view="attention", q="", status="", trigger="", date_from="", date_to="", page=1, history=False):
        rows, coverage, warnings = self.console.tasks()
        items = [self._item(row) for row in rows]
        query = (q or "").strip().casefold()
        selected = []
        historical = []
        for row, item in zip(rows, items):
            created = item.get("created_at") or ""
            is_run = item["record_type"] == "run"
            matches = (not query or query in (item["title"]+" "+item["source"]+" "+item["task_id"]).casefold())
            status_groups = {"active": {"RESEARCH_QUEUED","RESEARCHING","PRODUCTION_REQUESTED","REQUESTED","PRODUCING","SUBMISSION_APPROVED","SUBMITTING","UNDER_REVIEW","SUBMITTED_BOUND"},
                             "waiting": {"CANDIDATES_READY","CANDIDATE_SELECTED","READY_FOR_REVIEW","LOGIN_REQUIRED","HELD","UNCERTAIN"},
                             "failed": {"FAILED","REJECTED"}, "complete": {"PUBLISHED","CANCELED"}}
            matches &= not status or item["status"] == status or item["status"] in status_groups.get(status, set())
            matches &= not trigger or item["trigger"] == trigger
            matches &= not date_from or created[:10] >= date_from
            matches &= not date_to or created[:10] <= date_to
            matches &= (view == "runs" and is_run) or (view != "runs" and not is_run)
            matches &= view != "attention" or row["attention"] or item["display_status"] in {"研究状态待核实", "制作状态待核实"}
            if matches:
                if item["age_bucket"] == "history" and view == "attention":
                    historical.append(item)
                else:
                    selected.append(item)
                    if item["age_bucket"] == "history" and view == "all":
                        historical.append(item)
        total = len(selected)
        page = max(1, int(page))
        pages = max(1, (total+self.PAGE_SIZE-1)//self.PAGE_SIZE)
        history_pages = max(1, (len(historical)+self.PAGE_SIZE-1)//self.PAGE_SIZE)
        page = min(page, max(pages, history_pages if history and view != "runs" else pages))
        return {"view": view, "filters": {"q": q, "status": status, "trigger": trigger,
                "date_from": date_from, "date_to": date_to, "history": history},
                "page": page, "page_size": self.PAGE_SIZE, "pages": pages, "total": total,
                "items": selected[(page-1)*self.PAGE_SIZE:page*self.PAGE_SIZE],
                "summary": {"latest_run": next((x for x in items if x["record_type"] == "run"), None),
                            "active": sum(1 for r, i in zip(rows, items) if r["active"] and i["display_status"] not in {"研究状态待核实", "制作状态待核实"}),
                            "waiting": sum(1 for r, i in zip(rows, items) if r["attention"] or i["display_status"] in {"研究状态待核实", "制作状态待核实"}), "next_scheduled": None},
                "history": {"count": len(historical), "page": page, "pages": history_pages,
                            "items": historical[(page-1)*self.PAGE_SIZE:page*self.PAGE_SIZE] if history and view != "runs" else [],
                            "collapsed": view == "attention" and not history},
                "coverage": coverage, "warnings": warnings}

    def detail(self, task_id):
        row = self.console.find(task_id)
        item = self._item(row)
        record = row["_record"]
        steps = []
        if task_id.startswith("run:"):
            identity = self._run_identity(record)
            attempt = (identity or {}).get("attempts", [])
            attempt = attempt[-1] if attempt else None
            steps = self._run_steps(identity, attempt)
        elif row.get("_job"):
            job = row["_job"]
            research_state = job.get("state") or "UNKNOWN"
            research_unverified = research_state == "RESEARCHING"
            production_unverified = (job.get("production_state") or "not_started") == "PRODUCING"
            steps = [{"id": name, "label": label, "state": state,
                      "display_state": ("研究状态待核实" if name == "research" and research_unverified else "制作状态待核实" if name == "production" and production_unverified else None),
                      "started_at": job.get("production_started_at") if name == "production" else job.get("created_at"),
                      "ended_at": job.get("production_finished_at") if name == "production" else job.get("updated_at") if research_state == "CANDIDATES_READY" else None,
                      "last_activity": job.get("updated_at"), "detail": job.get("error_message") or ("没有近期执行心跳；账本状态保留，当前执行状态待核实" if (research_unverified if name == "research" else production_unverified) else "当前无阶段心跳；状态可能已陈旧" if row.get("stale") else None)}
                     for name,label,state in [("research","候选研究", research_state),
                                              ("production","制作", job.get("production_state") or "not_started")]]
        else:
            steps = [{"id": "submission", "label": "审核与投稿", "state": record.get("state"), "started_at": record.get("submission_started_at"),
                      "ended_at": record.get("submission_finished_at"), "last_activity": record.get("updated_at"), "detail": row.get("error")}]
        evidence = []
        for kind, report_kind in (("video", "asset"), ("cover", "asset"), ("submission", "platform"),
                                  ("audio", "audio"), ("language", "language"), ("visual", "visual"), ("safety", "safety")):
            evidence_status, identity_status, summary, issues = "缺失", "关联未核实", "尚无可核验的证据", []
            if kind in {"video", "cover"}:
                path_key = "mp4_path" if kind == "video" else "cover_path"
                try:
                    path = self.console.local(record.get(path_key))
                    evidence_status = "可读取"
                    expected_hash = record.get("artifact_sha256" if kind == "video" else "cover_sha256")
                    actual_hash = self._sha256_file(path)
                    identity_status = "审核包SHA256一致" if expected_hash and actual_hash == expected_hash else "当前任务路径；未绑定审核SHA256"
                    if expected_hash and actual_hash != expected_hash:
                        evidence_status = "哈希不一致"
                        issues = ["当前文件已变化，不可作为已审核版本"]
                    if task_id.startswith("run:"):
                        identity_status = "具名运行身份未绑定审核项"
                    summary = f"{path.name} · {path.stat().st_size:,} 字节"
                except (OSError, ValueError):
                    issues = ["文件缺失，或路径超出允许目录"]
            elif kind == "submission":
                platform_id = record.get("platform_post_id")
                evidence_status = "已登记" if platform_id else "待核验"
                identity_status = "原生 ID 已登记" if platform_id else "缺少原生 ID"
                summary = f"当前台账状态：{record.get('platform_state') or record.get('state') or 'UNKNOWN'}；本页未访问平台"
                if record.get("reconciliation_evidence_dir"):
                    try:
                        evidence_dir = Path(record["reconciliation_evidence_dir"])
                        evidence_dir = evidence_dir.resolve()
                        if evidence_dir.is_relative_to(self.console.output) and evidence_dir.is_dir():
                            evidence_status = "有本地核验材料"
                    except (OSError, ValueError):
                        pass
            else:
                report = self.console.report(task_id, report_kind)
                evidence_status = report.get("status", "报告状态未知")
                identity_status = "绑定报告" if "一致" in evidence_status else "身份未核实"
                if identity_status == "绑定报告":
                    issues = [clean(value)[:300] for value in report.get("issues", [])[:8] if value]
                    summary = (issues[0] if issues else next((line for line in report.get("lines", [])
                               if line.startswith(("报告记录：", "报告未列出", "问题摘要", "未发现"))), None)
                               or "无可读取报告")
                else:
                    summary = "报告身份未绑定当前成片，问题摘要不可采纳"
                if evidence_status == "证据缺失或不可读取": issues = ["缺少对应的任务绑定报告"]
                elif identity_status != "绑定报告": issues = ["报告文件与当前包身份不一致"]
            evidence.append({"kind": kind, "status": evidence_status, "generated_at": item.get("last_activity"),
                             "identity_status": identity_status, "summary": summary, "issues": issues,
                             "href": f"/api/english-world/workbench/media?task={task_id}&kind={kind}", "report_kind": report_kind})
        package_hashes = {key: record.get(key) for key in ("artifact_sha256", "manifest_sha256", "title_sha256", "copy_sha256", "cover_sha256", "cover_provenance_sha256")}
        product_ok, product_summary = self._product_context_status(record)
        product_context = {}
        try:
            manifest = self.console.read(self.console.local(record.get("manifest_path")))
            product_context = manifest.get("product_context") if isinstance(manifest.get("product_context"), dict) else {}
        except (OSError, ValueError, TypeError):
            pass
        quality_evidence = [e for e in evidence if e["kind"] in {"audio", "language", "visual", "safety"}]
        quality_summary = {"status": "通过" if quality_evidence and all("通过" in str(e.get("status")) for e in quality_evidence) else "需复核",
                           "items": [{"kind": e["kind"], "status": e["status"], "summary": e["summary"]} for e in quality_evidence]}
        package = {"title": record.get("title") or record.get("submission_title"),
                   "platform": record.get("platform") or "WECHAT_CHANNELS",
                   "package_hashes": package_hashes,
                   "hash_bound_to_review": all(isinstance(v, str) and len(v) == 64 for v in package_hashes.values()),
                   "product_summary": {"status": "FROZEN" if product_ok else "BLOCKED", "intent": product_context.get("product_intent"),
                                       "name": product_context.get("product_title"), "summary": product_summary},
                   "quality_summary": quality_summary}
        capture_name = None
        capture_status = "缺少管理页截图"
        try:
            capture_dir_raw = record.get("reconciliation_evidence_dir")
            capture_dir = Path(capture_dir_raw).resolve() if capture_dir_raw else None
            if capture_dir and not Path(capture_dir_raw).is_symlink() and capture_dir.is_relative_to(self.console.output):
                for name in ("management_published.png", "management_under_review.png", "management_page.png"):
                    candidate = capture_dir / name
                    if candidate.is_file() and not candidate.is_symlink():
                        capture_name = name
                        capture_status = "已保存固定管理页截图"
                        break
        except (OSError, ValueError):
            pass
        evidence.append({"kind": "submission_capture", "status": capture_status,
                         "identity_status": "管理页截图只作人工参考，结构化回读仍单独核验",
                         "summary": capture_name or "当前审核项没有固定名称的管理页截图",
                         "issues": [] if capture_name else ["缺少提交状态截图"],
                         "href": f"/api/english-world/workbench/media?task={task_id}&kind=submission_capture",
                         "capture_name": capture_name})
        candidates = self.db.get_english_world_candidates(str(row["_job"]["id"])) if row.get("_job") else []
        candidates = [{**c, "candidate_id": c.get("candidate_id") or c.get("id"),
                       "source_title": c.get("source_title") or c.get("title"),
                       "source_channel": c.get("source_channel") or c.get("source")}
                      for c in candidates]
        audit = self.db.list_english_world_workbench_audit(task_id)
        safe_audit = []
        for entry in audit:
            result = entry.get("result") or {}
            safe_audit.append({"action": entry.get("action"), "actor": entry.get("actor"),
                               "created_at": entry.get("created_at"),
                               "status": result.get("status") or result.get("recorded_outcome") or ("进行中" if result.get("pending") else "已记录"),
                               "recorded_outcome": result.get("recorded_outcome"),
                               "evidence_identity": result.get("evidence_identity"),
                               "verification_note": result.get("verification_note"),
                               "dispatch_state": result.get("dispatch_state"),
                               "dispatch_message": "执行器启动异常或状态未知；使用原 operation_id 核验" if result.get("dispatch_state") == "FAILED_OR_UNKNOWN" else None})
        return {"task": item, "steps": steps, "evidence": evidence, "actions": item["action_eligibility"], "package": package,
                "candidates": candidates,
                "audit": safe_audit,
                "audit_summary": safe_audit[0] if safe_audit else None,
                "platform_management_url": "https://channels.weixin.qq.com/platform/post/list"}

    def _run_steps(self, identity, attempt):
        if not identity or not attempt:
            return [{"id": "association", "label": "运行关联", "state": "unverified",
                     "detail": "历史关联不足：没有可验证的具名候选阶段记录"}]
        try:
            journal_path = self.console.local(attempt.get("stage_journal"))
            journal = self.console.read(journal_path)
        except (OSError, ValueError, TypeError):
            return [{"id": "association", "label": "运行关联", "state": "unverified",
                     "detail": "运行身份存在，但阶段日志缺失或不可读取"}]
        if not isinstance(journal.get("attempts"), list):
            return []
        by_stage = {}
        for event in journal["attempts"]:
            if (isinstance(event, dict) and event.get("run_id") == identity.get("run_id")
                    and event.get("source_attempt_id") == attempt.get("source_attempt_id")):
                by_stage[event.get("stage", "unknown")] = event
        stage_labels = {"language_review": "语言复核", "audio_qa": "音频质检", "visual_safety": "画面安全复核",
                        "safety_gate": "内容安全门", "render": "成片渲染", "package": "制作包整理"}
        return [{"id": stage, "label": stage_labels.get(stage, stage.replace("_", " ")), "state": event.get("state"),
                 "display_state": "阶段已开始 · 执行状态待核实" if str(event.get("state", "")).upper() == "RUNNING" else None,
                 "started_at": self._ns_stamp(event.get("started_ns")),
                 "ended_at": self._ns_stamp(event.get("finished_ns")),
                 "last_activity": self._ns_stamp(event.get("finished_ns") or event.get("started_ns")),
                 "detail": (clean(' · '.join(str(value) for value in (
                     event.get('error_class') or event.get('error_kind'),
                     event.get('error') or event.get('message')) if value))[:300] or ("阶段已开始，但没有后续心跳，执行状态待核实" if str(event.get("state", "")).upper() == "RUNNING" else None))}
                for stage, event in by_stage.items()]

    @staticmethod
    def _ns_stamp(value):
        try:
            return datetime.fromtimestamp(int(value)/1_000_000_000, timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None

    def action(self, *, task_id, action, revision, operation_id, payload, actor):
        if action not in self.ACTIONS:
            raise ValueError("不支持的动作")
        payload = payload or {}
        if action == "research" and task_id == "new":
            request_hash = hashlib.sha256(json.dumps({"task":task_id,"action":action,"payload":payload}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            prior = self.db.english_world_workbench_audit_result(task_id, action, operation_id)
            if prior:
                if prior["request_hash"] != request_hash: raise RuntimeError("operation_id 已用于不同请求")
                return {**prior["result"], "audit_id": prior["audit_id"], "replayed": True}
            source_url = payload.get("source_url")
            if source_url:
                parsed = urlparse(str(source_url))
                if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}:
                    raise ValueError("指定来源必须是 YouTube 视频链接")
            audit_id = uuid.uuid4().hex
            claim = self.db.reserve_english_world_workbench_action(audit_id=audit_id, task_id=task_id,
                action=action, operation_id=operation_id, actor=actor, request_hash=request_hash)
            if not claim["created"]:
                if claim["request_hash"] != request_hash: raise RuntimeError("operation_id 已用于不同请求")
                if claim["result"].get("failed"): raise RuntimeError(claim["result"].get("message") or "原操作失败，不能重试")
                if claim["result"].get("pending"):
                    return {"audit_id": claim["audit_id"], "replayed": True, "operation_pending": True}
                return {**claim["result"], "audit_id": claim["audit_id"], "replayed": True}
            job = self.db.create_english_world_research_job(requested_by=actor, source_url=source_url)
            result = {"task_id": "job:"+job["id"], "status": job["state"]}
            self.db.complete_english_world_workbench_action(audit_id=audit_id, result=result)
            return {**result, "audit_id": audit_id, "replayed": False}
        row = self.console.find(task_id)
        item = self._item(row)
        request_hash = hashlib.sha256(json.dumps({"task":task_id,"action":action,"payload":payload}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prior = self.db.english_world_workbench_audit_result(task_id, action, operation_id)
        if prior:
            if prior["request_hash"] != request_hash:
                raise RuntimeError("operation_id 已用于不同请求")
            if prior["result"].get("failed"):
                raise RuntimeError(prior["result"].get("message") or "原操作失败，不能重试")
            if prior["result"].get("pending"):
                raise RuntimeError("原操作已预占但未完成；请核对任务状态与审计后再处理，不能重复执行")
            return {**prior["result"], "audit_id": prior["audit_id"], "replayed": True}
        if item["revision"] != revision:
            raise RuntimeError("任务状态已更新，请重新载入")
        eligible = item["action_eligibility"].get(action, {})
        if not eligible.get("allowed"):
            raise PermissionError(eligible.get("reason", "当前任务不允许此动作"))
        audit_id = uuid.uuid4().hex
        reservation = self.db.reserve_english_world_workbench_action(audit_id=audit_id, task_id=task_id,
            action=action, operation_id=operation_id, actor=actor, request_hash=request_hash,
            expected_version=row.get("_revision_seq", 0))
        if not reservation["created"]:
            if reservation["request_hash"] != request_hash:
                raise RuntimeError("operation_id 已用于不同请求")
            if reservation["result"].get("failed"):
                raise RuntimeError(reservation["result"].get("message") or "原操作失败，不能重试")
            if reservation["result"].get("pending"):
                return {"audit_id": reservation["audit_id"], "replayed": True, "operation_pending": True}
            return {**reservation["result"], "audit_id": reservation["audit_id"], "replayed": True}
        record = row["_record"]
        if action == "research":
            source_url = payload.get("source_url") or (row.get("_job") or {}).get("source_url")
            if source_url:
                parsed = urlparse(str(source_url))
                if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}:
                    raise ValueError("指定来源必须是 YouTube 视频链接")
            job = self.db.create_english_world_research_job(requested_by=actor, source_url=source_url)
            result = {"task_id": "job:"+job["id"], "status": job["state"]}
        elif action == "select_candidate":
            candidate_id = str(payload.get("candidate_id") or "")
            if not any(str(candidate.get("id")) == candidate_id for candidate in self.db.get_english_world_candidates(str(row["_job"]["id"]))):
                raise PermissionError("候选不属于当前任务")
            candidate = self.db.select_english_world_candidate(candidate_id)
            result = {"task_id": task_id, "status": "CANDIDATE_SELECTED", "candidate_id": candidate["id"]}
        elif action == "confirm_production":
            job = self.db.request_english_world_production(str(record["id"]))
            result = {"task_id": task_id, "status": job["state"]}
        elif action == "approve_submission":
            if getattr(__import__("config.settings", fromlist=["settings"]).settings, "wechat_publishing_paused", False):
                raise PermissionError("视频号投稿当前已暂停")
            from video_processing.english_world.package_integrity import calculate_package_hashes
            hashes = calculate_package_hashes(record)
            bound_fields = {"artifact_sha256": "artifact_sha256", "manifest_sha256": "manifest_sha256",
                            "title_sha256": "title_sha256", "copy_sha256": "copy_sha256",
                            "cover_sha256": "cover_sha256", "cover_provenance_sha256": "cover_provenance_sha256"}
            if any(not isinstance(record.get(field), str) or len(record[field]) != 64
                   for field in bound_fields):
                raise PermissionError("当前复核记录缺少完整的六项已绑定投稿包哈希；请重新载入对应复核版本")
            if any(hashes.get(key) != record.get(field) for field,key in bound_fields.items()):
                raise PermissionError("当前文件与审核绑定包哈希不一致；素材已变化，必须生成新revision并重新复核")
            approved = self.db.approve_english_world_submission(str(record["id"]), authorization="DESKTOP_WORKBENCH")
            result = {"task_id": task_id, "status": approved["state"], "approval_source": approved.get("approval_source")}
        elif action == "hold":
            held = self.db.hold_english_world_review_item(str(record["id"]))
            result = {"task_id": task_id, "status": held["state"]}
        elif action == "resume":
            if not task_id.startswith("run:") or payload.get("step_id") != "delivery":
                raise PermissionError("当前仅支持从明确的 delivery 步骤继续待审核成片")
            request_path = self._resume_request(row)
            if not request_path:
                raise PermissionError("具名交付请求不满足未提交、包完整或身份绑定条件")
            result = {"task_id": task_id, "status": "RESUME_AUTHORIZED", "request_path": Path(request_path).name,
                      "resume_mode": "MANUAL_REVIEW_ONLY"}
        else:
            outcome = str(payload.get("outcome") or "")
            if outcome not in {"under_review", "public", "unknown"}:
                raise ValueError("人工结果必须为 under_review、public 或 unknown")
            identity_matched = outcome in {"under_review", "public"} and self._identity_match(record, payload.get("evidence"), outcome)
            if outcome == "public" and not identity_matched:
                raise PermissionError("公开证据身份未能与当前审核项原生 ID 及结构化状态报告绑定，不能标记为公开")
            result = {"task_id": task_id, "recorded_outcome": outcome,
                      "verified_at": datetime.now(timezone.utc).isoformat(),
                      "evidence_identity": "MATCHED" if identity_matched else "NOT_VERIFIED",
                      "verification_note": None if identity_matched else "人工声明已记录；平台状态未核实",
                      "submission_state_changed": False}
        self.db.complete_english_world_workbench_action(audit_id=audit_id, result=result)
        return {**result, "audit_id": audit_id, "replayed": False}

    def fail_pending_action(self, task_id, action, operation_id, message):
        pending = self.db.english_world_workbench_audit_result(task_id, action, operation_id)
        if pending and pending["result"].get("pending"):
            self.db.fail_english_world_workbench_action(audit_id=pending["audit_id"], message=message)

    def mark_dispatch(self, audit_id, state, message=None):
        self.db.mark_english_world_workbench_dispatch(audit_id=audit_id, state=state, message=message)

    def _identity_match(self, record, evidence, outcome):
        """只有结构化回读报告与本任务原生身份、目标状态绑定时才算已核实。"""
        if not isinstance(evidence, dict) or not record.get("platform_post_id"):
            return False
        if str(evidence.get("native_id") or "") != str(record.get("platform_post_id")):
            return False
        ref = str(evidence.get("evidence_ref") or "")
        if ref != "management_readback.json":
            return False
        try:
            raw_directory = Path(record.get("reconciliation_evidence_dir") or "")
            directory = raw_directory.resolve()
            if raw_directory.is_symlink() or not directory.is_relative_to(self.console.output) or not directory.is_dir():
                return False
            candidate = (directory / "management_readback.json").resolve()
            if (directory / "management_readback.json").is_symlink() or not candidate.is_relative_to(directory) or not candidate.is_file():
                return False
            report = json.loads(candidate.read_text())
            if not isinstance(report, dict) or report.get("platform_post_id") != str(record["platform_post_id"]):
                return False
            if outcome == "under_review":
                return report.get("state") == "UNDER_REVIEW" and report.get("reason") == "DOM_STATUS_TEXT"
            component = report.get("component_state")
            explicit_status = report.get("reason") == "DOM_STATUS_TEXT"
            if report.get("reason") == "DOM_POSTED_PUBLIC_COMPONENT" and isinstance(component, dict):
                explicit_status = all(component.get(key) is True for key in ("has_posted", "process_success", "posted_info_visible", "public_visibility")) and all(component.get(key) is False for key in ("processing", "scheduled"))
            return report.get("state") == "PUBLISHED" and explicit_status and (directory/"management_published.png").is_file()
        except (OSError, ValueError):
            return False
