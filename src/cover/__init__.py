"""视频号封面生成引擎 v2.0 包入口

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，导出 CoverEngine Facade 接口                          |
| 1.1.0   | 2026-07-29 | Codex                        | 导出内容贴合封面策划契约，保持渲染层与语义层解耦                  |
"""

from .engine import CoverEngine
from .creative_brief import CoverCreativeBrief, build_cover_creative_brief, validate_cover_brief_input

__all__ = [
    "CoverEngine",
    "CoverCreativeBrief",
    "build_cover_creative_brief",
    "validate_cover_brief_input",
]
