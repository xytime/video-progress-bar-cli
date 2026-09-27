"""tests/unit/test_bot_formatter.py — 消息格式化模块 TDD (Red → Green)

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-09-09 | Codex | 覆盖队列和已发布列表的安全 YouTube 原视频链接。 |
| 1.3.0 | 2026-09-27 | Antigravity | 覆盖 /last_login 帮助文案与 fmt_wechat_login_status 状态渲染。 |
| 1.1.0 | 2026-08-20 | Codex | 覆盖 Highlight Job 的显式候选入口帮助文案 |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | TDD Red phase: 先写测试定义合约 |
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestFormatter:
    """测试 bot.formatter 模块的 Markdown 格式化输出"""

    def test_format_video_added_success(self):
        """成功加入队列时的回复格式"""
        from bot.formatter import fmt_video_added
        msg = fmt_video_added(title="AI巨头IPO暗战", video_id="PtbZY9HCatE")
        assert "✅" in msg
        assert "AI巨头IPO暗战" in msg
        assert "PtbZY9HCatE" in msg

    def test_format_video_already_exists(self):
        """视频已存在时应包含当前状态"""
        from bot.formatter import fmt_video_exists
        msg = fmt_video_exists(title="测试视频", status="DOWNLOADING")
        assert "DOWNLOADING" in msg
        assert "测试视频" in msg

    def test_format_queue_empty(self):
        """队列为空时应给出清晰提示"""
        from bot.formatter import fmt_queue
        msg = fmt_queue(videos=[])
        assert "空" in msg or "empty" in msg.lower()

    def test_format_queue_with_videos(self):
        """队列有视频时应按状态展示每条记录"""
        from bot.formatter import fmt_queue
        videos = [
            {"youtube_id": "ODhae8RmBIc", "title": "测试视频一", "status": "PENDING"},
            {"youtube_id": "def456", "title": "Test Video Two", "status": "DOWNLOADING"},
        ]
        msg = fmt_queue(videos=videos)
        assert "ODhae8RmBIc" in msg
        assert "测试视频一" in msg
        assert "PENDING" in msg
        assert "DOWNLOADING" in msg
        assert "https://www.youtube.com/watch?v=ODhae8RmBIc" in msg

    def test_format_published_list(self):
        """最近发布的视频列表格式"""
        from bot.formatter import fmt_published
        videos = [
            {"youtube_id": "ODhae8RmBIc", "title": "已发布视频", "status": "PUBLISHED"},
        ]
        msg = fmt_published(videos=videos)
        assert "已发布视频" in msg
        assert "✅" in msg or "PUBLISHED" in msg
        assert "https://www.youtube.com/watch?v=ODhae8RmBIc" in msg

    def test_format_delete_success(self):
        """删除成功的回复"""
        from bot.formatter import fmt_delete_success
        msg = fmt_delete_success(youtube_id="abc123")
        assert "abc123" in msg
        assert "🗑" in msg or "删除" in msg

    def test_format_error(self):
        """通用错误格式应包含 ❌ 和错误原因"""
        from bot.formatter import fmt_error
        msg = fmt_error("视频不存在")
        assert "❌" in msg
        assert "视频不存在" in msg

    def test_format_api_unavailable(self):
        """FastAPI 断线时的降级回复"""
        from bot.formatter import fmt_api_unavailable
        msg = fmt_api_unavailable()
        assert "⚠️" in msg or "❌" in msg

    def test_format_help(self):
        """帮助信息应包含所有核心命令"""
        from bot.formatter import fmt_help
        msg = fmt_help()
        for cmd in ["/queue", "/published", "/delete", "/retry", "/highlight", "/last_login"]:
            assert cmd in msg

    def test_format_wechat_login_status_valid(self):
        """有效登录态渲染测试"""
        from bot.formatter import fmt_wechat_login_status

        info = {
            "login_time_bj": "2026-09-27 13:21:31 BJ",
            "relative_age": "2小时前",
            "status_label": "✅ 有效",
            "remaining_hours": 20.8,
            "state_file_status": "✅ 已保存 (2.9 KB)",
            "desktop_preflight": "✅ 就绪（免扫码桌面快捷授权）",
            "suggestions": ["当前登录态正常，无需操作。"],
        }
        msg = fmt_wechat_login_status(info)
        assert "微信视频号登录态状态" in msg
        assert "2026-09-27 13:21:31 BJ" in msg
        assert "✅ 有效（2小时前）" in msg
        assert "约 20.8 小时" in msg
        assert "已保存 (2.9 KB)" in msg
        assert "免扫码桌面快捷授权" in msg

    def test_format_wechat_login_status_expired(self):
        """过期登录态渲染测试"""
        from bot.formatter import fmt_wechat_login_status

        info = {
            "login_time_bj": "2026-09-25 10:00:00 BJ",
            "relative_age": "2天前",
            "status_label": "❌ 已过期",
            "remaining_hours": 0.0,
            "state_file_status": "✅ 已保存",
            "desktop_preflight": "⚠️ 不可用 (NO_PROCESS)",
            "suggestions": ["请发送 /wechat_login 重新登录。"],
        }
        msg = fmt_wechat_login_status(info)
        assert "❌ 已过期" in msg
        assert "请发送 /wechat_login 重新登录。" in msg

