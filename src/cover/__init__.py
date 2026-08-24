"""视频号封面生成引擎 v2.0 包入口

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，导出 CoverEngine Facade 接口                          |
| 1.1.0   | 2026-07-29 | Codex                        | 导出内容贴合封面策划契约，保持渲染层与语义层解耦                  |
| 1.2.0   | 2026-08-24 | Codex                        | 导出英语世界封面载荷构建与校验接口。                              |
| 1.3.0   | 2026-08-24 | Codex                        | 导出 Antigravity 主视觉契约与候选验收工具。                        |
"""

from .engine import CoverEngine
from .creative_brief import CoverCreativeBrief, build_cover_creative_brief, validate_cover_brief_input
from .english_world import build_english_world_cover_payload, validate_english_world_cover_payload
from .antigravity import accept_and_normalize, build_agy_prompt, build_visual_brief

__all__ = [
    "CoverEngine",
    "CoverCreativeBrief",
    "build_cover_creative_brief",
    "validate_cover_brief_input",
    "build_english_world_cover_payload",
    "validate_english_world_cover_payload",
    "accept_and_normalize",
    "build_agy_prompt",
    "build_visual_brief",
]
