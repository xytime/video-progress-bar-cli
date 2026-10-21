"""内容贴合封面的策划契约。

将视频元数据归纳为稳定、可审计的视觉策划，而不让封面渲染器承担
语义推断职责。后续若接入图像生成服务，只需消费 ``visual_direction``
与 ``visual_keywords``，无需改动发布或排版链路。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-21 | Antigravity | 引入零算力真实摄影美学轮换预设，消除单一插画风格同质化。 |
| 1.0.0 | 2026-07-29 | Codex | 新增内容到视觉策划的纯规则契约与输入质量校验 |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class PhotographicStylePreset:
    """真实摄影光学与光影预设；用于打破同质化插画风格，零本地算力消耗。"""

    preset_id: str
    label_zh: str
    lens_and_aperture: str
    lighting_and_color: str
    composition_and_bokeh: str

    def to_prompt_directive(self) -> str:
        return (
            f"Photographic style ({self.preset_id}): {self.lens_and_aperture}; "
            f"{self.lighting_and_color}; {self.composition_and_bokeh}."
        )


PHOTOGRAPHIC_STYLE_PRESETS: tuple[PhotographicStylePreset, ...] = (
    PhotographicStylePreset(
        "macro_rim_light",
        "微距逆光浅景深",
        "100mm f/2.8 macro lens, extreme shallow depth of field, razor-sharp micro-texture on the single foreground subject",
        "low-angle golden-hour rim light with warm amber highlights and deep natural shadow falloff",
        "creamy optical bokeh background, calm out-of-focus upper zone for typography",
    ),
    PhotographicStylePreset(
        "telephoto_street_compression",
        "长焦空间压缩纪实",
        "135mm f/2.0 telephoto lens, strong spatial compression, crisp tactile material detail on the foreground anchor",
        "late-afternoon side light with rich contrast, natural film-like highlight roll-off",
        "layered street or architectural depth melting into soft bokeh in the upper-left area",
    ),
    PhotographicStylePreset(
        "cleanroom_macro_optics",
        "精密工业微距冷暖对比",
        "90mm f/2.8 tilt-shift macro, specular surface reflections and precision physical details",
        "cool cyan ambient light contrasted with warm amber key reflection, authentic optical flare",
        "single dominant physical object in lower-right foreground, dark smoothly defocused upper background",
    ),
    PhotographicStylePreset(
        "cinematic_nocturne_35mm",
        "雨夜人文纪实35mm",
        "35mm f/1.4 prime lens, environmental close-up, wet surface specular reflections and natural film grain",
        "moody nocturnal teal-and-amber lighting, single glowing practical light source",
        "clear focal subject against softly blurred city or interior bokeh, uncluttered upper-left negative space",
    ),
    PhotographicStylePreset(
        "architectural_daylight_50mm",
        "建筑自然光影50mm",
        "50mm f/1.8 standard prime, authentic perspective, tangible stone/metal/wood/glass textures",
        "crisp directional morning sunlight casting clean geometric shadows, neutral editorial color grade",
        "grounded foreground subject with calm, softly shadowed or sky-toned upper area for headline placement",
    ),
    PhotographicStylePreset(
        "studio_chiaroscuro_85mm",
        "静物明暗对照85mm",
        "85mm f/1.8 portrait/still-life lens, tack-sharp focal plane with rapid depth falloff",
        "Caravaggio-inspired directional window light, warm highlights emerging from deep matte shadows",
        "iconic physical object isolated on a textured surface, quiet dark upper-left negative space",
    ),
)


def select_photographic_style(seed_text: str, *, variant_offset: int = 0) -> PhotographicStylePreset:
    """根据主题文本哈希确定性轮换摄影风格；同一视频的多候选 variant 自动错开。"""
    normalized = " ".join(str(seed_text or "").split()).encode("utf-8")
    digest = hashlib.sha256(normalized).digest()
    base_index = int.from_bytes(digest[:4], "big")
    index = (base_index + int(variant_offset)) % len(PHOTOGRAPHIC_STYLE_PRESETS)
    return PHOTOGRAPHIC_STYLE_PRESETS[index]


def resolve_photographic_style(
    keywords: Iterable[str], seed_text: str, *, variant_offset: int = 0,
) -> PhotographicStylePreset:
    """优先沿用策划已选定的预设（keywords 中的 preset_id），重试时在其基础上轮换；否则回退哈希选择。

    保证同一封面 prompt 只出现一个摄影风格指令，避免策划与生成器各选一套互相冲突。
    """
    ids = [preset.preset_id for preset in PHOTOGRAPHIC_STYLE_PRESETS]
    for keyword in keywords:
        if str(keyword) in ids:
            index = (ids.index(str(keyword)) + int(variant_offset)) % len(ids)
            return PHOTOGRAPHIC_STYLE_PRESETS[index]
    return select_photographic_style(seed_text, variant_offset=variant_offset)


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
        "真实摄影级编辑画面：选取与主题直接相关的单一具象金融或工业实体作为焦点，配合强烈明暗对比、浅景深与冷峻纪实光影。",
        ("crash", "selloff", "plunge", "collapse", "crisis", "崩盘", "暴跌", "抛售", "下跌", "巨震"),
    ),
    _StyleRule(
        "market_watch", "资本观察", "#151617", "#D5A63D", "#FAFAF5", "#F0C85A", "#594319", 30,
        "真实摄影级编辑画面：聚焦与资本、地产或企业主题直接对应的真实物质主体（如建筑局部、黄铜门锁、交易终端细节），暖金侧逆光与浅景深虚化。",
        ("market", "stock", "ipo", "finance", "capital", "股价", "上市", "资本", "财报", "投资", "估值"),
    ),
    _StyleRule(
        "tech_frontier", "前沿科技", "#071B27", "#38BDF8", "#F8FAFC", "#7DD3FC", "#053B58", 34,
        "真实摄影级微距/工业纪实：突出硅晶圆、精密光学元件、服务器或实验装置的真实物理质感，采用冷青与琥珀高光对比及光学浅景深。",
        ("ai", "chip", "hardware", "robot", "software", "芯片", "人工智能", "大模型", "机器人", "算法", "硬件"),
    ),
    _StyleRule(
        "global_affairs", "全球局势", "#21191B", "#E05D5D", "#FFF8F2", "#F5A3A3", "#671F28", 38,
        "真实摄影级人文/建筑纪实：选取具象的现场物件、港口集装箱、能源设施或建筑地标局部，长焦空间压缩与庄重自然光影。",
        ("policy", "geopolitics", "sanction", "war", "election", "政策", "制裁", "战争", "地缘", "选举", "总统"),
    ),
    _StyleRule(
        "science_explainer", "知识解析", "#183220", "#72B889", "#F7FFF8", "#B9E4C5", "#245C38", 28,
        "真实摄影级自然/科学特写：聚焦视频核心讨论的具象自然生物、实验器皿或物理现象，微距逆光、细腻纹理与柔和散景。",
        ("science", "education", "lecture", "health", "tutorial", "科学", "讲座", "教程", "科普", "健康", "医疗"),
    ),
)

_DEFAULT_RULE = _StyleRule(
    "editorial", "深度解读", "#17212B", "#7BA5C9", "#F7FAFC", "#BBD7EE", "#16344B", 26,
    "真实摄影级编辑画面：从主题中提炼单一具体可拍的真实物体或场景特写，真实镜头景深与自然光影，避免插画或抽象图标。",
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
    photo_style = select_photographic_style(searchable or matched.style_id)
    visual_keywords = _unique((*keyword_hits[:3], *hints[:3], photo_style.preset_id))
    return CoverCreativeBrief(
        style_id=matched.style_id,
        badge=matched.badge,
        header_color=matched.header_color,
        accent_color=matched.accent_color,
        title_color=matched.title_color,
        secondary_title_color=matched.secondary_title_color,
        frame_tint=matched.frame_tint,
        frame_tint_opacity=matched.frame_tint_opacity,
        # 摄影预设只经 visual_keywords 里的 preset_id 传递，由生成器展开为唯一一条技法指令。
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
