"""封面版式硬门槛。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-10-20 | Codex | 允许经批准的逐行实底标题，保留历史版式校验以避免重做旧封面。 |
| 1.0.0 | 2026-08-03 | Codex | 将无大面积遮罩/卡片遮挡底图规则固化为来源清单和模板硬校验 |
| 1.1.0 | 2026-08-03 | Codex | 将移动端大字可读性纳入封面来源清单和模板静态校验 |
| 1.2.0 | 2026-08-21 | Codex | 禁止系统告警式运营装饰，防止无关文字破坏封面可信度 |
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


COVER_LAYOUT_POLICY_VERSION = "no_broad_overlay_v2"


class CoverReadabilityError(ValueError):
    """文字无法完整、清晰地排入封面；禁止降级到小字或裁切结果。"""


def compliant_cover_layout_policy(headline_style: str | None = None) -> dict[str, Any]:
    """生产封面必须携带的版式规则声明。"""
    policy = {
        "policy_version": COVER_LAYOUT_POLICY_VERSION,
        "no_broad_dark_overlay": True,
        "no_large_text_card": True,
        "preserve_dedicated_background": True,
        "text_legibility_method": "local_stroke_shadow_weight",
        "mobile_readable_title": True,
        "min_title_font_px": 84,
        "requires_local_text_stroke_or_shadow": True,
    }
    if headline_style == "opaque_title_strips_v1":
        policy.update(
            policy_version=headline_style,
            text_legibility_method="opaque_per_line_background",
            min_title_font_px=128,
            requires_local_text_stroke_or_shadow=False,
            opaque_title_strips=True,
            max_title_lines=2,
        )
    return policy


def has_compliant_cover_layout_policy(provenance: Mapping[str, Any]) -> bool:
    """旧封面没有该声明即不可继续作为自动投递 checkpoint。"""
    policy = provenance.get("layout_policy")
    if not isinstance(policy, Mapping):
        return False
    style = policy.get("policy_version")
    if style not in {COVER_LAYOUT_POLICY_VERSION, "opaque_title_strips_v1"}:
        return False
    expected = compliant_cover_layout_policy(style)
    return all(policy.get(key) == value for key, value in expected.items())


def validate_dedicated_cover_file(cover_file: Path, provenance_file: Path) -> bool:
    """统一验证可投递封面：非视频帧、哈希绑定，并符合无大遮罩版式策略。"""
    if not cover_file.is_file() or not provenance_file.is_file():
        return False
    try:
        provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
        digest = hashlib.sha256(cover_file.read_bytes()).hexdigest()
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        provenance.get("cover_kind") == "dedicated_generated_image"
        and provenance.get("uses_video_frame") is False
        and provenance.get("cover_filename") == cover_file.name
        and provenance.get("cover_sha256") == digest
        and has_compliant_cover_layout_policy(provenance)
    )


_BROAD_VISUAL_OVERLAY_RE = re.compile(
    r"background-image\s*:\s*linear-gradient\([^;]+url\(",
    re.IGNORECASE | re.DOTALL,
)
_MAIN_TITLE_BLOCK_RE = re.compile(r"^\s*\.main-title\s*\{(?P<body>.*?)\}", re.IGNORECASE | re.DOTALL | re.MULTILINE)
_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*(?P<size>\d+)px", re.IGNORECASE)


def assert_template_respects_cover_policy(
    template_text: str, template_path: Path, *, headline_style: str | None = None,
) -> None:
    """阻止模板重新引入覆盖主视觉的大面积暗渐变或文字卡片。"""
    violations: list[str] = []
    if _BROAD_VISUAL_OVERLAY_RE.search(template_text):
        violations.append("visual-layer must not combine a broad linear-gradient overlay with the visual asset")
    if ".glass-card" in template_text:
        violations.append("large glass/text card is prohibited over dedicated cover backgrounds")
    if "SYS_ALERT" in template_text:
        violations.append("system-alert marketing decoration is prohibited on production covers")
    title_match = _MAIN_TITLE_BLOCK_RE.search(template_text)
    if headline_style == "opaque_title_strips_v1" and not title_match:
        violations.append("approved title typography is missing")
    if title_match:
        title_block = title_match.group("body")
        size_match = _FONT_SIZE_RE.search(title_block)
        minimum = 128 if headline_style == "opaque_title_strips_v1" else 84
        if not size_match or int(size_match.group("size")) < minimum:
            violations.append(f"main title font-size must be at least {minimum}px for mobile cover readability")
        if headline_style == "opaque_title_strips_v1":
            strip = re.search(r"\.title-line\s*\{([^}]+)\}", template_text)
            if not strip or "background: #142331;" not in strip[1] or "color: #ffffff;" not in strip[1]:
                violations.append("opaque title strips require the approved solid background and white text")
        elif "-webkit-text-stroke" not in title_block and "text-shadow" not in title_block:
            violations.append("main title must use local stroke or shadow for readability")
    if violations:
        joined = "; ".join(violations)
        raise ValueError(f"Cover template violates {COVER_LAYOUT_POLICY_VERSION}: {template_path}: {joined}")
