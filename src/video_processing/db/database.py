"""数据库访问层 - 管理自动化视频管线的状态与发现列表

所有 SQL 操作必须封装在 PipelineDB 方法内。
禁止外部模块直接调用 get_connection() 执行裸 SQL。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建数据库与DAL封装 |
| 1.1.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 补充 update_video_score / get_high_score_pending_videos，封堵 pipeline_manager 中的裸 SQL 泄漏 |
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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
        
    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    def add_video(self, youtube_id: str, title: str, channel_id: str, score: int = 0) -> bool:
        with self.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO processed_videos (youtube_id, title, channel_id, score, status) VALUES (?, ?, ?, ?, 'PENDING')",
                    (youtube_id, title, channel_id, score)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False # Already exists
                
    def update_video_status(self, youtube_id: str, status: str, error_msg: Optional[str] = None):
        with self.get_connection() as conn:
            if error_msg:
                conn.execute(
                    "UPDATE processed_videos SET status = ?, error_msg = ?, updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ?",
                    (status, error_msg, youtube_id)
                )
            else:
                conn.execute(
                    "UPDATE processed_videos SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ?",
                    (status, youtube_id)
                )
            conn.commit()
            
    def get_videos_by_status(self, status: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM processed_videos WHERE status = ? ORDER BY score DESC", (status,))
            return [dict(row) for row in cursor.fetchall()]

    def update_video_score(self, youtube_id: str, score: int) -> None:
        """更新视频评分。
        
        此方法封装了原本散落在 pipeline_manager.py 中的裸 SQL 写分逻辑。
        外部模块不得绕过此方法直接操作 score 字段。
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE processed_videos SET score = ?, updated_at = CURRENT_TIMESTAMP WHERE youtube_id = ?",
                (score, youtube_id)
            )
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

    def get_recent_videos(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回最近更新的视频列表，用于仪表盘动态活动流。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM processed_videos ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

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


