"""Handwritten Pager Video Generation Pipeline.

Bilingual handwriting reading and pen-follow video generation with
photorealistic pen sprites, dual-shadow physics, and natural handwriting dynamics.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of handwritten pager video pipeline |
"""

from .contracts import (
    HandwrittenPagerConfig,
    LyricLine,
    LyricWord,
    PenState,
    CopywritingPackage,
)
from .pen_physics import PenPhysicsEngine
from .canvas_builder import CanvasBuilder
from .renderer import HandwrittenPagerRenderer
from .cover_generator import CoverGenerator
from .copywriter import Copywriter

__all__ = [
    "HandwrittenPagerConfig",
    "LyricLine",
    "LyricWord",
    "PenState",
    "CopywritingPackage",
    "PenPhysicsEngine",
    "CanvasBuilder",
    "HandwrittenPagerRenderer",
    "CoverGenerator",
    "Copywriter",
]
