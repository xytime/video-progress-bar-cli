"""新闻精读卡片的独立渲染域。

本包不依赖发布流水线、数据库或任一 AI 供应商；上游只需交付稳定的
``StudyCardContent``，下游只产出可审核的 MP4 与 manifest。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 导出学习卡片旁路渲染域的内容契约、渲染器与词汇筛选规则。 |
| 1.1.0 | 2026-08-03 | Codex | 导出左侧正文微笔记上限，供渲染脚本和异步协调复用同一规则。 |
"""

from .models import StudyCardContent, StudyParagraph, StudyWord, VocabularyItem
from .renderer import StudyCardRenderer
from .vocabulary import (
    MAX_STUDY_NOTE_ITEMS,
    MAX_VOCABULARY_DENSITY,
    MIN_LEARNING_LEVEL,
    VocabularySelection,
    difficulty_level,
    select_vocabulary,
)

__all__ = [
    "MAX_STUDY_NOTE_ITEMS", "MAX_VOCABULARY_DENSITY", "MIN_LEARNING_LEVEL", "StudyCardContent",
    "StudyCardRenderer", "StudyParagraph", "StudyWord", "VocabularyItem", "VocabularySelection",
    "difficulty_level", "select_vocabulary",
]
