"""微信视频号助手浏览器上下文工厂。

统一收拢微信视频号助手上传、保活、复用检验与独立新上下文验证的 Viewport、真实 Chrome UA
以及 anti-detection init_script 浏览器环境指纹配置，确保各调用入口（初始上传器、内部复用门禁、
保活心跳、独立会话检验）保持一致的基础运行环境与配置，消除配置漂移风险。

# Modification History
| Version | Date       | Author      | Description                                                  |
|---------|------------|-------------|--------------------------------------------------------------|
| 1.0.0   | 2026-09-28 | Antigravity | 初始版本：统一创建微信视频号浏览器上下文，收拢 UA、Viewport 与 init_script 反检测指纹。 |
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

# 统一微信视频号视口规格（1280x800）
WECHAT_VIEWPORT: dict[str, int] = {"width": 1280, "height": 800}

# 统一微信视频号真实 Chrome UA
WECHAT_USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 统一反检测浏览器指纹脚本（覆盖 webdriver、window.chrome、plugins、languages 与 permissions）
WECHAT_INIT_SCRIPT: str = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.chrome = {
    runtime: {},
    loadTimes: function(){},
    csi: function(){},
    app: {}
};
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
const _oq = window.navigator.permissions.query;
window.navigator.permissions.query = (p) =>
    p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : _oq(p);
delete window.__playwright;
delete window.__pw_manual;
delete window._phantom;
"""

__all__ = [
    "WECHAT_VIEWPORT",
    "WECHAT_USER_AGENT",
    "WECHAT_INIT_SCRIPT",
    "create_wechat_context",
]


def create_wechat_context(
    browser: Any,
    storage_state: Path | str | Mapping[str, Any] | None = None,
) -> Any:
    """创建配置了统一微信环境指纹的全新独立浏览器上下文。

    Args:
        browser: Playwright Browser 实例。
        storage_state: 可选的会话凭证路径（Path/str）或字典对象；为 None 时创建干净上下文（如 relogin 或初次授权）。

    Returns:
        注入了统一反检测指纹脚本的 Playwright BrowserContext 实例。
    """
    context_opts: dict[str, Any] = {
        "viewport": dict(WECHAT_VIEWPORT),
        "user_agent": WECHAT_USER_AGENT,
    }

    if storage_state is not None:
        context_opts["storage_state"] = str(storage_state) if isinstance(storage_state, Path) else storage_state

    context = browser.new_context(**context_opts)
    context.add_init_script(WECHAT_INIT_SCRIPT)
    return context
