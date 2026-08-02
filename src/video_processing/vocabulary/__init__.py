# -*- coding: utf-8 -*-
"""离线词汇分级模块。

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0 | 2026-08-03 | Codex | 初始创建：导出词表加载与考试等级判定的公共接口。 |
| 1.1.0 | 2026-08-03 | Codex | 导出文章生词表抽取便捷接口。 |
| 1.2.0 | 2026-08-03 | Codex | 导出 ECDICT 加载模式选项，支持性能策略切换。 |
"""

from .leveler import (
    DEFAULT_WORDLIST_DIR,
    ECDICT_MODES,
    EcdictMode,
    VocabularyLeveler,
    analyze_text,
    analyze_word,
    extract_article_vocabulary,
)
from .models import FriendlyTag, WordLevelResult

__all__ = [
    "DEFAULT_WORDLIST_DIR",
    "ECDICT_MODES",
    "EcdictMode",
    "FriendlyTag",
    "VocabularyLeveler",
    "WordLevelResult",
    "analyze_text",
    "analyze_word",
    "extract_article_vocabulary",
]
