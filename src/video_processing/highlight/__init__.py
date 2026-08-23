"""长视频 Highlight Job 的独立分析和资产生产域。

仅负责显式创建的候选分析与产物计划；绝不接管 PipelineManager 的既有处理、发布或账本状态。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-08-20 | Codex | 暴露独立 Clip 的人工审核、投递和 post_id 精确回查服务 |
| 1.1.0 | 2026-08-20 | Codex | 暴露独立 Clip 本地资产渲染服务，仍不接管既有发布状态机 |
| 1.0.0 | 2026-08-20 | Codex | 新增独立 Highlight Job 分析域入口 |
"""

from .service import HighlightJobService
from .render import HighlightRenderService
from .publish import HighlightPublicationService

__all__ = ["HighlightJobService", "HighlightRenderService", "HighlightPublicationService"]
