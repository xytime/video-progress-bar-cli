"""测试全局夹具。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-28 | Codex | 默认关闭公开视频提交窗口守卫，避免发布类单测依赖当前时钟 |
"""

import pytest

from config.settings import settings


@pytest.fixture(autouse=True)
def disable_public_publish_windows_by_default():
    previous = settings.enable_public_publish_windows
    settings.enable_public_publish_windows = False
    try:
        yield
    finally:
        settings.enable_public_publish_windows = previous
