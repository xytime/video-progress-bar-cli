"""本次部署专用 DAL：按已存在的抖音审核账本准确收尾一条总任务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-17 | Codex | 固定对象、完整原值 CAS、唯一行列更新及其他账本哈希保护 |
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from video_processing.db.database import PipelineDB as BasePipelineDB

TARGET = {"id": 6133, "youtube_id": "local-baiju-investment-legends-20261017",
          "slice_index": 0, "status": "PUBLISHING", "process_pid": None,
          "retry_count": 0, "created_at": "2026-10-17 03:57:56",
          "updated_at": "2026-10-17 03:57:56"}
PUBLICATION = {"id": 770, "video_id": 6133, "state": "UNDER_REVIEW",
               "asset_sha256": "fb0b803f02d470db14dd2f83c17aa615b6098bcb101f46894aaf4a8d06911194",
               "attempt_count": 1, "attempt_number": 1,
               "updated_at": "2026-10-17 03:59:31"}
CHANGED = {"status", "error_msg", "updated_at"}
LEDGERS = ("wechat_publications", "wechat_submission_attempts",
           "wechat_publications_historical_archive", "wechat_upload_retries",
           "douyin_publications", "kuaishou_publications")
REASON = "MAINTENANCE_RECONCILED: 抖音账本770已UNDER_REVIEW；仅总任务收尾，不代表公开发布，不重试或重传。"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str).encode()).hexdigest()


class PipelineDB(BasePipelineDB):
    """独立一次性维护 DAL，不替换生产业务 DAL，不初始化或迁移数据库。"""

    @staticmethod
    def verify_backup(path, proof):
        path = Path(path).resolve()
        wal = Path(str(path) + "-wal")
        if (str(path) != proof.get("path") or (wal.exists() and wal.stat().st_size)
                or hashlib.sha256(path.read_bytes()).hexdigest() != proof.get("sha256")):
            return False
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
            return conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]

    @staticmethod
    def _snapshot(conn):
        row = conn.execute("SELECT * FROM processed_videos WHERE id=?", (TARGET["id"],)).fetchone()
        pub = conn.execute("SELECT * FROM douyin_publications WHERE id=?", (PUBLICATION["id"],)).fetchone()
        return {"video": dict(row) if row else None, "publication": dict(pub) if pub else None,
                "ledger_hashes": {table: digest([dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')])
                                  for table in LEDGERS}}

    @staticmethod
    def snapshot(path):
        # 活库正常读取 WAL，不使用 immutable；没有业务写入和构造器副作用。
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            return PipelineDB._snapshot(conn)

    @staticmethod
    def reconcile(path, expected):
        """调用方持真实维护互斥与部署锁；只将一条假在途对齐既有审核状态。"""
        if (not isinstance(expected, dict) or not isinstance(expected.get("video"), dict)
                or not isinstance(expected.get("publication"), dict)
                or any(expected["video"].get(k) != v for k, v in TARGET.items())
                or any(expected["publication"].get(k) != v for k, v in PUBLICATION.items())):
            raise ValueError("TARGET_OR_SUBMISSION_NOT_CONFIRMED")
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                if PipelineDB._snapshot(conn) != expected:
                    raise ValueError("RECORD_OR_LEDGER_DRIFT")
                for table in LEDGERS:
                    if table != "douyin_publications" and conn.execute(
                            f'SELECT 1 FROM "{table}" WHERE video_id=? LIMIT 1', (TARGET["id"],)).fetchone():
                        raise ValueError("OTHER_SUBMISSION_PRESENT")
                if conn.execute("SELECT COUNT(*) FROM douyin_publications WHERE video_id=?", (TARGET["id"],)).fetchone()[0] != 1:
                    raise ValueError("AMBIGUOUS_SUBMISSION")

                def authorize(action, table, column, _database, trigger):
                    if action == sqlite3.SQLITE_UPDATE:
                        return sqlite3.SQLITE_OK if table == "processed_videos" and column in CHANGED and not trigger else sqlite3.SQLITE_DENY
                    if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE,
                                  sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE,
                                  sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX}:
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                conn.set_authorizer(authorize)
                count = conn.execute("""UPDATE processed_videos SET status='UNDER_REVIEW',
                    error_msg=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND youtube_id=? AND slice_index=0 AND status='PUBLISHING'
                      AND process_pid IS NULL AND retry_count=0 AND created_at=? AND updated_at=?""",
                    (REASON, TARGET["id"], TARGET["youtube_id"], TARGET["created_at"], TARGET["updated_at"])).rowcount
                after = PipelineDB._snapshot(conn)
                if (count != 1 or conn.total_changes != 1
                        or any(after["video"][k] != v for k, v in expected["video"].items() if k not in CHANGED)
                        or after["publication"] != expected["publication"]
                        or after["ledger_hashes"] != expected["ledger_hashes"]):
                    raise ValueError("WRITE_SCOPE_MISMATCH")
            return {"before": expected, "after": after, "updated_rows": 1,
                    "enqueued": False, "uploaded": False, "public_success_claimed": False}
