"""合规二创不可变快照与单次审批 DAL。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | GPT-6.1 Sol | 独立身份、上下文绑定审批和事务领取 |
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import time
from typing import Any


def canonical_manifest(manifest: dict) -> str:
    """拒绝 NaN，并固定审批内容序列化。"""
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(canonical_manifest(manifest).encode()).hexdigest()


class ComplianceRemixDAL:
    """SQL 仅供 PipelineDB 继承使用。"""

    def initialize_compliance_remix(self) -> None:
        with self.get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS compliance_remix_proposals (
                proposal_id TEXT PRIMARY KEY, video_id INTEGER NOT NULL UNIQUE REFERENCES processed_videos(id),
                source_id TEXT NOT NULL, manifest_json TEXT NOT NULL, content_hash TEXT NOT NULL,
                work_dir TEXT NOT NULL, actor TEXT NOT NULL, chat TEXT NOT NULL,
                purpose TEXT NOT NULL, expires_at REAL NOT NULL, state TEXT NOT NULL,
                created_at REAL NOT NULL, approved_at REAL, claimed_at REAL, revoked_at REAL,
                receipt_json TEXT, error TEXT, human_reviewed_at REAL, human_reviewed_hash TEXT
            )""")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(compliance_remix_proposals)")}
            for column, kind in (("human_reviewed_at", "REAL"), ("human_reviewed_hash", "TEXT")):
                if column not in columns:
                    conn.execute(f"ALTER TABLE compliance_remix_proposals ADD COLUMN {column} {kind}")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS compliance_remix_immutable
                BEFORE UPDATE OF proposal_id, video_id, created_at, manifest_json, content_hash, work_dir, source_id, actor, chat, purpose, expires_at
                ON compliance_remix_proposals BEGIN SELECT RAISE(ABORT, 'immutable proposal'); END""")

            conn.execute("""CREATE TRIGGER IF NOT EXISTS compliance_remix_source_identity
                BEFORE UPDATE OF source, youtube_id, slice_index ON processed_videos
                WHEN OLD.source='COMPLIANCE_REMIX' AND
                     (NEW.source IS NOT OLD.source OR NEW.youtube_id IS NOT OLD.youtube_id OR NEW.slice_index IS NOT OLD.slice_index)
                BEGIN SELECT RAISE(ABORT, 'immutable compliance remix identity'); END""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS compliance_remix_status_authority
                BEFORE UPDATE OF status ON processed_videos
                WHEN OLD.source='COMPLIANCE_REMIX' AND NEW.status IS NOT COALESCE(
                    (SELECT CASE state WHEN 'APPROVED' THEN 'PENDING_REVIEW' WHEN 'REVOKED' THEN 'CANCELLED' ELSE state END
                     FROM compliance_remix_proposals WHERE video_id=OLD.id), 'NO_PROPOSAL')
                BEGIN SELECT RAISE(ABORT, 'compliance remix lifecycle authority required'); END""")

    def create_compliance_remix(self, *, proposal_id: str, source_id: str, manifest: dict,
                                work_dir: str, actor: str, chat: str, purpose: str = "produce",
                                ttl_seconds: int = 3600) -> dict[str, Any]:
        """独立任务与快照在同一事务落盘，绝无 PENDING 窗口。"""
        if not re.fullmatch(r"remix_[0-9a-f]{32}", proposal_id) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", source_id):
            raise ValueError("提案或源 ID 无效")
        if manifest.get("id") != proposal_id or str(Path(work_dir).resolve()) != work_dir:
            raise ValueError("快照身份或工作目录无效")
        if not actor or not chat or purpose not in {"produce", "publish"} or not 1 <= ttl_seconds <= 86400:
            raise ValueError("审批上下文或有效期无效")
        payload = canonical_manifest(manifest)
        digest = manifest_digest(manifest)
        now = time.time()
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("""INSERT INTO processed_videos
                (youtube_id,title,channel_id,score,status,source,zh_title,disable_slicing,publication_review_required)
                VALUES (?,?,'COMPLIANCE_REMIX',0,'PENDING_REVIEW','COMPLIANCE_REMIX',?,1,1)""",
                (proposal_id, manifest["source_title"], manifest["title"]))
            conn.execute("""INSERT INTO compliance_remix_proposals
                (proposal_id,video_id,source_id,manifest_json,content_hash,work_dir,actor,chat,purpose,expires_at,state,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,'PENDING_REVIEW',?)""",
                (proposal_id, cursor.lastrowid, source_id, payload, digest, work_dir,
                 str(actor), str(chat), purpose, now + ttl_seconds, now))
        return self.get_compliance_remix(proposal_id)

    def get_compliance_remix(self, proposal_id: str) -> dict[str, Any]:
        """读取持久快照，不推断默认工作目录。"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM compliance_remix_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if row is None:
            raise ValueError("提案不存在")
        return dict(row)

    @staticmethod
    def _check_remix_context(row: dict, *, actor: str, chat: str, content_hash: str, purpose: str) -> None:
        if (row["actor"] != str(actor) or row["chat"] != str(chat) or row["content_hash"] != content_hash
                or row["purpose"] != purpose or row["expires_at"] <= time.time()):
            raise ValueError("审批上下文、内容哈希或有效期不匹配")
        if manifest_digest(json.loads(row["manifest_json"])) != content_hash:
            raise ValueError("提案快照哈希不匹配")

    def approve_compliance_remix(self, proposal_id: str, *, actor: str, chat: str,
                                 content_hash: str, purpose: str = "produce", source_reviewed: bool = False) -> None:
        """仅允许待审提案批准一次，不续期、不复活终态。"""
        if source_reviewed is not True:
            raise ValueError("必须明确确认已核对来源事实、脚本及全部拟用镜头")
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM compliance_remix_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None or row["state"] != "PENDING_REVIEW":
                raise ValueError("提案不是可批准状态")
            self._check_remix_context(dict(row), actor=actor, chat=chat, content_hash=content_hash, purpose=purpose)
            conn.execute("UPDATE compliance_remix_proposals SET state='APPROVED',approved_at=?,human_reviewed_at=?,human_reviewed_hash=? WHERE proposal_id=?", (time.time(), time.time(), content_hash, proposal_id))

    def claim_compliance_remix(self, proposal_id: str, *, actor: str, chat: str,
                               content_hash: str, purpose: str = "produce") -> dict[str, Any]:
        """BEGIN IMMEDIATE 串行竞争，最多一个执行者领取。"""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM compliance_remix_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None or row["state"] != "APPROVED" or row["claimed_at"] is not None or row["human_reviewed_at"] is None or row["human_reviewed_hash"] != content_hash:
                raise ValueError("提案未批准、已撤销或已领取")
            self._check_remix_context(dict(row), actor=actor, chat=chat, content_hash=content_hash, purpose=purpose)
            conn.execute("UPDATE compliance_remix_proposals SET state='PROCESSING',claimed_at=? WHERE proposal_id=?", (time.time(), proposal_id))
            conn.execute("UPDATE processed_videos SET status='PROCESSING' WHERE id=?", (row["video_id"],))
        return dict(row)

    def revoke_compliance_remix(self, proposal_id: str, *, actor: str, chat: str) -> None:
        """撤销待审或尚未领取的审批；在途须人工核对，不重置。"""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM compliance_remix_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if (row is None or row["actor"] != str(actor) or row["chat"] != str(chat)
                    or row["state"] not in {"PENDING_REVIEW", "APPROVED"}):
                raise ValueError("任务不可撤销或审批上下文不匹配")
            conn.execute("UPDATE compliance_remix_proposals SET state='REVOKED',revoked_at=? WHERE proposal_id=?", (time.time(), proposal_id))
            conn.execute("UPDATE processed_videos SET status='CANCELLED' WHERE id=?", (row["video_id"],))

    def finish_compliance_remix(self, proposal_id: str, *, state: str, receipt: dict | None = None,
                                error: str | None = None) -> None:
        """只终结已领取任务；未知/提交态永久停止自动重传。"""
        allowed = {"COMPLETED", "FAILED", "UNCERTAIN"}
        if state not in allowed:
            raise ValueError("无效终态")
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM compliance_remix_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None or row["state"] != "PROCESSING":
                raise ValueError("任务不是已领取状态")
            conn.execute("UPDATE compliance_remix_proposals SET state=?,receipt_json=?,error=? WHERE proposal_id=?",
                         (state, canonical_manifest(receipt or {}), error, proposal_id))
            conn.execute("UPDATE processed_videos SET status=?,error_msg=? WHERE id=?", (state, error, row["video_id"]))
