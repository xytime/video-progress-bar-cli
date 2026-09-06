"""按审核身份续接 Telegram 审计，保存已受理步骤及不确定边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-06 | Codex | 原子领取通知步骤；已受理跳过、未发出可恢复、结果不明停止。 |
"""
from collections.abc import Callable

from video_processing.db.database import PipelineDB
from video_processing.telegram_delivery import TelegramDeliveryResult


class ReviewDelivery:
    def __init__(self, db: PipelineDB, review_id: str):
        self.db, self.review_id = db, review_id

    def send(self, stage: str, action: Callable[[], TelegramDeliveryResult]) -> TelegramDeliveryResult:
        previous = self.db.get_english_world_delivery_stages(self.review_id).get(stage, {})
        if previous.get("state") == "ACCEPTED":
            return TelegramDeliveryResult(state="ACCEPTED", message_id=previous["message_id"])
        if not self.db.claim_english_world_delivery_stage(self.review_id, stage):
            raise RuntimeError(f"通知步骤 {stage} 已领取或结果不明，需核验；禁止盲目重发")
        try:
            result = action()
        except Exception as exc:
            self.db.finish_english_world_delivery_stage(
                self.review_id, stage, state="UNKNOWN", error_kind=type(exc).__name__,
            )
            raise
        self.db.finish_english_world_delivery_stage(
            self.review_id, stage, state=result.state,
            message_id=result.message_id, error_kind=result.error_kind,
        )
        if result.state != "ACCEPTED":
            raise RuntimeError(f"通知步骤 {stage} 未获 API 接受：{result.error_kind or result.state}")
        return result
