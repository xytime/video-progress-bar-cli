"""tests/unit/test_bot_auth.py — 鉴权模块 TDD (Red → Green)

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | TDD Red phase: 先写测试定义合约 |
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestAdminAuth:
    """测试 bot.auth 模块的白名单鉴权逻辑"""

    def test_valid_admin_passes(self):
        """白名单内的用户应通过鉴权"""
        from bot.auth import is_admin
        auth = is_admin(user_id=123456789, admin_ids={123456789, 987654321})
        assert auth is True

    def test_unknown_user_rejected(self):
        """白名单外的用户必须被拒绝"""
        from bot.auth import is_admin
        auth = is_admin(user_id=111111111, admin_ids={123456789})
        assert auth is False

    def test_empty_admin_list_rejects_all(self):
        """空白名单应拒绝所有人（Fail-Closed）"""
        from bot.auth import is_admin
        auth = is_admin(user_id=123456789, admin_ids=set())
        assert auth is False

    def test_parse_admin_ids_valid(self):
        """正确解析逗号分隔的 admin ID 字符串"""
        from bot.auth import parse_admin_ids
        result = parse_admin_ids("123456789,987654321")
        assert result == {123456789, 987654321}

    def test_parse_admin_ids_with_spaces(self):
        """解析时应容忍空格"""
        from bot.auth import parse_admin_ids
        result = parse_admin_ids("123456789, 987654321")
        assert result == {123456789, 987654321}

    def test_parse_admin_ids_empty_raises(self):
        """空字符串或未配置应抛出 SecurityConfigError（Fail-Closed）"""
        from bot.auth import parse_admin_ids, SecurityConfigError
        with pytest.raises(SecurityConfigError):
            parse_admin_ids("")

    def test_parse_admin_ids_none_raises(self):
        """None 值（未配置环境变量）应抛出 SecurityConfigError"""
        from bot.auth import parse_admin_ids, SecurityConfigError
        with pytest.raises(SecurityConfigError):
            parse_admin_ids(None)

    def test_parse_admin_ids_invalid_format_raises(self):
        """非数字的 ID 应抛出 SecurityConfigError"""
        from bot.auth import parse_admin_ids, SecurityConfigError
        with pytest.raises(SecurityConfigError):
            parse_admin_ids("not_a_number")
