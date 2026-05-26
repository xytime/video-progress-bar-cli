"""数据库访问层 - 管理自动化视频管线的状态与发现列表

所有 SQL 操作必须封装在 PipelineDB 方法内。
禁止外部模块直接调用 get_connection() 执行裸 SQL。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建数据库与DAL封装 |
| 1.1.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 补充 update_video_score / get_high_score_pending_videos，封堵 pipeline_manager 中的裸 SQL 泄漏 |
| 1.2.0 | 2026-05-22 | Gemini_3.1_Pro_High_planning | [红蓝博弈] 加入 WAL 模式与 30s timeout 解决并发锁表危机 |
| 2.0.0 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Phase 1] 黑名单墓碑表、v7.0 新列迁移、人工评分锁、process_pid 追踪、add_video 黑名单前置检查 |
| 2.0.1 | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning | [v7.0 Review Fix] LINT-5: 修宊 add_to_blacklist docstring 调用顺序说明 |
| 2.0.2 | 2026-05-26 | Gemini_3.5_Flash_planning           | [v7.0 Censor Engine] 新增 update_video_censor_status 用于写入内容审查审计数据 |
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
            # [Gemini_3.1_Pro_High_planning] 开启 WAL 模式，支持高并发读写，避免 database is locked
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            
            # 1. 已处理视频状态表 (FSM 状态机)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_id TEXT UNIQUE NOT NULL,
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
                    upload_date TEXT DEFAULT NULL
                )
            ''')
            
            # 2. 频道白名单与推荐表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recommended_channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 3. 动态检查并添加新列 (Schema Migration)
            cursor.execute("PRAGMA table_info(processed_videos)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'zh_title' not in columns:
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN zh_title TEXT")
            if 'source' not in columns:
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN source TEXT DEFAULT 'AUTO'")
            if 'duration_sec' not in columns:
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN duration_sec INTEGER DEFAULT NULL")
            if 'view_count' not in columns:
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN view_count INTEGER DEFAULT NULL")
            if 'like_count' not in columns:
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN like_count INTEGER DEFAULT NULL")
            if 'upload_date' not in columns:
                cursor.execute("ALTER TABLE processed_videos ADD COLUMN upload_date TEXT DEFAULT NULL")

            # [Claude_Sonnet_4.6_Thinking_planning] v7.0 新列迁移（ADD COLUMN only，不影响现有数据）
            _v7_cols = {
                'censor_tag':         "TEXT DEFAULT NULL",
                'censor_score':       "INTEGER DEFAULT NULL",
                'is_manually_scored': "INTEGER DEFAULT 0",
                'process_pid':        "INTEGER DEFAULT NULL",
            }
            for col, definition in _v7_cols.items():
                if col not in columns:
                    cursor.execute(f"ALTER TABLE processed_videos ADD COLUMN {col} {definition}")
                    self._logger.info(f"[Migration] Added column: processed_videos.{col}")

            # [Claude_Sonnet_4.6_Thinking_planning] v7.0 黑名单墓碑表（防止删除后被爬虫二次拉取）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blacklisted_videos (
                    youtube_id TEXT PRIMARY KEY,
                    reason     TEXT DEFAULT 'user_deleted',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 4. 创建复合索引优化分页查询性能
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_updated 
                ON processed_videos(status, updated_at DESC)
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
    ) -> bool:
        # [Claude_Sonnet_4.6_Thinking_planning] v7.0: 前置黑名单检查，防止已删除视频被爬虫二次拉取
        if self.is_blacklisted(youtube_id):
            self._logger.warning(f"[Blacklist] Blocked re-add of blacklisted video: {youtube_id}")
            return False

        with self.get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO processed_videos
                       (youtube_id, title, channel_id, score, status, zh_title, source,
                        duration_sec, view_count, like_count, upload_date)
                       VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?)""",
                    (youtube_id, title, channel_id, score, zh_title, source,
                     duration_sec, view_count, like_count, upload_date)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # Already exists
                
    def update_video_status(self, youtube_id: str, status: str, error_msg: Optional[str] = None):
        """更新视频状态。error_msg=None 时主动清空旧错误信息（用于 retry 场景）。"""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET status = ?, error_msg = ?, updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ?",
                (status, error_msg, youtube_id)
            )
            conn.commit()
            
    def get_videos_by_status(self, status: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM processed_videos WHERE status = ? ORDER BY score DESC", (status,))
            return [dict(row) for row in cursor.fetchall()]

    def claim_video_for_processing(self, youtube_id: str) -> bool:
        """原子地将 PENDING 状态的视频改为 DOWNLOADING，用于防止并发竞争（乐观锁）。
        返回 True 表示抢占成功，可以启动管线处理。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE processed_videos SET status = 'DOWNLOADING', updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ? AND status = 'PENDING'",
                (youtube_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def purge_stale_tasks(self, stale_hours: int = 2) -> int:
        """[Gemini_3.1_Pro_High_planning] 清洗器：将卡在非终态（如 DOWNLOADING）超过 N 小时的任务重置回 PENDING"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE processed_videos 
                SET status = 'PENDING', 
                    retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP 
                WHERE status NOT IN ('COMPLETED', 'FAILED', 'PENDING')
                AND updated_at < datetime('now', ?)
                ''',
                (f'-{stale_hours} hours',)
            )
            conn.commit()
            return cursor.rowcount

    def update_video_score(self, youtube_id: str, score: int, force: bool = False) -> None:
        """更新视频评分。

        此方法封装了原本散落在 pipeline_manager.py 中的裸 SQL 写分逻辑。
        外部模块不得绕过此方法直接操作 score 字段。

        Args:
            youtube_id: 视频 ID。
            score:      新分值。
            force:      为 True 时强制写入（人工调分场景），忽略 is_manually_scored 锁。
                        为 False 时（自动算分场景），若 is_manually_scored=1 则跳过，保护人工设置。
        """
        with self.get_connection() as conn:
            if force:
                # [Claude_Sonnet_4.6_Thinking_planning] 人工调分：同步打上手动锁，后续自动算分不得覆盖
                conn.execute(
                    "UPDATE processed_videos SET score = ?, is_manually_scored = 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ?",
                    (score, youtube_id)
                )
            else:
                # [Claude_Sonnet_4.6_Thinking_planning] 自动算分：仅对未锁定的记录生效
                cursor = conn.execute(
                    "UPDATE processed_videos SET score = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE youtube_id = ? AND is_manually_scored = 0",
                    (score, youtube_id)
                )
                if cursor.rowcount == 0:
                    self._logger.info(f"[ScoreLock] Skipped auto-score for manually-locked video: {youtube_id}")
                    return
            conn.commit()

    def get_high_score_pending_videos(self, min_score: int = 75, limit: int = 5) -> List[Dict[str, Any]]:
        """获取高分待处理视频列表，用于触发加工管线。
        
        此方法封装了原本散落在 pipeline_manager.py 中的裸 SQL 查询逻辑。
        调用方不得自行拼接 score 过滤条件，统一通过此入口。
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos WHERE status = 'PENDING' AND score >= ? ORDER BY score DESC LIMIT ?",
                (min_score, limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_status_counts(self) -> Dict[str, int]:
        """返回各状态下的视频数量，用于仪表盘统计卡片。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM processed_videos GROUP BY status"
            )
            return {row["status"]: row["cnt"] for row in cursor.fetchall()}

    def get_paginated_videos(self, tab: str = 'waitlist', page: int = 1, size: int = 20) -> tuple[List[Dict[str, Any]], int]:
        """按分页和 Tab 类型返回视频列表和总数。"""
        if tab == 'completed':
            condition = "pv.status IN ('PUBLISHED', 'IGNORED', 'COMPLETED')"
        elif tab == 'error':
            condition = "pv.status IN ('FAILED', 'LOGIN_REQUIRED')"
        elif tab == 'active':
            condition = "pv.status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'PUBLISHING')"
        elif tab == 'queue': # 待处理 (满足所有条件，在排队还没进行到)
            condition = "pv.status = 'PENDING' AND pv.score >= 75"
        else: # waitlist (默认，待筛选)
            condition = "pv.status = 'PENDING' AND pv.score < 75"
            
        offset = (page - 1) * size
        with self.get_connection() as conn:
            # 获取总数
            cursor = conn.execute(
                f"SELECT COUNT(*) as cnt FROM processed_videos pv WHERE {condition}"
            )
            total_count = cursor.fetchone()["cnt"]
            
            # 获取分页数据，LEFT JOIN 带出频道名称
            cursor = conn.execute(
                f"""SELECT pv.*, COALESCE(rc.channel_name, pv.channel_id) AS channel_name
                    FROM processed_videos pv
                    LEFT JOIN recommended_channels rc ON pv.channel_id = rc.channel_id
                    WHERE {condition}
                    ORDER BY pv.updated_at DESC LIMIT ? OFFSET ?""",
                (size, offset)
            )
            videos = [dict(row) for row in cursor.fetchall()]
            
        return videos, total_count

    def get_tab_counts(self) -> Dict[str, int]:
        """获取各 Tab 的当前数量"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    SUM(CASE WHEN status = 'PENDING' AND score < 75 THEN 1 ELSE 0 END) as waitlist,
                    SUM(CASE WHEN status = 'PENDING' AND score >= 75 THEN 1 ELSE 0 END) as queue,
                    SUM(CASE WHEN status IN ('DOWNLOADING', 'TRANSCRIBING', 'COPYWRITING', 'PUBLISHING') THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN status IN ('PUBLISHED', 'IGNORED', 'COMPLETED') THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status IN ('FAILED', 'LOGIN_REQUIRED') THEN 1 ELSE 0 END) as error
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
        """从频道白名单中删除指定频道。"""
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
        """按 channel_id 精确查找频道记录，用于重复检查。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM recommended_channels WHERE channel_id = ?",
                (channel_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_video_by_youtube_id(self, youtube_id: str) -> Optional[Dict[str, Any]]:
        """按 youtube_id 精确查找视频记录，用于重复检查。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos WHERE youtube_id = ?",
                (youtube_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


    def delete_video_record(self, youtube_id: str) -> bool:
        """物理删除视频记录"""
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM processed_videos WHERE youtube_id = ?",
                    (youtube_id,)
                )
                conn.commit()
                return True
            except Exception as e:
                self._logger.error(f"delete_video_record failed for {youtube_id}: {e}")
                return False

    # --- v7.0 Blacklist DAL [Claude_Sonnet_4.6_Thinking_planning] ---

    def add_to_blacklist(self, youtube_id: str, reason: str = 'user_deleted') -> bool:
        """将视频 ID 写入黑名单墓碑表。

        [Claude_Sonnet_4.6_Thinking_planning] LINT-5 修复: 正确的原常保证调用顺序是《先写墓碑、再删主记录》。
        这样可以防止删除窗口期内爬虫二次插入（墓碑写入即封堵入口，小于 1ms）。
        即: add_to_blacklist() 先调用，再调用 delete_video_record()。
        
        此操作不可逆（设计上）。
        """
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
        """检查视频是否在黑名单中（爬虫插入前的前置校验）。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM blacklisted_videos WHERE youtube_id = ?",
                (youtube_id,)
            )
            return cursor.fetchone() is not None

    def update_process_pid(self, youtube_id: str, pid: Optional[int]) -> None:
        """记录或清除当前处理该视频的子进程组 ID（用于 SIGTERM 精准击杀）。"""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET process_pid = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE youtube_id = ?",
                (pid, youtube_id)
            )
            conn.commit()

    def update_video_censor_status(self, youtube_id: str, tag: Optional[str], score: Optional[int]) -> None:
        """更新视频的安全审查标签与分值。"""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET censor_tag = ?, censor_score = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ?",
                (tag, score, youtube_id)
            )
            conn.commit()

    def set_manually_scored(self, youtube_id: str, locked: bool = True) -> None:
        """设置或解除人工评分锁。

        locked=True: 人工调分后锁定，自动算分不得覆盖。
        locked=False: 硬重置时解锁，恢复自动算分。
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET is_manually_scored = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ?",
                (1 if locked else 0, youtube_id)
            )
            conn.commit()
