"""人工配音再制中心。

该包不被 PipelineManager 导入；只有显式人工入口可以创建或投递再制任务。
"""

from .service import DubbingService

__all__ = ["DubbingService"]
