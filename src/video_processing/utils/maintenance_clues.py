"""旧热词中枢的维护适配器；缓存只读、刷新作为有限单项登记。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-12 | Codex | 接入现有 SWR 协议，避免只读 Web GET 留下未登记刷新线程 |
"""
import time
from config.settings import settings
from ..core.maintenance import gate, spawn_admitted, running, MaintenanceDenied


def read_clues(hub):
    cache = hub._read_cache()
    keywords = hub._normalize_cached_keywords(cache.get("keywords", [])) if cache else []
    updated = cache.get("updated_at") if cache else None
    local = hub._format_response(keywords, source="cache" if cache else "static", updated_at=updated)
    if not running() or not settings.enable_dynamic_keywords:
        return local
    if cache:
        if time.time() - (updated or 0) >= 3600:
            try:
                spawn_admitted(hub.refresh_sync, role="topic-clues-refresh", object_key="topic-clues-refresh",
                               name="topic-clues-bg-refresh")
            except MaintenanceDenied:
                pass
        return local
    with gate().admit("topic-clues-refresh", "topic-clues-refresh") as ticket:
        ticket.start()
        return hub.refresh_sync()
