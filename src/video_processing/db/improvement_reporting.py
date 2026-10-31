"""改进分析的只读失败事件查询，不初始化或修改生产表。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 按失败事件时间读取，保留旧任务及删除后孤立事件。 |
"""
from __future__ import annotations


class ImprovementReportingDAL:
    def get_improvement_failure_events(self, since_utc: str, until_utc: str) -> list[dict]:
        """读取半开时间窗口，不以入库时间或当前状态过滤历史失败。"""
        with self.get_connection() as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            rows = conn.execute("""
                SELECT e.id AS event_id, e.video_id, e.status, e.reason, e.failed_at,
                       COALESCE(v.parent_id, e.video_id) AS family_root_id,
                       v.youtube_id, v.slice_index, v.created_at,
                       CASE WHEN v.id IS NULL THEN 1 ELSE 0 END AS orphaned
                FROM publishing_failure_events e
                LEFT JOIN processed_videos v ON v.id=e.video_id
                WHERE julianday(e.failed_at)>=julianday(?)
                  AND julianday(e.failed_at)<julianday(?)
                ORDER BY julianday(e.failed_at), e.id
            """, (since_utc, until_utc)).fetchall()
            invalid = conn.execute("SELECT count(*) FROM publishing_failure_events WHERE julianday(failed_at) IS NULL").fetchone()[0]
            if invalid:
                raise ValueError("失败事件存在不可解析时间，不能输出完整增量")
            return [dict(row) for row in rows]
