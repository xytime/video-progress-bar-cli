# -*- coding: utf-8 -*-
"""离线词汇分级模块。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 初始创建：导出词表加载与考试等级判定的公共接口。 |
| 1.1.0 | 2026-08-03 | Codex | 导出文章生词表抽取便捷接口。 |
"""

from .leveler import DEFAULT_WORDLIST_DIR, VocabularyLeveler, analyze_text, analyze_word, extract_article_vocabulary
from .models import FriendlyTag, WordLevelResult

__all__ = [
    "DEFAULT_WORDLIST_DIR",
    "FriendlyTag",
    "VocabularyLeveler",
    "WordLevelResult",
    "analyze_text",
    "analyze_word",
    "extract_article_vocabulary",
]
