"""tests/unit/test_bot_formatter.py — 消息格式化模块 TDD (Red → Green)

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
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
            {"youtube_id": "abc123", "title": "测试视频一", "status": "PENDING"},
            {"youtube_id": "def456", "title": "Test Video Two", "status": "DOWNLOADING"},
        ]
        msg = fmt_queue(videos=videos)
        assert "abc123" in msg
        assert "测试视频一" in msg
        assert "PENDING" in msg
        assert "DOWNLOADING" in msg

    def test_format_published_list(self):
        """最近发布的视频列表格式"""
        from bot.formatter import fmt_published
        videos = [
            {"youtube_id": "xyz789", "title": "已发布视频", "status": "PUBLISHED"},
        ]
        msg = fmt_published(videos=videos)
        assert "已发布视频" in msg
        assert "✅" in msg or "PUBLISHED" in msg

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
        for cmd in ["/queue", "/published", "/delete", "/retry"]:
            assert cmd in msg
