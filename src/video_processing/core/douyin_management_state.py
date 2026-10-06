"""抖音作品管理页的状态契约；平台限制与 UI 无法识别分别处理。

依赖仅为标准库，供上传器、调度和人工对账入口共享。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-06 | Codex | 同作品卡片识别公开、审核及限制状态，负面审核不累计 UI 熔断。 |
"""

from __future__ import annotations

import re


MANAGEMENT_EXIT_STATES = {0: "PUBLISHED", 6: "UNDER_REVIEW", 8: "REJECTED", 9: "RESTRICTED"}
MANAGEMENT_NEGATIVE_STATES = {"REJECTED", "RESTRICTED"}
MANAGEMENT_STATE_MESSAGES = {
    "PUBLISHED": "抖音作品管理页精确确认本次作品已发布。",
    "UNDER_REVIEW": "抖音作品管理页精确确认本次作品仍在审核中。",
    "REJECTED": "抖音作品管理页精确确认本次作品不适宜公开或审核不通过；保留投稿身份，禁止重传。",
    "RESTRICTED": "抖音作品管理页精确确认本次作品流量减少；保留投稿身份，禁止重传。",
}
_LABEL_STATES = {
    "已发布": "PUBLISHED", "审核中": "UNDER_REVIEW",
    "不适宜公开": "REJECTED", "审核不通过": "REJECTED", "不通过": "REJECTED",
    "流量减少": "RESTRICTED",
}
_CARD_STATE = re.compile(
    r"编辑作品(?:设置权限)?(?:作品置顶)?(?:删除作品)?"
    r"\d{4}年\d{2}月\d{2}日(?:\d{2}:\d{2})?"
    r"(" + "|".join(_LABEL_STATES) + r")"
)


def normalize_page_text(text: str) -> str:
    """压缩页面空白及零宽字符，保持文案内容本身不变。"""
    return "".join((text or "").replace("\u200b", "").split())


def get_management_copy_markers(copy_text: str) -> list[str]:
    """长正文优先提供身份指纹；短片段保持既有兼容。"""
    normalized = normalize_page_text(copy_text)
    return list(dict.fromkeys(normalized[:size] for size in (96, 64, 40, 24) if len(normalized) >= size))


def get_management_publication_state(page_text: str, copy_text: str, title_text: str = "") -> str | None:
    """仅接受身份锚点后第一个编辑菜单紧邻的日期和状态，不借用下一作品。"""
    page = normalize_page_text(page_text)
    title = normalize_page_text(title_text)
    markers = [title] if len(title) >= 6 else []
    markers.extend(marker for marker in get_management_copy_markers(copy_text) if marker not in markers)
    cards: dict[int, str] = {}
    for marker in markers:
        start = 0
        while (index := page.find(marker, start)) >= 0:
            tail = page[index + len(marker):]
            edit_index = tail.find("编辑作品")
            if edit_index >= 0:
                match = _CARD_STATE.match(tail[edit_index:])
                if match:
                    cards[index + len(marker) + edit_index] = _LABEL_STATES[match.group(1)]
            start = index + len(marker)
    return next(iter(cards.values())) if len(cards) == 1 else None
