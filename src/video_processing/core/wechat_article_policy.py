"""微信视频号公众号文章扩展链接策略与身份规范。

仅依赖标准库，不访问平台、浏览器或运行数据库。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-10-12 | Antigravity | 修复 URL 校验漏洞（/s 路径边界、端口/凭据注入检测）；规范化 ArticleIdentity；ArticleTaskDecision 新增版本与摘要。 |
| 1.0.0 | 2026-10-12 | Codex | 初始实现：定义公众号文章身份 (ArticleIdentity)、URL 合法性校验及挂接仲裁契约类型。 |
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import urllib.parse


class AttachmentType(str, Enum):
    """视频号发布页挂接类型契约。"""
    PRODUCT = "PRODUCT"
    ARTICLE = "ARTICLE"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


def is_valid_mp_article_url(url: str | None) -> bool:
    """校验微信公众号文章 URL 是否合法且属于 mp.weixin.qq.com。

    必须为以 https/http 开头、域名为 mp.weixin.qq.com 的永久文章链接（/s/... 或 /s?__biz=...）。
    杜绝路径边界绕过（如 /settings, /shop 等）、杜绝端口/用户凭据注入、杜绝空白与控制字符。
    """
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return False
    # 严格禁止任何位置包含空白字符、换行符或注入字符
    if any(c.isspace() for c in url) or any(c in url for c in ("\r", "\n", "\t", "<", ">", '"', "'", "`", "\\")):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if hostname != "mp.weixin.qq.com":
            return False
        # 严禁用户名/密码凭据注入以及非标端口伪造
        if parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 80, 443):
            return False
        path = parsed.path
        # 必须是 /s 或以 /s/ 开头（避免 /settings, /shop, /service 等非文章路径匹配）
        if path != "/s" and not path.startswith("/s/"):
            return False
        if path == "/s" and not parsed.query:
            return False
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class ArticleIdentity:
    """公众号文章身份契约。"""

    url: str
    title: str = ""

    def __post_init__(self) -> None:
        clean_url = (self.url or "").strip()
        object.__setattr__(self, "url", clean_url)
        clean_title = (self.title or "").strip()
        object.__setattr__(self, "title", clean_title)
        if not is_valid_mp_article_url(self.url):
            raise ValueError(f"非法公众号文章 URL: {self.url!r}")
        if self.title and any(c in self.title for c in ("\r", "\n")):
            raise ValueError(f"非法文章标题: {self.title!r}")


@dataclass(frozen=True)
class ArticleTaskDecision:
    """单视频文章挂接任务意图与目标。"""

    task_id: str
    url: str
    title: str = ""
    require_article: bool = False
    reason: str = "MANUAL_OR_MAPPED_ARTICLE"
    publisher_capability: str = "wechat-article-task-v1"
    config_version: str = "1.0.0"
    config_digest: str = ""

