"""深度洞察脚本契约；时间轴以已烧录字幕的竖版成片为基准。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-06 | Codex | 限定文本、有限时间、非重叠浮窗及可审查正文 |
"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=500)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class InsightModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HighlightWindow(InsightModel):
    start_sec: Seconds
    end_sec: Seconds

    @model_validator(mode="after")
    def ordered(self):
        if self.end_sec <= self.start_sec:
            raise ValueError("高光结束时间必须晚于开始时间")
        return self


class ContextCard(InsightModel):
    trigger_sec: Seconds
    duration_sec: Annotated[float, Field(gt=0, le=60, allow_inf_nan=False)]
    badge: Annotated[str, Field(min_length=1, max_length=60)]
    points: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]],
                      Field(min_length=1, max_length=3)]


class ClosingTakeaway(InsightModel):
    quote: Annotated[str, Field(min_length=1, max_length=120)]
    narration: Text
    poll_topic: Annotated[str, Field(min_length=1, max_length=120)]


class InsightScript(InsightModel):
    hook_title: Annotated[str, Field(min_length=1, max_length=80)]
    hook_narration: Text
    highlight_window: HighlightWindow
    context_cards: Annotated[list[ContextCard], Field(min_length=2, max_length=2)]
    closing_takeaway: ClosingTakeaway

    @model_validator(mode="after")
    def validate_timeline(self):
        duration = self.highlight_window.end_sec - self.highlight_window.start_sec
        previous_end = 0.0
        for card in self.context_cards:
            end = card.trigger_sec + card.duration_sec
            if card.trigger_sec < previous_end or end > duration:
                raise ValueError("浮窗必须按时间排序、互不重叠且位于高光段内")
            previous_end = end
        return self

    def review_text(self) -> str:
        """新增画面和口播必须作为发布审查正文，不受字幕审查开关影响。"""
        return "\n".join([
            self.hook_title, self.hook_narration,
            *(text for card in self.context_cards for text in [card.badge, *card.points]),
            self.closing_takeaway.quote, self.closing_takeaway.narration,
            self.closing_takeaway.poll_topic,
        ])
