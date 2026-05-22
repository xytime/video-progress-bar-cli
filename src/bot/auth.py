"""src/bot/auth.py — Telegram Bot 管理员鉴权模块

高内聚：只负责 admin 白名单管理，不依赖任何外部 I/O。
安全设计：Fail-Closed — 未配置即拒绝启动。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建，TDD Green phase |
"""
from __future__ import annotations


class SecurityConfigError(ValueError):
    """TELEGRAM_ADMIN_IDS 未配置或格式非法时抛出。
    触发此异常将导致 Bot 拒绝启动 (Fail-Closed)。
    """


def parse_admin_ids(raw: str | None) -> set[int]:
    """将 TELEGRAM_ADMIN_IDS 环境变量解析为整数集合。

    Args:
        raw: 逗号分隔的用户 ID 字符串，如 "123456789,987654321"。

    Returns:
        整数集合 {123456789, 987654321}。

    Raises:
        SecurityConfigError: 当 raw 为 None、空字符串或包含非数字 ID 时。
    """
    # [Claude_Sonnet_4.6_Thinking_planning] Fail-Closed: 空值直接拒绝
    if not raw or not raw.strip():
        raise SecurityConfigError(
            "❌ 安全拦截：TELEGRAM_ADMIN_IDS 未配置或为空。\n"
            "请在 .env 中设置 TELEGRAM_ADMIN_IDS=<your_telegram_user_id>\n"
            "（发送任意消息给 @userinfobot 可获取您的 User ID）"
        )

    admin_ids: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            admin_ids.add(int(token))
        except ValueError:
            raise SecurityConfigError(
                f"❌ 安全拦截：TELEGRAM_ADMIN_IDS 中含有非数字项：'{token}'。\n"
                "请填写纯数字的 Telegram User ID。"
            )

    if not admin_ids:
        raise SecurityConfigError(
            "❌ 安全拦截：TELEGRAM_ADMIN_IDS 解析后为空集合，请检查配置。"
        )

    return admin_ids


def is_admin(user_id: int, admin_ids: set[int]) -> bool:
    """检查 user_id 是否在 admin 白名单中。

    Args:
        user_id: Telegram 用户 ID。
        admin_ids: 已解析的管理员 ID 集合。

    Returns:
        True 若在白名单中，False 否则（空集合亦返回 False）。
    """
    # [Claude_Sonnet_4.6_Thinking_planning] 空集合视同拒绝所有人
    return bool(admin_ids) and user_id in admin_ids
