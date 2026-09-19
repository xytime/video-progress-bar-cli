"""互动评论执行结果的 Telegram 自动汇报器。

将发评结果、策略类型、文本预览及审计截图推送至 Telegram 运营群。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 初始创建：实现互动引导结果与证据截图的图文汇报 |
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings
from video_processing.db.database import PipelineDB
from video_processing.telegram_delivery import send_photo, send_text

from .contract import InteractionDraft

logger = logging.getLogger(__name__)


class InteractionNotifier:
    """互动评论结果通知器。"""

    def __init__(self, db: Optional[PipelineDB] = None) -> None:
        self.db = db or PipelineDB()

    def notify_interaction_result(
        self,
        *,
        video_title: str,
        platform_post_id: str,
        status: str,
        draft: Optional[InteractionDraft],
        evidence_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """向 Telegram 推送互动发评通知。"""
        status_icons = {
            "COMMENTED": "💬 <b>视频号首评互动已发布</b>",
            "SKIPPED_EXISTS": "ℹ️ <b>视频号互动已存在（跳过）</b>",
            "PENDING_REVIEW": "⏳ <b>视频号互动待回查（转码/审核中）</b>",
            "FAILED": "⚠️ <b>视频号互动发评失败</b>",
        }
        title_line = status_icons.get(status, f"🔔 <b>视频号互动通知: {status}</b>")

        lines = [
            title_line,
            f"🎬 <b>视频</b>: <code>{html.escape(video_title)}</code>",
            f"🆔 <b>Post ID</b>: <code>{html.escape(platform_post_id[:32])}...</code>",
        ]

        if draft:
            provider_badge = "🤖 AGY深度思考" if "agy" in draft.provider else "🌱 自生长规则兜底"
            type_names = {
                "POLL_STAND": "站队投票型",
                "WARNING_SHARE": "利他避坑转发型",
                "GROUP_DISCUSSION": "群聊研讨转发型",
                "MEMO_COLLECTION": "干货备忘转发型",
                "VOICE_RESONANCE": "观点共鸣嘴替型",
            }
            type_label = type_names.get(draft.interaction_type.value, draft.interaction_type.value)
            lines.extend([
                f"🧠 <b>生成方式</b>: {provider_badge} ({draft.provider})",
                f"🎯 <b>互动类型</b>: {type_label}",
                "📝 <b>首评排版预览</b>:",
                f"<blockquote>{html.escape(draft.formatted_comment)}</blockquote>",
            ])

        if error_message:
            lines.append(f"❌ <b>原因</b>: {html.escape(error_message)}")

        text = "\n".join(lines)
        photo_path = Path(evidence_path) if evidence_path else None

        if photo_path and photo_path.is_file():
            res = send_photo(
                event_type="interaction.wechat_comment",
                priority="P1",
                path=photo_path,
                caption=text,
                db=self.db,
            )
            return res.state == "ACCEPTED"

        res = send_text(
            event_type="interaction.wechat_comment",
            priority="P1",
            text=text,
            db=self.db,
        )
        return res.state == "ACCEPTED"
