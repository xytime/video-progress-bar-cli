"""新闻精读卡片的独立渲染域。

本包不依赖发布流水线、数据库或任一 AI 供应商；上游只需交付稳定的
``StudyCardContent``，下游只产出可审核的 MP4 与 manifest。
"""

from .models import StudyCardContent, StudyParagraph, StudyWord, VocabularyItem
from .renderer import StudyCardRenderer

__all__ = ["StudyCardContent", "StudyCardRenderer", "StudyParagraph", "StudyWord", "VocabularyItem"]
