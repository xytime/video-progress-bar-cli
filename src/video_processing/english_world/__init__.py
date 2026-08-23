"""英语世界短视频的独立选题研究域。

该域仅保存候选、选题和生产请求，不进入既有通用视频队列，也不上传或发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-21 | Codex | 新增英语世界短视频候选研究服务入口。 |
"""

from .research import EnglishWorldResearchService

__all__ = ["EnglishWorldResearchService"]
