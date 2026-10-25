"""英语世界桌面工作台审计与幂等 DAL。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 增加桌面操作审计、幂等回执与记录版本读取。 |
"""
import json
import sqlite3


class EnglishWorldWorkbenchDAL:
    """所有工作台 SQL 集中在 PipelineDB 方法中。"""

    def initialize_english_world_workbench_schema(self):
        with self.get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS english_world_workbench_audit (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL,
            operation_id TEXT NOT NULL, actor TEXT NOT NULL, request_hash TEXT NOT NULL,
            result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(task_id, action, operation_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ew_workbench_audit_task ON english_world_workbench_audit(task_id,created_at DESC)")
            conn.execute("CREATE TABLE IF NOT EXISTS english_world_workbench_revisions(task_id TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0)")

    def english_world_workbench_revision(self, task_id):
        with self.get_connection() as conn:
            row = conn.execute("SELECT version FROM english_world_workbench_revisions WHERE task_id=?", (task_id,)).fetchone()
            return int(row[0]) if row else 0

    def english_world_workbench_audit_result(self, task_id, action, operation_id):
        with self.get_connection() as conn:
            row = conn.execute("SELECT id,request_hash,result_json FROM english_world_workbench_audit WHERE task_id=? AND action=? AND operation_id=?",
                               (task_id, action, operation_id)).fetchone()
            if not row:
                return None
            return {"audit_id": row["id"], "request_hash": row["request_hash"], "result": json.loads(row["result_json"])}

    def reserve_english_world_workbench_action(self, *, audit_id, task_id, action, operation_id, actor, request_hash, expected_version=None):
        """原子预占操作键；pending 记录确保崩溃/并发时不会重复执行副作用。"""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO english_world_workbench_revisions(task_id,version) VALUES(?,0)", (task_id,))
            current = int(conn.execute("SELECT version FROM english_world_workbench_revisions WHERE task_id=?", (task_id,)).fetchone()[0])
            if expected_version is not None and current != int(expected_version):
                conn.rollback()
                raise RuntimeError("任务版本已被其他操作占用，请重新读取后重试")
            try:
                conn.execute("INSERT INTO english_world_workbench_audit(id,task_id,action,operation_id,actor,request_hash,result_json) VALUES(?,?,?,?,?,?,?)",
                             (audit_id, task_id, action, operation_id, actor, request_hash, json.dumps({"pending": True})))
                conn.execute("UPDATE english_world_workbench_revisions SET version=version+1 WHERE task_id=? AND version=?", (task_id,current))
                conn.commit()
                return {"audit_id": audit_id, "request_hash": request_hash, "result": {"pending": True}, "created": True}
            except sqlite3.IntegrityError:
                conn.rollback()
                conn.execute("BEGIN")
                row = conn.execute("SELECT id,request_hash,result_json FROM english_world_workbench_audit WHERE task_id=? AND action=? AND operation_id=?",
                                   (task_id, action, operation_id)).fetchone()
                if not row:
                    conn.rollback()
                    raise
                result = {"audit_id": row["id"], "request_hash": row["request_hash"], "result": json.loads(row["result_json"]), "created": False}
                conn.rollback()
                return result

    def complete_english_world_workbench_action(self, *, audit_id, result):
        with self.get_connection() as conn:
            conn.execute("UPDATE english_world_workbench_audit SET result_json=? WHERE id=? AND json_extract(result_json,'$.pending')=1",
                         (json.dumps(result, ensure_ascii=False, sort_keys=True), audit_id))
            conn.commit()

    def fail_english_world_workbench_action(self, *, audit_id, message):
        with self.get_connection() as conn:
            conn.execute("UPDATE english_world_workbench_audit SET result_json=? WHERE id=? AND json_extract(result_json,'$.pending')=1",
                         (json.dumps({"failed": True, "message": str(message)[:300]}, ensure_ascii=False), audit_id))
            conn.commit()

    def mark_english_world_workbench_dispatch(self, *, audit_id, state, message=None):
        if state not in {"ADMITTED", "FAILED_OR_UNKNOWN"}:
            raise ValueError("Invalid workbench dispatch state")
        with self.get_connection() as conn:
            row = conn.execute("SELECT result_json FROM english_world_workbench_audit WHERE id=?", (audit_id,)).fetchone()
            if not row:
                return
            result = json.loads(row[0])
            result["dispatch_state"] = state
            if message:
                result["dispatch_message"] = str(message)[:300]
            conn.execute("UPDATE english_world_workbench_audit SET result_json=? WHERE id=?",
                          (json.dumps(result, ensure_ascii=False, sort_keys=True), audit_id))
            conn.commit()

    def record_english_world_workbench_action(self, *, audit_id, task_id, action, operation_id,
                                               actor, request_hash, result):
        """持久化幂等回执；唯一键阻止同一操作重复产生副作用。"""
        with self.get_connection() as conn:
            try:
                conn.execute("INSERT INTO english_world_workbench_audit(id,task_id,action,operation_id,actor,request_hash,result_json) VALUES(?,?,?,?,?,?,?)",
                             (audit_id, task_id, action, operation_id, actor, request_hash,
                              json.dumps(result, ensure_ascii=False, sort_keys=True)))
                conn.commit()
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT id,request_hash,result_json FROM english_world_workbench_audit WHERE task_id=? AND action=? AND operation_id=?",
                                   (task_id, action, operation_id)).fetchone()
                if not row:
                    raise
                return {"audit_id": row["id"], "request_hash": row["request_hash"], "result": json.loads(row["result_json"])}
        return {"audit_id": audit_id, "request_hash": request_hash, "result": result}

    def list_english_world_workbench_audit(self, task_id, limit=50):
        with self.get_connection() as conn:
            rows = conn.execute("SELECT id,action,actor,created_at,result_json FROM english_world_workbench_audit WHERE task_id=? ORDER BY created_at DESC LIMIT ?",
                                (task_id, max(1, min(100, int(limit))))).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["result"] = json.loads(item.pop("result_json") or "{}")
                result.append(item)
            return result
