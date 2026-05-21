"""数据库访问层 - 管理自动化视频管线的状态与发现列表

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建数据库与DAL封装 |
"""
import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

class PipelineDB:
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
                
    def update_video_status(self, youtube_id: str, status: str, error_msg: str = None):
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
