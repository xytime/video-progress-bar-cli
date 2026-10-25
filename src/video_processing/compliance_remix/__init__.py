# -*- coding: utf-8 -*-
"""合规二创业务核心模块 (video_processing.compliance_remix)

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-25 | Antigravity | 初始创建，实现敏感外媒视频合规二创核心组件与流水线 |
"""

from .censor_guard import ComplianceCensorGuard, ComplianceReport
from .card_generator import FinancialCardGenerator, generate_vertical_frame_overlay
from .subtitle_generator import TopEdgeSubtitleGenerator
from .audio_mixer import AudioMixerEngine
from .video_compositor import VideoCompositor
from .remix_pipeline import ComplianceVideoRemixPipeline
from .commentary_generator import CommentaryGenerator
from .remix_service import ComplianceRemixService

__all__ = [
    "ComplianceCensorGuard",
    "ComplianceReport",
    "FinancialCardGenerator",
    "generate_vertical_frame_overlay",
    "TopEdgeSubtitleGenerator",
    "AudioMixerEngine",
    "VideoCompositor",
    "ComplianceVideoRemixPipeline",
    "CommentaryGenerator",
    "ComplianceRemixService",
]
