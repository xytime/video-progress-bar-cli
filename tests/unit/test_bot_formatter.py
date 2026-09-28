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
        """有效授权状态渲染测试"""
        from bot.formatter import fmt_wechat_login_status

        info = {
            "login_time_bj": "2026-09-27 13:21:31 BJ",
            "relative_age": "2小时前",
            "auth_method_label": "桌面快捷",
            "status_label": "✅ 授权期内",
            "last_verified_bj": "2026-09-27 15:00:00 BJ",
            "relative_verified_age": "30分钟前",
            "schedule_estimate": "距 22.0h 调度阈值约 20.0 小时（调度估算，不代表平台剩余寿命）",
            "lock_status": "空闲",
            "state_file_status": "✅ 已保存 (2.9 KB)",
            "desktop_preflight": "✅ 预检就绪（仅桌面客户端环境就绪，不代表平台已授权）",
            "suggestions": ["当前在授权维护期内，系统将按计划定期保活。"],
        }
        msg = fmt_wechat_login_status(info)
        assert "微信视频号登录态状态" in msg
        assert "2026-09-27 13:21:31 BJ" in msg
        assert "2小时前 · 桌面快捷" in msg
        assert "✅ 授权期内" in msg
        assert "2026-09-27 15:00:00 BJ" in msg
        assert "30分钟前" in msg
        assert "调度估算，不代表平台剩余寿命" in msg
        assert "会话锁" in msg and "空闲" in msg
        assert "已保存 (2.9 KB)" in msg
        assert "仅桌面客户端环境就绪，不代表平台已授权" in msg

    def test_format_wechat_login_status_expired(self):
        """失效登录态渲染测试"""
        from bot.formatter import fmt_wechat_login_status

        info = {
            "login_time_bj": "2026-09-25 10:00:00 BJ",
            "relative_age": "2天前",
            "auth_method_label": "历史记录",
            "status_label": "❌ 会话已失效（需重新登录）",
            "last_verified_bj": "2026-09-25 10:00:00 BJ",
            "relative_verified_age": "2天前",
            "last_failure_display": "09-28 08:23:58 · LOGIN_REQUIRED (Redirected to login)",
            "schedule_estimate": "已达 22.0h 调度阈值（等待空闲周期自动重登）",
            "lock_status": "空闲",
            "state_file_status": "✅ 已保存",
            "desktop_preflight": "⚠️ 不可用 (NO_PROCESS，需手机扫码)",
            "suggestions": ["平台已要求重新扫码登录，请发送 /wechat_login 获取二维码扫码。"],
        }
        msg = fmt_wechat_login_status(info)
        assert "❌ 会话已失效（需重新登录）" in msg
        assert "最近检查" in msg
        assert "09-28 08:23:58 · LOGIN_REQUIRED" in msg
        assert "请发送 /wechat_login 获取二维码扫码。" in msg

