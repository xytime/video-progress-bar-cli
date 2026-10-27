"""发布恢复的失败事件、固定预览及持久批次；SQL 仅位于 DAL。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-23 | Codex | 增量失败时间、预览绑定、幂等批次与逐项领取／取消。 |
| subtitle-recovery-v1 | 2026-10-27 | Codex | 发布恢复等待与启动事务复核字幕冷却，禁止清账绕过。 |
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid


def revision(video):
    return hashlib.sha256(json.dumps(dict(video), sort_keys=True, default=str).encode()).hexdigest()


class PublishingRecoveryDAL:
    def initialize_publishing_recovery(self):
        with self.get_connection() as c:
            columns = {r[1] for r in c.execute("PRAGMA table_info(processed_videos)")}
            if "failed_at" not in columns:
                c.execute("ALTER TABLE processed_videos ADD COLUMN failed_at TEXT")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS publishing_failure_events (
                    id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL,
                    status TEXT NOT NULL, reason TEXT, failed_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS publishing_failure_time ON publishing_failure_events(failed_at, video_id);
                CREATE TRIGGER IF NOT EXISTS publishing_failed_update AFTER UPDATE OF status ON processed_videos
                WHEN NEW.status IN ('FAILED','LOGIN_REQUIRED') AND OLD.status != NEW.status
                BEGIN
                    UPDATE processed_videos SET failed_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=NEW.id;
                    INSERT INTO publishing_failure_events(video_id,status,reason,failed_at)
                    VALUES(NEW.id,NEW.status,NEW.error_msg,strftime('%Y-%m-%d %H:%M:%f','now'));
                END;
                CREATE TRIGGER IF NOT EXISTS publishing_failed_insert AFTER INSERT ON processed_videos
                WHEN NEW.status IN ('FAILED','LOGIN_REQUIRED')
                BEGIN
                    UPDATE processed_videos SET failed_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=NEW.id;
                    INSERT INTO publishing_failure_events(video_id,status,reason,failed_at)
                    VALUES(NEW.id,NEW.status,NEW.error_msg,strftime('%Y-%m-%d %H:%M:%f','now'));
                END;
                CREATE TABLE IF NOT EXISTS publishing_recovery_previews (
                    id TEXT PRIMARY KEY, created REAL NOT NULL, expires REAL NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS publishing_recovery_operations (
                    id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                    state TEXT NOT NULL, request TEXT NOT NULL, receipt TEXT, reason TEXT);
                CREATE TABLE IF NOT EXISTS publishing_recovery_items (
                    id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES publishing_recovery_operations(id),
                    video_id INTEGER REFERENCES processed_videos(id) ON DELETE SET NULL,
                    position INTEGER NOT NULL, state TEXT NOT NULL, reason TEXT, next_at REAL,
                    original TEXT NOT NULL, current_revision TEXT NOT NULL,
                    started REAL, updated REAL NOT NULL, permit_expires REAL, permit_used REAL,
                    UNIQUE(operation_id,video_id));
                CREATE UNIQUE INDEX IF NOT EXISTS publishing_recovery_one_active ON publishing_recovery_items(video_id)
                WHERE state IN ('RESERVED','WAITING','RUNNING');
            """)

    @staticmethod
    def _publishing_video(c, video_id):
        row = c.execute("SELECT * FROM processed_videos WHERE id=?", (video_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _publishing_flags(c, video):
        vid = video["id"]
        protected = any(c.execute(f"SELECT 1 FROM {table} WHERE video_id=? LIMIT 1", (vid,)).fetchone()
                        for table in ("wechat_publications", "wechat_submission_attempts", "wechat_publications_historical_archive"))
        blacklisted = bool(c.execute("SELECT 1 FROM blacklisted_videos WHERE youtube_id=?", (video["youtube_id"],)).fetchone()
                           or c.execute("SELECT 1 FROM recommended_channels WHERE channel_id=? AND status='BLACKLISTED'", (video.get("channel_id"),)).fetchone())
        lease = c.execute("""SELECT lease_id FROM manual_publish_leases WHERE video_id=?
            AND revoked_at IS NULL AND claimed_at IS NULL AND expires_at>CURRENT_TIMESTAMP
            LIMIT 1""", (vid,)).fetchone()
        active = c.execute("SELECT operation_id FROM publishing_recovery_items WHERE video_id=? AND state IN ('RESERVED','WAITING','RUNNING')", (vid,)).fetchone()
        return {"submission_protected": protected, "blacklisted": blacklisted,
                "keyword_allowed": bool(c.execute("SELECT keyword_allowed(?,?)", (video.get("source"), video["youtube_id"])).fetchone()[0]),
                "active_lease": bool(lease), "active_operation": active[0] if active else None}

    def publishing_recovery_video(self, video_id):
        with self.get_connection() as c:
            video = self._publishing_video(c, video_id)
            return {"video": video, "flags": self._publishing_flags(c, video)} if video else None

    def publishing_recovery_candidates(self, start, end, *, include_ready=False):
        """旧失败明确标记估算；时间边界在服务层冻结后传入。"""
        with self.get_connection() as c:
            rows = c.execute("""SELECT * FROM processed_videos
                WHERE (COALESCE(failed_at,updated_at) >= ? AND COALESCE(failed_at,updated_at) <= ?
                       AND (failed_at IS NOT NULL OR status IN ('FAILED','LOGIN_REQUIRED')))
                   OR (? AND preparation_ready=1 AND status IN ('PENDING','WECHAT_DEFERRED'))
                ORDER BY COALESCE(failed_at,updated_at) DESC, id""", (start, end, int(include_ready))).fetchall()
            return [{"video": dict(v), "flags": self._publishing_flags(c, dict(v))} for v in rows]

    def save_publishing_recovery_preview(self, payload):
        key = uuid.uuid4().hex
        with self.get_connection() as c:
            c.execute("DELETE FROM publishing_recovery_previews WHERE expires<?", (time.time() - 86400,))
            c.execute("INSERT INTO publishing_recovery_previews VALUES(?,?,?,?)",
                      (key, time.time(), time.time()+900, json.dumps(payload, ensure_ascii=False)))
        return key

    def get_publishing_recovery_preview(self, key):
        with self.get_connection() as c:
            row = c.execute("SELECT * FROM publishing_recovery_previews WHERE id=?", (key,)).fetchone()
            if not row or row["expires"] <= time.time():
                raise ValueError("预览已过期，请重新预览并选择")
            return json.loads(row["payload"])

    def create_publishing_recovery_operation(self, operation_id, request, selected):
        """先保留所选身份，再恢复账户；每个身份最多属于一个活动批次。"""
        now = time.time()
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT request FROM publishing_recovery_operations WHERE id=?", (operation_id,)).fetchone()
            if old:
                if json.loads(old[0]) != request:
                    raise ValueError("操作 ID 已用于不同请求")
                return False
            c.execute("INSERT INTO publishing_recovery_operations(id,created,updated,state,request) VALUES(?,?,?,'PLANNED',?)",
                      (operation_id, now, now, json.dumps(request, ensure_ascii=False)))
            for pos, item in enumerate(selected):
                video = self._publishing_video(c, item["id"])
                reason = None
                if not video or revision(video) != item["revision"]:
                    reason = "预览后任务已变化，未恢复该项"
                elif self._publishing_flags(c, video)["active_operation"]:
                    reason = "该任务已在另一恢复批次中"
                c.execute("""INSERT INTO publishing_recovery_items(operation_id,video_id,position,state,reason,original,
                    current_revision,updated,permit_expires) VALUES(?,?,?,?,?,?,?,?,?)""",
                          (operation_id, item["id"] if video else None, pos, "SKIPPED" if reason else "RESERVED", reason,
                           json.dumps(item, ensure_ascii=False), item["revision"], now,
                           now+1800 if request.get("skip_avoidance") else None))
            return True

    def finish_publishing_recovery_setup(self, operation_id, *, receipt=None, error=None):
        with self.get_connection() as c:
            changed = c.execute("UPDATE publishing_recovery_operations SET state=?,updated=?,receipt=?,reason=? WHERE id=? AND state='PLANNED'",
                      ("BLOCKED" if error else "QUEUED", time.time(), json.dumps(receipt, ensure_ascii=False), error, operation_id)).rowcount
            if not changed:
                if receipt:
                    c.execute("UPDATE publishing_recovery_operations SET receipt=?,reason='已取消尚未启动项；账户恢复已记录' WHERE id=? AND state='CANCELLED'", (json.dumps(receipt, ensure_ascii=False), operation_id))
                return
            c.execute("UPDATE publishing_recovery_items SET state=?,reason=COALESCE(?,reason),updated=? WHERE operation_id=? AND state='RESERVED'",
                      ("SKIPPED" if error else "WAITING", error, time.time(), operation_id))

            if not error:
                c.execute("""UPDATE publishing_recovery_operations SET state='COMPLETED' WHERE id=? AND NOT EXISTS
                    (SELECT 1 FROM publishing_recovery_items WHERE operation_id=? AND state IN ('WAITING','RUNNING'))""", (operation_id, operation_id))

    def get_publishing_recovery_operation(self, key):
        with self.get_connection() as c:
            row = c.execute("SELECT * FROM publishing_recovery_operations WHERE id=?", (key,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["request"] = json.loads(result["request"])
            result["receipt"] = json.loads(result["receipt"]) if result["receipt"] else None
            result["items"] = [dict(r) for r in c.execute("""SELECT i.*,pv.youtube_id,pv.slice_index,pv.title,pv.status AS video_status,
                pv.zh_title,pv.publication_wait_reason,pv.error_msg
                FROM publishing_recovery_items i LEFT JOIN processed_videos pv ON pv.id=i.video_id
                WHERE operation_id=? ORDER BY position""", (key,))]
            for item in result["items"]:
                item["original"] = json.loads(item["original"])
            return result

    def list_publishing_recovery_operations(self, *, limit=20, offset=0):
        with self.get_connection() as c:
            total = c.execute("SELECT count(*) FROM publishing_recovery_operations").fetchone()[0]
            keys = [r[0] for r in c.execute("SELECT id FROM publishing_recovery_operations ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset))]
        return {"total": total, "items": [self.get_publishing_recovery_operation(k) for k in keys]}

    def pending_publishing_recovery_setups(self):
        with self.get_connection() as c:
            return [dict(r) for r in c.execute("SELECT id,request FROM publishing_recovery_operations WHERE state='PLANNED' ORDER BY created")]

    def pending_publishing_recovery_items(self):
        with self.get_connection() as c:
            return [dict(r) for r in c.execute("""SELECT i.* FROM publishing_recovery_items i
                JOIN publishing_recovery_operations o ON o.id=i.operation_id
                WHERE i.state IN ('WAITING','RUNNING') AND o.state='QUEUED' ORDER BY o.created,i.position""")]

    def update_publishing_recovery_item(self, key, state, reason="", *, next_at=None, refresh_revision=False):
        with self.get_connection() as c:
            row = c.execute("SELECT * FROM publishing_recovery_items WHERE id=?", (key,)).fetchone()
            if not row or row["state"] not in ("WAITING", "RUNNING"):
                return False
            video = self._publishing_video(c, row["video_id"])
            current = revision(video) if refresh_revision and video else row["current_revision"]
            c.execute("UPDATE publishing_recovery_items SET state=?,reason=?,next_at=?,current_revision=?,updated=? WHERE id=?",
                      (state, reason, next_at, current, time.time(), key))
            c.execute("""UPDATE publishing_recovery_operations SET state='COMPLETED',updated=?
                WHERE id=? AND state='QUEUED' AND NOT EXISTS (SELECT 1 FROM publishing_recovery_items
                WHERE operation_id=? AND state IN ('RESERVED','WAITING','RUNNING'))""",
                      (time.time(), row["operation_id"], row["operation_id"]))
            return True

    def activate_publishing_recovery_item(self, key):
        """在最终启动前事务复核；只签发本项短期 lease，不修改评分和来源。"""
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM publishing_recovery_items WHERE id=? AND state='WAITING'", (key,)).fetchone()
            if not row:
                return None
            video = self._publishing_video(c, row["video_id"])
            flags = self._publishing_flags(c, video) if video else {}
            foreign_lease = c.execute("""SELECT 1 FROM manual_publish_leases WHERE video_id=?
                AND issued_via!=? AND revoked_at IS NULL AND claimed_at IS NULL AND expires_at>CURRENT_TIMESTAMP
               """, (row["video_id"],"recovery:"+row["operation_id"])).fetchone()
            if (not video or foreign_lease or revision(video) != row["current_revision"] or flags.get("submission_protected")
                    or flags.get("blacklisted") or not flags.get("keyword_allowed")
                    or video.get("publication_review_required") or video.get("source") == "DISCOVERY"
                    or video["status"] not in ("PENDING","FAILED","WECHAT_DEFERRED")):
                c.execute("UPDATE publishing_recovery_items SET state='SKIPPED',reason='启动前身份、审批或状态变化，未执行',updated=? WHERE id=?", (time.time(), key))
                c.execute("""UPDATE publishing_recovery_operations SET state='COMPLETED',updated=?
                    WHERE id=? AND state='QUEUED' AND NOT EXISTS (SELECT 1 FROM publishing_recovery_items
                    WHERE operation_id=? AND state IN ('RESERVED','WAITING','RUNNING'))""",
                          (time.time(), row["operation_id"], row["operation_id"]))
                return None
            if self._subtitle_blocker_in(c, video["id"]):
                return None
            if not flags["active_lease"]:
                c.execute("""INSERT INTO manual_publish_leases(lease_id,video_id,platform,issued_by,issued_via,
                    expires_at)
                    VALUES(?,?,'wechat','后台操作者',?,datetime('now','+120 minutes'))""",
                          (uuid.uuid4().hex, video["id"], "recovery:"+row["operation_id"]))
            c.execute("UPDATE processed_videos SET status='PENDING',process_pid=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (video["id"],))
            c.execute("UPDATE publishing_recovery_items SET state='RUNNING',started=?,updated=?,permit_used=? WHERE id=?",
                      (time.time(), time.time(), time.time() if row["permit_expires"] and row["permit_expires"] > time.time() else None, key))
            return self._publishing_video(c, video["id"])

    def cancel_publishing_recovery(self, operation_id):
        with self.get_connection() as c:
            c.execute("BEGIN IMMEDIATE")
            rows = c.execute("SELECT * FROM publishing_recovery_items WHERE operation_id=? AND state IN ('RESERVED','WAITING')", (operation_id,)).fetchall()
            for row in rows:
                video = self._publishing_video(c, row["video_id"])
                original = json.loads(row["original"])
                if video and revision(video) == row["current_revision"] and video["status"] == "PENDING" and not self._publishing_flags(c, video)["submission_protected"]:
                    c.execute("UPDATE processed_videos SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND process_pid IS NULL",
                              (original.get("status", "FAILED"), video["id"]))
                c.execute("""UPDATE manual_publish_leases SET revoked_at=CURRENT_TIMESTAMP
                    WHERE video_id=? AND issued_via=? AND claimed_at IS NULL AND revoked_at IS NULL""",
                          (row["video_id"], "recovery:"+operation_id))
            c.execute("UPDATE publishing_recovery_items SET state='CANCELLED',reason='用户取消尚未启动项',updated=? WHERE operation_id=? AND state IN ('RESERVED','WAITING')", (time.time(),operation_id))
            c.execute("""UPDATE publishing_recovery_operations SET state='CANCELLED',updated=? WHERE id=?
                AND NOT EXISTS(SELECT 1 FROM publishing_recovery_items WHERE operation_id=? AND state='RUNNING')""", (time.time(),operation_id,operation_id))
            return len(rows)

    def publishing_recovery_task_wait(self, video_id):
        with self.get_connection() as c:
            subtitle = self._subtitle_blocker_in(c, video_id)
            if subtitle and subtitle['state'] == 'NEEDS_REPAIR':
                # 兼容旧时间接口；实际放行始终由启动事务的同一门禁决定。
                return time.time() + 86400
            values = [r[0] for table in ("copywriter_deferred", "wechat_upload_retries")
                      for r in c.execute(f"SELECT strftime('%s',next_attempt_at) FROM {table} WHERE video_id=? AND next_attempt_at>CURRENT_TIMESTAMP", (video_id,))]
            if subtitle:
                values.append(subtitle['next_attempt_at'])
            return max((float(v) for v in values), default=None)

    def reset_proven_upload_backoff(self, video_id):
        """重新验证零进度凭据后解除本次本地等待，绝不删除凭据或尝试次数。"""
        from pathlib import Path
        from ..core.wechat_upload_recovery import valid_timeout_receipt
        with self.get_connection() as c:
            video = self._publishing_video(c, video_id)
            if not video or self._publishing_flags(c, video)["submission_protected"]:
                return False
            rows = c.execute("SELECT * FROM wechat_upload_retries WHERE video_id=? AND next_attempt_at>CURRENT_TIMESTAMP", (video_id,)).fetchall()
            for row in rows:
                path = Path(row["evidence_path"])
                try:
                    receipt = json.loads(path.read_text())
                    expected = video["youtube_id"] + (f"_s{video['slice_index']}" if video.get("slice_index") else "")
                    stem = Path(receipt["video_path"]).stem
                    if stem not in {expected+s for s in ("_vertical","_vertical_interactive","_vocab","_insight")}:
                        return False
                    if not valid_timeout_receipt(path.parent, receipt["video_path"]):
                        return False
                except (OSError, KeyError, ValueError, TypeError):
                    return False
            return bool(c.execute("UPDATE wechat_upload_retries SET next_attempt_at=CURRENT_TIMESTAMP WHERE video_id=? AND next_attempt_at>CURRENT_TIMESTAMP", (video_id,)).rowcount)
