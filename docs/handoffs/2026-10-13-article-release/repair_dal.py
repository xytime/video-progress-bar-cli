"""本次上线专用 DAL：只将已授权孤儿记录隔离，绝不重新入队。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-13 | Codex | 单条原值 CAS、提交证据拒绝、事务写入范围校验 |
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from video_processing.db.database import PipelineDB as BasePipelineDB

TARGET = {"id": 5787, "youtube_id": "KSILOEIGvkw", "slice_index": 0,
          "status": "PROCESSING", "process_pid": None, "retry_count": 0,
          "created_at": "2026-10-13 09:40:12", "updated_at": "2026-10-13 09:40:24"}
REASON = "MAINTENANCE_ORPHAN_HELD: 已授权隔离无主 PROCESSING；保留任务，人工确认前禁止重试或发布"
CHANGED = {"status", "publication_review_required", "error_msg", "updated_at"}
LEDGERS = ("wechat_publications", "wechat_submission_attempts",
           "wechat_publications_historical_archive", "wechat_upload_retries",
           "douyin_publications", "kuaishou_publications")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str).encode()).hexdigest()


class PipelineDB(BasePipelineDB):
    """一次性运维 DAL；不安装到生产业务路径，不允许通用目标参数。"""

    @staticmethod
    def verify_recovery_backup(path, proof):
        path = Path(path).resolve()
        wal = Path(str(path) + '-wal')
        if (str(path) != proof.get('path') or (wal.exists() and wal.stat().st_size)
                or hashlib.sha256(path.read_bytes()).hexdigest() != proof.get('sha256')):
            return False
        # backup() 完成后封存的单文件副本不应尝试创建 WAL/SHM。
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as conn:
            return conn.execute('PRAGMA integrity_check').fetchall() == [('ok',)]

    @staticmethod
    def repair_snapshot(path, *, verified_backup=False):
        # immutable 只用于已验证的一致性备份；活库必须正常读取 WAL。
        suffix = "?mode=ro&immutable=1" if verified_backup else "?mode=ro"
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + suffix, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM processed_videos WHERE id=?", (TARGET["id"],)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def hold_authorized_orphan(path, expected):
        """调用方须持真实维护锁及部署锁；完整原值相等才进行唯一 UPDATE。"""
        if not isinstance(expected, dict) or any(expected.get(k) != v for k, v in TARGET.items()):
            raise ValueError("TARGET_NOT_AUTHORIZED")
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM processed_videos WHERE id=?", (TARGET["id"],)).fetchone()
                if row is None or dict(row) != expected:
                    raise ValueError("RECORD_DRIFT")
                # 任何相关提交/发布记录均阻断，包括失败、未知和历史归档记录。
                ledger_before = {}
                for table in LEDGERS:
                    if conn.execute(f'SELECT 1 FROM "{table}" WHERE video_id=? LIMIT 1', (TARGET["id"],)).fetchone():
                        raise ValueError("SUBMISSION_EVIDENCE_PRESENT")
                    ledger_before[table] = digest([dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')])
                # 禁止触发器或意外 SQL 改写其他表/字段；不是关闭业务 DAL 的维护保护。
                def authorize(action, table, column, _database, _trigger):
                    if action == sqlite3.SQLITE_UPDATE:
                        return sqlite3.SQLITE_OK if table == "processed_videos" and column in CHANGED else sqlite3.SQLITE_DENY
                    if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE}:
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                conn.set_authorizer(authorize)
                count = conn.execute("""UPDATE processed_videos SET status='FAILED',
                    publication_review_required=1, error_msg=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND youtube_id=? AND slice_index=0 AND status='PROCESSING'
                      AND process_pid IS NULL AND retry_count=0 AND created_at=? AND updated_at=?""",
                    (REASON, TARGET["id"], TARGET["youtube_id"], TARGET["created_at"], TARGET["updated_at"])).rowcount
                after = dict(conn.execute("SELECT * FROM processed_videos WHERE id=?", (TARGET["id"],)).fetchone())
                if count != 1 or conn.total_changes != 1 or any(after[k] != v for k, v in expected.items() if k not in CHANGED):
                    raise ValueError("WRITE_SCOPE_MISMATCH")
                ledger_after = {table: digest([dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]) for table in LEDGERS}
                if ledger_before != ledger_after:
                    raise ValueError("LEDGER_CHANGED")
            return {"before": expected, "after": after, "ledger_hashes": ledger_after,
                    "updated_rows": 1, "retry_count_preserved": True, "enqueued": False}
