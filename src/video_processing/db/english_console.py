"""英语世界管理台只读聚合；不领取任务、不更改生产或投稿状态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-25 | Codex | 移除候选任务聚合截断，确保工作台覆盖完整业务待办。 |
| 1.0.0 | 2026-10-25 | Codex | 合并人工任务和独立审核身份，保留无任务父项的自动成片。 |
"""


class EnglishConsoleDAL:
    def english_console_snapshot(self):
        """一次连接读取有限窗口；避免逐行查询和把未关联自动成片漏掉。"""
        with self.get_connection() as conn:
            jobs = [dict(r) for r in conn.execute('''
            SELECT j.*, c.source_title, c.source_channel
                FROM english_world_jobs j LEFT JOIN english_world_candidates c
                ON c.id=j.selected_candidate_id ORDER BY j.updated_at DESC,j.id DESC''')]
            reviews = [dict(r) for r in conn.execute('''
                SELECT r.*, d.state AS douyin_state,
                       d.updated_at AS douyin_updated_at, d.last_error_message AS douyin_error
                FROM english_world_review_items r LEFT JOIN english_world_douyin_publications d
                ON d.review_id=r.id ORDER BY r.updated_at DESC,r.id DESC''')]
            counts = {table: conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                      for table in ('english_world_jobs', 'english_world_review_items')}
        return {'jobs': jobs, 'reviews': reviews, 'counts': counts}
