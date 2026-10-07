"""深度洞察脚本契约；时间轴以已烧录字幕的竖版成片为基准。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-06 | Codex | 限定文本、有限时间、非重叠浮窗及可审查正文 |
| 2.0.0 | 2026-10-08 | Antigravity | 引入 InsightScriptV2：100% 完整原片零裁切约束、事实引证绑定与平滑兼容适配层 |
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=500)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class InsightModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ==================== V1 契约 (Legacy 保留兼容) ====================

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


# ==================== V2 契约 (RFC-2026-DEEP-CREATION-001) ====================

class VTTReference(InsightModel):
    start_sec: Seconds
    end_sec: Seconds
    source_quote: Annotated[str, Field(min_length=3, max_length=150)]

    @model_validator(mode="after")
    def validate_time(self):
        if self.end_sec < self.start_sec:
            raise ValueError("引证结束时间不可早于开始时间")
        return self


class PointItem(InsightModel):
    point_type: Literal["FACT", "INSIGHT", "BACKGROUND"]
    keyword: Annotated[str, Field(min_length=2, max_length=8)]
    explanation: Annotated[str, Field(min_length=10, max_length=36)]
    vtt_reference: VTTReference


class InsightCardV2(InsightModel):
    card_id: Literal["card_1", "card_2"]
    badge: Literal["制度透视", "利益博弈", "前沿透视", "底层洞察", "战略剖析", "危机解码"]
    title: Annotated[str, Field(min_length=4, max_length=28)]
    start_sec: Seconds
    end_sec: Seconds
    points: Annotated[list[PointItem], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_card_duration(self):
        duration = self.end_sec - self.start_sec
        if duration < 5.0 or duration > 45.0:
            raise ValueError(f"卡片展示时间跨度必须在 5~45 秒之间，当前为 {duration}s")
        return self


class HookSegment(InsightModel):
    title: Annotated[str, Field(min_length=4, max_length=24)]
    narration: Annotated[str, Field(min_length=30, max_length=120)]
    estimated_sec: Annotated[float, Field(ge=12.0, le=30.0)]


class OutroSegment(InsightModel):
    philosophical_quote: Annotated[str, Field(min_length=10, max_length=36)]
    reflection_question: Annotated[str, Field(min_length=10, max_length=32)]
    poll_options: Annotated[list[Annotated[str, Field(min_length=2, max_length=16)]], Field(min_length=2, max_length=3)]

    @property
    def tts_narration(self) -> str:
        """规范化片尾 TTS 配音合成文本。"""
        return f"{self.philosophical_quote}。{self.reflection_question}。"


class InsightScriptV2(InsightModel):
    schema_version: Literal["2.0.0"] = "2.0.0"
    video_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{11}$")]
    headline: Annotated[str, Field(min_length=4, max_length=24)]
    preserve_full_body: Literal[True] = True
    hook: HookSegment
    cards: Annotated[list[InsightCardV2], Field(min_length=2, max_length=2)]
    outro: OutroSegment

    @model_validator(mode="after")
    def validate_timeline(self):
        prev_end = 0.0
        for card in self.cards:
            if card.start_sec < prev_end:
                raise ValueError(f"卡片时序不可重叠或倒流: {card.start_sec} < {prev_end}")
            prev_end = card.end_sec
        return self

    def review_text(self) -> str:
        """提取全部新增口播、卡片文本及尾部思辨议题，送审流水线风控审查引擎。"""
        texts = [self.headline, self.hook.title, self.hook.narration]
        for c in self.cards:
            texts.extend([c.badge, c.title])
            for p in c.points:
                texts.extend([p.keyword, p.explanation])
        texts.extend([
            self.outro.philosophical_quote,
            self.outro.reflection_question,
            *self.outro.poll_options,
        ])
        return "\n".join(texts)

    def to_legacy_v1(self, body_duration: float) -> InsightScript:
        """向后兼容适配层：将 V2 结构转换为旧版 InsightScript (v1)。"""
        return InsightScript(
            hook_title=self.hook.title,
            hook_narration=self.hook.narration,
            highlight_window=HighlightWindow(start_sec=0.0, end_sec=body_duration),
            context_cards=[
                ContextCard(
                    trigger_sec=c.start_sec,
                    duration_sec=c.end_sec - c.start_sec,
                    badge=c.badge,
                    points=[f"{p.keyword}: {p.explanation}" for p in c.points]
                ) for c in self.cards
            ],
            closing_takeaway=ClosingTakeaway(
                quote=self.outro.philosophical_quote,
                narration=self.outro.tts_narration,
                poll_topic=self.outro.reflection_question
            )
        )
