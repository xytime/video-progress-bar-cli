"""src/bot/api_client.py — 与 FastAPI 控制中心通信的异步客户端

高内聚：只负责 HTTP 通信层。使用 httpx.AsyncClient，永远不阻塞 event loop。
断路器：所有请求设 10s timeout，断线返回 None/[] 而非抛出异常（降级处理）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建，TDD Green phase |
| 1.1.0 | 2026-05-22 | Gemini_3.1_Pro_High_planning | [红蓝博弈] 增加 HTTPStatusError 与 ValueError 熔断拦截，防止 502/500 JSON 解析崩溃 |
| 1.1.1 | 2026-05-25 | Gemini_3.5_Flash_High_planning | 增加 add_video API 调用的 timeout 至 45s，防止 yt-dlp 查询超时导致控制中心不可用假警报 |
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)  # [Claude_Sonnet_4.6_Thinking_planning] 断路器：10s 强制熔断


class PipelineAPIClient:
    """异步 HTTP 客户端，封装对 FastAPI 控制中心的所有调用。

    使用方法：
        client = PipelineAPIClient()
        result = await client.add_video(url)
    """

    def __init__(self, base_url: str = "http://localhost:8765"):
        self._base_url = base_url.rstrip("/")

    # ── 私有辅助 ────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        """每次请求创建新的 AsyncClient（短连接，避免连接池泄漏）"""
        return httpx.AsyncClient(base_url=self._base_url, timeout=_TIMEOUT)

    # ── 视频管理 ────────────────────────────────────────────────────────

    async def add_video(self, url: str) -> Optional[dict]:
        """POST /api/videos/add — 手动添加 YouTube 视频到队列。

        Returns:
            dict 响应体，断线返回 None。
        """
        try:
            async with self._client() as c:
                # [Gemini_3.5_Flash_High_planning] yt-dlp 查询元数据可能比较耗时，此处放宽超时限制至 45 秒
                resp = await c.post("/api/videos/add", json={"url": url}, timeout=45.0)
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] add_video failed (API down?): {e}")
            return None

    async def get_videos(self, tab: str = "waitlist", page: int = 1, size: int = 10) -> Optional[list]:
        """GET /api/videos — 获取视频列表。

        Returns:
            video 列表，断线返回 None。
        """
        try:
            async with self._client() as c:
                resp = await c.get("/api/videos", params={"tab": tab, "page": page, "size": size})
                resp.raise_for_status()
                data = resp.json()
                return data.get("videos", [])
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_videos failed (API down?): {e}")
            return None

    async def get_stats(self) -> Optional[dict]:
        """GET /api/stats — 获取系统统计数据。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/stats")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_stats failed (API down?): {e}")
            return None

    async def delete_video(self, youtube_id: str, delete_files: bool = True) -> Optional[dict]:
        """DELETE /api/videos/{youtube_id} — 删除视频任务记录。

        Returns:
            dict 响应体，断线返回 None。
        """
        try:
            async with self._client() as c:
                resp = await c.delete(
                    f"/api/videos/{youtube_id}",
                    # [Claude_Sonnet_4.6_Thinking_planning] P1修复：直接传 bool，httpx 序列化为 "true"/"false"，FastAPI 正确解析
                    params={"delete_files": delete_files}
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] delete_video failed (API down?): {e}")
            return None

    async def retry_video(self, youtube_id: str) -> Optional[dict]:
        """POST /api/videos/{youtube_id}/retry — 重试失败任务。"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/videos/{youtube_id}/retry")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] retry_video failed (API down?): {e}")
            return None

    async def run_pipeline(self) -> Optional[dict]:
        """POST /api/pipeline/run — 触发一次完整管线。"""
        try:
            async with self._client() as c:
                resp = await c.post("/api/pipeline/run")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] run_pipeline failed (API down?): {e}")
            return None
