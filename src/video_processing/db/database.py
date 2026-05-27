"""数据库访问层 - 管理自动化视频管线的状态与发现列表

所有 SQL 操作必须封装在 PipelineDB 方法内。
禁止外部模块直接调用 get_connection() 执行裸 SQL。

# Modification History
| Version | Date       | Author                              | Description                                                                    |
|---------|------------|-------------------------------------|--------------------------------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建数据库与DAL封装                                                         |
| 2.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | v7.0 架构升级：黑名单表、Pid追踪、手动评分锁                                      |
| 2.5.0   | 2026-05-27 | Gemini_3.5_Flash_planning           | 一变多升级：复合唯一约束(youtube_id, slice_index)、自关联外键级联删除与批量插入 |
| 2.5.1   | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 修复 _init_db 中遗漏推荐频道表 recommended_channels 的创建问题 |
| 2.5.2   | 2026-05-27 | Gemini_3.5_Flash_High_planning      | 新增 get_detailed_stats 方法提供父子任务的细分状态统计数据 |
| 2.5.3   | 2026-05-27 | Unknown_Model_planning              | 修复已分片(SEGMENTED)父视频在后台仪表盘各 Tab 中隐藏不可见的 Bug |
"""

import sqlite3
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

class PipelineDB:
    """视频管线数据访问层。

    所有 SQL 操作必须通过此类的方法执行。
    外部模块禁止直接调用 get_connection() 执行裸 SQL。
    """

    _logger = logging.getLogger(__name__)

    def __init__(self, db_path: str = "pipeline.db"):
        # 默认在项目根目录的 output 文件夹内创建数据库
        # 如果是绝对路径则直接使用
        if not os.path.isabs(db_path):
            base_dir = Path(__file__).parent.parent.parent.parent
            self.db_path = str(base_dir / "output" / db_path)
        else:
            self.db_path = db_path
            
        # 确保目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
        
    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # [Gemini_3.5_Flash_planning] 开启 WAL 模式，支持高并发读写，并激活 SQLite 外键支持
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            
            # [Gemini_3.5_Flash_High_planning] 重新加入推荐频道表的创建，防测试环境与空数据库丢失此表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recommended_channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 检测是否已经进行了复合键和自关联级联删除的表升级 (检查 parent_id 列是否存在)
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if columns and "parent_id" not in columns:
                self._logger.info("[Migration] Upgrading database schema to composite keys (yid, slice_index) & parent_id cascade relation...")
                # 使用隐式事务，不再手动 BEGIN IMMEDIATE 避免 OperationalError
                try:
                    # 1. 重命名原表
                    cursor.execute("ALTER TABLE processed_videos RENAME TO processed_videos_old;")
                    
                    # 2. 创建支持复合主键和外键级联删除的新表
                    cursor.execute('''
                        CREATE TABLE processed_videos (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            youtube_id TEXT NOT NULL,
                            slice_index INTEGER NOT NULL DEFAULT 0,
                            parent_id INTEGER DEFAULT NULL,
                            title TEXT NOT NULL,
                            channel_id TEXT NOT NULL,
                            score INTEGER DEFAULT 0,
                            status TEXT NOT NULL DEFAULT 'PENDING',
                            retry_count INTEGER DEFAULT 0,
                            error_msg TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            zh_title TEXT,
                            source TEXT DEFAULT 'AUTO',
                            duration_sec INTEGER DEFAULT NULL,
                            view_count INTEGER DEFAULT NULL,
                            like_count INTEGER DEFAULT NULL,
                            upload_date TEXT DEFAULT NULL,
                            censor_tag TEXT DEFAULT NULL,
                            censor_score INTEGER DEFAULT NULL,
                            is_manually_scored INTEGER DEFAULT 0,
                            process_pid INTEGER DEFAULT NULL,
                            trim_start TEXT DEFAULT NULL,
                            trim_end TEXT DEFAULT NULL,
                            UNIQUE(youtube_id, slice_index),
                            FOREIGN KEY(parent_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                        )
                    ''')
                    
                    # 3. 提取旧表字段并导入新表（设置默认 slice_index=0, parent_id=NULL）
                    old_fields = [
                        "id", "youtube_id", "title", "channel_id", "score", "status", "retry_count", 
                        "error_msg", "created_at", "updated_at", "zh_title", "source", "duration_sec", 
                        "view_count", "like_count", "upload_date"
                    ]
                    # v7 系列列
                    for col in ["censor_tag", "censor_score", "is_manually_scored", "process_pid", "trim_start", "trim_end"]:
                        if col in columns:
                            old_fields.append(col)
                            
                    old_fields_str = ", ".join(old_fields)
                    
                    new_fields = [
                        "id", "youtube_id", "slice_index", "parent_id", "title", "channel_id", "score", 
                        "status", "retry_count", "error_msg", "created_at", "updated_at", "zh_title", 
                        "source", "duration_sec", "view_count", "like_count", "upload_date"
                    ]
                    for col in ["censor_tag", "censor_score", "is_manually_scored", "process_pid", "trim_start", "trim_end"]:
                        if col in columns:
                            new_fields.append(col)
                    new_fields_str = ", ".join(new_fields)
                    
                    # 导回，在 id, youtube_id 后补上常量 0 和 NULL
                    select_fields_str = "id, youtube_id, 0, NULL, " + ", ".join(old_fields[2:])
                    
                    cursor.execute(f"""
                        INSERT INTO processed_videos ({new_fields_str})
                        SELECT {select_fields_str}
                        FROM processed_videos_old
                    """)
                    
                    # 4. 删除旧表
                    cursor.execute("DROP TABLE processed_videos_old;")
                    
                    conn.commit()
                    self._logger.info("[Migration] Database schema successfully migrated.")
                except Exception as e:
                    conn.rollback()
                    self._logger.error(f"[Migration] Schema migration failed, rolled back: {e}")
                    raise e
            elif not columns:
                # 第一次初始建表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processed_videos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        youtube_id TEXT NOT NULL,
                        slice_index INTEGER NOT NULL DEFAULT 0,
                        parent_id INTEGER DEFAULT NULL,
                        title TEXT NOT NULL,
                        channel_id TEXT NOT NULL,
                        score INTEGER DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        retry_count INTEGER DEFAULT 0,
                        error_msg TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        zh_title TEXT,
                        source TEXT DEFAULT 'AUTO',
                        duration_sec INTEGER DEFAULT NULL,
                        view_count INTEGER DEFAULT NULL,
                        like_count INTEGER DEFAULT NULL,
                        upload_date TEXT DEFAULT NULL,
                        censor_tag TEXT DEFAULT NULL,
                        censor_score INTEGER DEFAULT NULL,
                        is_manually_scored INTEGER DEFAULT 0,
                        process_pid INTEGER DEFAULT NULL,
                        trim_start TEXT DEFAULT NULL,
                        trim_end TEXT DEFAULT NULL,
                        UNIQUE(youtube_id, slice_index),
                        FOREIGN KEY(parent_id) REFERENCES processed_videos(id) ON DELETE CASCADE
                    )
                ''')
            
            # [Claude_Sonnet_4.6_Thinking_planning] v7.0 黑名单墓碑表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blacklisted_videos (
                    youtube_id TEXT PRIMARY KEY,
                    reason     TEXT DEFAULT 'user_deleted',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 4. 创建复合索引优化分页查询与状态调度性能
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_updated 
                ON processed_videos(status, updated_at DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_score_created
                ON processed_videos(status, score, created_at DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_score_updated
                ON processed_videos(status, score, updated_at DESC)
            ''')
            
            # [Gemini_3.5_Flash_planning] 新建 parent_id 索引提升自关联级联删除与关联查询速度
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_parent_id
                ON processed_videos(parent_id)
            ''')
            
            conn.commit()

    # --- Channel DAL ---
    def add_channel(self, channel_id: str, channel_name: str, status: str = 'APPROVED', reason: str = '') -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO recommended_channels (channel_id, channel_name, reason, status) VALUES (?, ?, ?, ?)",
                    (channel_id, channel_name, reason, status)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"add_channel failed for {channel_id}: {e}")
                return False
                
    def get_approved_channels(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM recommended_channels WHERE status = 'APPROVED'")
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_channels(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM recommended_channels WHERE status = 'PENDING'")
            return [dict(row) for row in cursor.fetchall()]

    def update_channel_status(self, channel_id: str, status: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE recommended_channels SET status = ? WHERE channel_id = ?", (status, channel_id))
            conn.commit()

    # --- Video DAL ---
    def add_video(
        self,
        youtube_id: str,
        title: str,
        channel_id: str,
        score: int = 0,
        zh_title: Optional[str] = None,
        source: str = 'AUTO',
        duration_sec: Optional[int] = None,
        view_count: Optional[int] = None,
        like_count: Optional[int] = None,
        upload_date: Optional[str] = None,
        trim_start: Optional[str] = None,
        trim_end: Optional[str] = None,
        slice_index: int = 0,                       # [Gemini_3.5_Flash_planning] 新增：切片索引，默认0 (主视频)
        parent_id: Optional[int] = None,            # [Gemini_3.5_Flash_planning] 新增：父自增 ID
    ) -> bool:
        # 前置黑名单检查，防止已删除视频被二次拉取
        if self.is_blacklisted(youtube_id):
            if source == 'MANUAL':
                self.remove_from_blacklist(youtube_id)
            else:
                self._logger.warning(f"[Blacklist] Blocked re-add of blacklisted video: {youtube_id}")
                return False

        with self.get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO processed_videos
                       (youtube_id, slice_index, parent_id, title, channel_id, score, status, zh_title, source,
                        duration_sec, view_count, like_count, upload_date, trim_start, trim_end)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (youtube_id, slice_index, parent_id, title, channel_id, score, zh_title, source,
                     duration_sec, view_count, like_count, upload_date, trim_start, trim_end)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # Already exists (youtube_id + slice_index duplicate)

    def batch_add_videos(self, videos: List[Dict[str, Any]]) -> bool:
        """[Gemini_3.1_Pro_High_planning] 批量插入子任务列表，使用 executemany 配合自动事务，规避性能与死锁问题"""
        if not videos:
            return True
            
        with self.get_connection() as conn:
            # 1. 批量查询黑名单
            yids = list(set(v.get("youtube_id") for v in videos if v.get("youtube_id")))
            blacklisted = set()
            if yids:
                placeholders = ",".join(["?"] * len(yids))
                cursor = conn.execute(f"SELECT youtube_id FROM blacklisted_videos WHERE youtube_id IN ({placeholders})", yids)
                blacklisted = {row["youtube_id"] for row in cursor.fetchall()}
                
            # 2. 准备插入数据
            insert_data = []
            for v in videos:
                yid = v.get("youtube_id")
                source = v.get("source", "AUTO")
                if yid in blacklisted and source != "MANUAL":
                    continue
                    
                insert_data.append((
                    yid, v.get("slice_index", 0), v.get("parent_id"), v.get("title"), v.get("channel_id"),
                    v.get("score", 0), v.get("zh_title"), source, v.get("duration_sec"), v.get("view_count"),
                    v.get("like_count"), v.get("upload_date"), v.get("trim_start"), v.get("trim_end")
                ))
            
            if not insert_data:
                return True
                
            try:
                conn.executemany(
                    """INSERT INTO processed_videos
                       (youtube_id, slice_index, parent_id, title, channel_id, score, status, zh_title, source,
                        duration_sec, view_count, like_count, upload_date, trim_start, trim_end)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    insert_data
                )
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                self._logger.error(f"[DB] batch_add_videos failed: {e}")
                return False

    def update_video_status(self, youtube_id: str, status: str, error_msg: Optional[str] = None, slice_index: int = 0):
        """更新指定联合键 (youtube_id, slice_index) 视频的状态。"""
        # [Gemini_3.5_Flash_planning] 更新定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET status = ?, error_msg = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (status, error_msg, youtube_id, slice_index)
            )
            conn.commit()
            
    def get_videos_by_status(self, status: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM processed_videos WHERE status = ? ORDER BY score DESC", (status,))
            return [dict(row) for row in cursor.fetchall()]

    def claim_video_for_processing(self, youtube_id: str, slice_index: int = 0) -> bool:
        """原子地将 PENDING 状态的特定切片任务改为 DOWNLOADING，用于防止并发抢占。"""
        # [Gemini_3.5_Flash_planning] 抢占定位增加 slice_index = ?
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET status = 'DOWNLOADING', updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ? AND status = 'PENDING'",
                (youtube_id, slice_index)
            )
            conn.commit()
            return cursor.rowcount > 0

    def purge_stale_tasks(self, stale_hours: int = 2) -> int:
        """清洗器：将卡在非终态（如 DOWNLOADING）超过 N 小时的任务重置回 PENDING"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE processed_videos 
                SET status = 'PENDING', 
                    retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP 
                WHERE status NOT IN ('COMPLETED', 'FAILED', 'PENDING', 'PUBLISHED')
                AND updated_at < datetime('now', ?)
                ''',
                (f'-{stale_hours} hours',)
            )
            conn.commit()
            return cursor.rowcount

    def update_video_score(self, youtube_id: str, score: int, force: bool = False, slice_index: int = 0) -> None:
        """更新特定切片的评分，支持评分锁保护。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            if force:
                conn.execute(
                    "UPDATE processed_videos SET score = ?, is_manually_scored = 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                    (score, youtube_id, slice_index)
                )
            else:
                cursor = conn.execute(
                    "UPDATE processed_videos SET score = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE youtube_id = ? AND slice_index = ? AND is_manually_scored = 0",
                    (score, youtube_id, slice_index)
                )
                if cursor.rowcount == 0:
                    self._logger.info(f"[ScoreLock] Skipped auto-score for manually-locked video: {youtube_id} (slice {slice_index})")
                    return
            conn.commit()

    def get_high_score_pending_videos(self, min_score: int = 75, limit: int = 5) -> List[Dict[str, Any]]:
        """获取高分待处理视频列表。包括主视频(slice_index=0)和切片子视频均在此获取排队。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos WHERE status = 'PENDING' AND score >= ? ORDER BY score DESC LIMIT ?",
                (min_score, limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_status_counts(self) -> Dict[str, int]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos GROUP BY status"
            )
            return {row["status"]: row["cnt"] for row in cursor.fetchall()}

    def get_detailed_stats(self) -> Dict[str, Any]:
        """[Gemini_3.5_Flash_High_planning] 分别统计父任务与切片子任务在各状态下的数量"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos WHERE parent_id IS NULL GROUP BY status"
            )
            parents = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos WHERE parent_id IS NOT NULL GROUP BY status"
            )
            children = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            return {
                "parents": parents,
                "children": children
            }

    def get_paginated_videos(self, tab: str = 'waitlist', page: int = 1, size: int = 20) -> tuple[List[Dict[str, Any]], int]:
        """按分页和 Tab 类型返回视频列表和总数。
        为了在折叠树中优雅呈现，在此查询时，主列表仅返回主任务（parent_id IS NULL 且 slice_index = 0）。
        """
        # [Gemini_3.5_Flash_planning] 增加了 parent_id IS NULL 的前置过滤，实现主列表仅展现主任务，切片在树形中折叠
        if tab == 'completed':
            # [Unknown_Model_planning] 包括已分集(SEGMENTED)的父任务，以便在已完成列表中查看和展开
            condition = "pv.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED', 'SEGMENTED') AND pv.parent_id IS NULL"
        elif tab == 'error':
            condition = "pv.status IN ('FAILED', 'LOGIN_REQUIRED') AND pv.parent_id IS NULL"
        elif tab == 'active':
            condition = "pv.status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'PUBLISHING') AND pv.parent_id IS NULL"
        elif tab == 'queue':
            condition = "pv.status = 'PENDING' AND pv.score >= 75 AND pv.parent_id IS NULL"
        else:
            condition = "pv.status = 'PENDING' AND pv.score < 75 AND pv.parent_id IS NULL"

        order_col = "pv.created_at" if tab == 'waitlist' else "pv.updated_at"
        offset = (page - 1) * size
        
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"SELECT COUNT(*) as cnt FROM processed_videos pv WHERE {condition}"
            )
            total_count = cursor.fetchone()["cnt"]

            # [Gemini_3.5_Flash_planning] 查询时，利用子查询带出子切片数量 count
            cursor = conn.execute(
                f"""SELECT pv.*, COALESCE(rc.channel_name, pv.channel_id) AS channel_name,
                           (SELECT COUNT(*) FROM processed_videos sub WHERE sub.parent_id = pv.id) AS slices_count
                    FROM processed_videos pv
                    LEFT JOIN recommended_channels rc ON pv.channel_id = rc.channel_id
                    WHERE {condition}
                    ORDER BY {order_col} DESC LIMIT ? OFFSET ?""",
                (size, offset)
            )
            videos = [dict(row) for row in cursor.fetchall()]

        return videos, total_count

    def get_slices_by_parent_yid(self, parent_yid: str) -> List[Dict[str, Any]]:
        """[Gemini_3.5_Flash_planning] 新增：按父任务 youtube_id 提取其下所有关联子切片元数据"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT sub.*, parent.youtube_id AS parent_youtube_id
                   FROM processed_videos sub
                   JOIN processed_videos parent ON sub.parent_id = parent.id
                   WHERE parent.youtube_id = ? AND sub.slice_index > 0
                   ORDER BY sub.slice_index ASC""",
                (parent_yid,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_tab_counts(self) -> Dict[str, int]:
        """获取各 Tab 的当前数量（仅统计 parent_id IS NULL 级别的父视频，清爽管理）"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    SUM(CASE WHEN status = 'PENDING' AND score < 75 AND parent_id IS NULL THEN 1 ELSE 0 END) as waitlist,
                    SUM(CASE WHEN status = 'PENDING' AND score >= 75 AND parent_id IS NULL THEN 1 ELSE 0 END) as queue,
                    SUM(CASE WHEN status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'PUBLISHING') AND parent_id IS NULL THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN status IN ('PUBLISHED', 'IGNORED', 'COMPLETED', 'SEGMENTED') AND parent_id IS NULL THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status IN ('FAILED', 'LOGIN_REQUIRED') AND parent_id IS NULL THEN 1 ELSE 0 END) as error
                FROM processed_videos
            """)
            row = cursor.fetchone()
            if row:
                return {
                    "waitlist": row["waitlist"] or 0,
                    "queue": row["queue"] or 0,
                    "active": row["active"] or 0,
                    "completed": row["completed"] or 0,
                    "error": row["error"] or 0,
                }
            return {"waitlist": 0, "queue": 0, "active": 0, "completed": 0, "error": 0}

    def delete_channel(self, channel_id: str) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM recommended_channels WHERE channel_id = ?",
                    (channel_id,)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_channel failed for {channel_id}: {e}")
                return False

    def get_channel_by_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM recommended_channels WHERE channel_id = ?",
                (channel_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_video_by_youtube_id(self, youtube_id: str, slice_index: int = 0) -> Optional[Dict[str, Any]]:
        """按 youtube_id 和 slice_index 精确查找视频记录，用于重复检查。"""
        # [Gemini_3.5_Flash_planning] 校验增加了 slice_index = ?
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                (youtube_id, slice_index)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_video_record(self, youtube_id: str, slice_index: Optional[int] = None) -> bool:
        """物理删除视频记录。如果 slice_index 传入 None，删除父及所有关联子视频；否则只删除单切片。"""
        # [Gemini_3.5_Flash_planning] 支持分级删除。级联删除靠 FOREIGN KEY ... REFERENCES ... ON DELETE CASCADE 实现
        with self.get_connection() as conn:
            try:
                if slice_index is None:
                    conn.execute(
                        "DELETE FROM processed_videos WHERE youtube_id = ?",
                        (youtube_id,)
                    )
                else:
                    conn.execute(
                        "DELETE FROM processed_videos WHERE youtube_id = ? AND slice_index = ?",
                        (youtube_id, slice_index)
                    )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_video_record failed for {youtube_id} (slice {slice_index}): {e}")
                return False

    def batch_delete_video_records(self, youtube_ids: List[str], tombstone: bool = True) -> tuple[int, List[str]]:
        if not youtube_ids:
            return 0, []

        deleted = 0
        failed: List[str] = []
        with self.get_connection() as conn:
            try:
                if tombstone:
                    for yid in youtube_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO blacklisted_videos (youtube_id, reason) VALUES (?, ?)",
                            (yid, "user_deleted")
                        )
                placeholders = ",".join(["?"] * len(youtube_ids))
                cursor = conn.execute(
                    f"DELETE FROM processed_videos WHERE youtube_id IN ({placeholders})",
                    youtube_ids
                )
                deleted = cursor.rowcount
                conn.commit()
            except Exception as e:
                self._logger.error(f"batch_delete_video_records failed: {e}")
                failed = list(youtube_ids)
        return deleted, failed

    def add_to_blacklist(self, youtube_id: str, reason: str = 'user_deleted') -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO blacklisted_videos (youtube_id, reason) VALUES (?, ?)",
                    (youtube_id, reason)
                )
                conn.commit()
                self._logger.info(f"[Blacklist] Added: {youtube_id} ({reason})")
                return True
            except Exception as e:
                self._logger.error(f"add_to_blacklist failed for {youtube_id}: {e}")
                return False

    def is_blacklisted(self, youtube_id: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM blacklisted_videos WHERE youtube_id = ?",
                (youtube_id,)
            )
            return cursor.fetchone() is not None

    def remove_from_blacklist(self, youtube_id: str) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM blacklisted_videos WHERE youtube_id = ?",
                    (youtube_id,)
                )
                conn.commit()
                self._logger.info(f"[Blacklist] Removed from blacklist: {youtube_id}")
                return True
            except Exception as e:
                self._logger.error(f"remove_from_blacklist failed for {youtube_id}: {e}")
                return False

    def update_process_pid(self, youtube_id: str, pid: Optional[int], slice_index: int = 0) -> None:
        """记录或清除特定切片视频关联的处理进程组 ID。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET process_pid = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ? AND slice_index = ?",
                (pid, youtube_id, slice_index)
            )
            conn.commit()

    def update_video_censor_status(self, youtube_id: str, tag: Optional[str], score: Optional[int], slice_index: int = 0) -> None:
        """更新特定切片的违禁词过滤状态。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET censor_tag = ?, censor_score = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                (tag, score, youtube_id, slice_index)
            )
            conn.commit()

    def set_manually_scored(self, youtube_id: str, locked: bool = True, slice_index: int = 0) -> None:
        """设置或解除特定视频/切片的人工评分锁。"""
        # [Gemini_3.5_Flash_planning] 定位增加 slice_index = ?
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET is_manually_scored = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND slice_index = ?",
                (1 if locked else 0, youtube_id, slice_index)
            )
            conn.commit()
