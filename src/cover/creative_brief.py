"""内容贴合封面的策划契约。

将视频元数据归纳为稳定、可审计的视觉策划，而不让封面渲染器承担
语义推断职责。后续若接入图像生成服务，只需消费 ``visual_direction``
与 ``visual_keywords``，无需改动发布或排版链路。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 新增内容到视觉策划的纯规则契约与输入质量校验 |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CoverCreativeBrief:
    """供当前封面渲染器和未来背景生成器共享的视觉策划。"""

    style_id: str
    badge: str
    header_color: str
    accent_color: str
    title_color: str
    secondary_title_color: str
    frame_tint: str
    frame_tint_opacity: int
    visual_direction: str
    visual_keywords: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """输出可持久化、可人工复核的 JSON 载荷。"""
        payload = asdict(self)
        payload["visual_keywords"] = list(self.visual_keywords)
        return payload


@dataclass(frozen=True)
class CoverBriefValidation:
    """策划输入的轻量质量门；警告不应阻断正常的封面降级路径。"""

    ok: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _StyleRule:
    style_id: str
    badge: str
    header_color: str
    accent_color: str
    title_color: str
    secondary_title_color: str
    frame_tint: str
    frame_tint_opacity: int
    visual_direction: str
    keywords: tuple[str, ...]


_STYLE_RULES: tuple[_StyleRule, ...] = (
    _StyleRule(
        "market_shock", "市场警报", "#17191E", "#E5484D", "#F8FAFC", "#FF7A7A", "#8D1018", 46,
        "真实交易屏、芯片或公司主体为主画面；以红色下行趋势和高对比新闻感强调冲击。",
        ("crash", "selloff", "plunge", "collapse", "crisis", "崩盘", "暴跌", "抛售", "下跌", "巨震"),
    ),
    _StyleRule(
        "market_watch", "资本观察", "#151617", "#D5A63D", "#FAFAF5", "#F0C85A", "#594319", 30,
        "保留市场、企业或产品实景，使用克制的金色财经标识和清晰数据感。",
        ("market", "stock", "ipo", "finance", "capital", "股价", "上市", "资本", "财报", "投资", "估值"),
    ),
    _StyleRule(
        "tech_frontier", "前沿科技", "#071B27", "#38BDF8", "#F8FAFC", "#7DD3FC", "#053B58", 34,
        "突出芯片、设备、代码或实验现场，采用冷青色技术新闻调性。",
        ("ai", "chip", "hardware", "robot", "software", "芯片", "人工智能", "大模型", "机器人", "算法", "硬件"),
    ),
    _StyleRule(
        "global_affairs", "全球局势", "#21191B", "#E05D5D", "#FFF8F2", "#F5A3A3", "#671F28", 38,
        "保留人物、地图或现场画面，以深红色新闻标识传达地缘与政策张力。",
        ("policy", "geopolitics", "sanction", "war", "election", "政策", "制裁", "战争", "地缘", "选举", "总统"),
    ),
    _StyleRule(
        "science_explainer", "知识解析", "#183220", "#72B889", "#F7FFF8", "#B9E4C5", "#245C38", 28,
        "突出讲者、实验或解释对象，保持清爽、可信、易阅读的知识内容质感。",
        ("science", "education", "lecture", "health", "tutorial", "科学", "讲座", "教程", "科普", "健康", "医疗"),
    ),
)

_DEFAULT_RULE = _StyleRule(
    "editorial", "深度解读", "#17212B", "#7BA5C9", "#F7FAFC", "#BBD7EE", "#16344B", 26,
    "保留最具信息量的原始画面，以冷静的编辑新闻风格组织标题和视觉层级。",
    (),
)


def build_cover_creative_brief(payload: Mapping[str, Any]) -> CoverCreativeBrief:
    """从已有文案产物生成确定性的视觉策划，不产生网络或模型调用。"""
    searchable = " ".join(
        str(payload.get(key) or "") for key in ("title", "subtitle", "category")
    ).casefold()
    hints = tuple(
        str(item).strip().casefold()
        for item in _as_texts(payload.get("content_hints"))
        if str(item).strip()
    )
    corpus = " ".join((searchable, *hints))

    matched = next((rule for rule in _STYLE_RULES if _matches(rule, corpus)), _DEFAULT_RULE)
    keyword_hits = tuple(keyword for keyword in matched.keywords if keyword.casefold() in corpus)
    confidence = 0.9 if keyword_hits else 0.55
    visual_keywords = _unique((*keyword_hits[:3], *hints[:3]))
    return CoverCreativeBrief(
        style_id=matched.style_id,
        badge=matched.badge,
        header_color=matched.header_color,
        accent_color=matched.accent_color,
        title_color=matched.title_color,
        secondary_title_color=matched.secondary_title_color,
        frame_tint=matched.frame_tint,
        frame_tint_opacity=matched.frame_tint_opacity,
        visual_direction=matched.visual_direction,
        visual_keywords=visual_keywords,
        confidence=confidence,
    )


def validate_cover_brief_input(payload: Mapping[str, Any]) -> CoverBriefValidation:
    """报告会削弱内容贴合度的输入问题，供人工审核或后续指标使用。"""
    warnings: list[str] = []
    title = str(payload.get("title") or "").strip()
    if not title:
        warnings.append("missing_title")
    elif len(title) > 32:
        warnings.append("long_title_requires_small_font")
    if not _as_texts(payload.get("content_hints")):
        warnings.append("no_content_hints_used_title_fallback")
    return CoverBriefValidation(ok=bool(title), warnings=tuple(warnings))


def _matches(rule: _StyleRule, corpus: str) -> bool:
    return any(keyword.casefold() in corpus for keyword in rule.keywords)


def _as_texts(value: Any) -> Iterable[str]:
    return value if isinstance(value, (list, tuple)) else ()


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
