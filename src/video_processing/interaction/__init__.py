"""视频号评论区互动与自生长引导模块。

本包为完全独立的微内核模块，负责：
1. 互动话题与转发动机决策（AGY 深度思考模型优先）；
2. 策略知识库自生长与程序化兜底（学习并逼近 AI 水平）；
3. 视频号后台评论自动化发评（Playwright，防重防风控）；
4. Telegram 图文汇报。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Antigravity | 架构解耦：轻量导出数据合同，对重型依赖（Playwright, Notifier）采用 __getattr__ 懒加载 |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：独立微内核包 |
"""

from .contract import (
    CensorshipViolationError,
    InteractionContractError,
    InteractionDraft,
    InteractionResult,
    InteractionType,
    validate_interaction_draft,
)

__all__ = [
    "CensorshipViolationError",
    "InteractionContractError",
    "InteractionDraft",
    "InteractionResult",
    "InteractionType",
    "validate_interaction_draft",
    "InteractionService",
    "BrowserCommenter",
    "InteractionNotifier",
]


def __getattr__(name: str):
    if name == "InteractionService":
        from .service import InteractionService
        return InteractionService
    if name == "BrowserCommenter":
        from .browser_commenter import BrowserCommenter
        return BrowserCommenter
    if name == "InteractionNotifier":
        from .notifier import InteractionNotifier
        return InteractionNotifier
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return __all__
