"""src/bot/api_client.py — 与 FastAPI 控制中心通信的异步客户端

高内聚：只负责 HTTP 通信层。使用 httpx.AsyncClient，永远不阻塞 event loop。
断路器：所有请求设 10s timeout，断线返回 None/[] 而非抛出异常（降级处理）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 初始创建，TDD Green phase |
| 1.1.0 | 2026-05-22 | Gemini_3.1_Pro_High_planning | [红蓝博弈] 增加 HTTPStatusError 与 ValueError 熔断拦截，防止 502/500 JSON 解析崩溃 |
| 1.1.1 | 2026-05-25 | Gemini_3.5_Flash_High_planning | 增加 add_video API 调用的 timeout 至 45s，防止 yt-dlp 查询超时导致控制中心不可用假警报 |
| 1.2.0 | 2026-05-27 | Gemini_3.5_Flash_High_planning | 新增 get_slices, retry_slice, delete_slice API 调用封装 |
| 1.3.0 | 2026-05-27 | Gemini_3.5_Flash_planning | 为 add_video 新增 disable_slicing 参数支持 |
| 1.4.0 | 2026-05-29 | Claude_Sonnet_4.6_Thinking_planning | 为 add_video 新增 tts_provider 参数支持，供 Telegram /tts 命令按需指定配音 |
| 1.5.0 | 2026-06-01 | Claude_Sonnet_4.6_Thinking_planning | 新增 respec_video() 封装，供 Bot 侧在 already_exists 时自动调用规格覆盖 |
| 1.6.0 | 2026-06-20 | Claude_Opus_4.8 | 新增 process_video()：POST /api/videos/{id}/process，供 /process 命令与 Agent 工具确定性触发单条视频处理（忽略分数阈值） |
| 1.7.0 | 2026-06-28 | Claude_Opus_4.8 | 新增 retry_recent(hours)：POST /api/videos/retry-recent，供 /retry <小时数> 批量重试最近 N 小时失败任务 |
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)  # [Claude_Sonnet_4.6_Thinking_planning] 断路器：10s 强制熔断


class PipelineAPIClient:
    """异步 HTTP 客户端，封装对 FastAPI 控制中心的所有调用。

    使用方法：
        client = PipelineAPIClient()
        result = await client.add_video(url)
    """

    def __init__(self, base_url: Optional[str] = None):
        # 端口单一真相源 settings.dashboard_port（见 PORTS.md，9100-9199 区间）
        self._base_url = (base_url or f"http://localhost:{settings.dashboard_port}").rstrip("/")

    # ── 私有辅助 ────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        """每次请求创建新的 AsyncClient（短连接，避免连接池泄漏）"""
        return httpx.AsyncClient(base_url=self._base_url, timeout=_TIMEOUT)

    # ── 视频管理 ────────────────────────────────────────────────────────

    async def add_video(self, url: str, trim_start: Optional[str] = None, trim_end: Optional[str] = None, disable_slicing: Optional[bool] = None, tts_provider: Optional[str] = None) -> Optional[dict]:  # [Claude_Sonnet_4.6_Thinking_planning]
        """POST /api/videos/add — 手动添加 YouTube 视频到队列。

        Returns:
            dict 响应体，断线返回 None。
        """
        try:
            async with self._client() as c:
                payload = {"url": url}
                if trim_start is not None:
                    payload["trim_start"] = trim_start
                if trim_end is not None:
                    payload["trim_end"] = trim_end
                if disable_slicing is not None:
                    payload["disable_slicing"] = disable_slicing
                if tts_provider is not None:
                    payload["tts_provider"] = tts_provider  # [Claude_Sonnet_4.6_Thinking_planning]
                # [Gemini_3.5_Flash_High_planning] yt-dlp 查询元数据可能比较耗时，此处放宽超时限制至 45 秒
                resp = await c.post("/api/videos/add", json=payload, timeout=45.0)
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

    async def respec_video(
        self,
        youtube_id: str,
        trim_start: Optional[str] = None,
        trim_end: Optional[str] = None,
        disable_slicing: Optional[bool] = None,
        tts_provider: Optional[str] = None,
    ) -> Optional[dict]:
        """POST /api/videos/{youtube_id}/respec — 覆盖规格并重新触发处理。

        [Claude_Sonnet_4.6_Thinking_planning] 供 Bot 侧在 already_exists 且有裁剪参数/TTS要求时自动调用。
        """
        try:
            async with self._client() as c:
                payload: dict = {}
                if trim_start is not None:
                    payload["trim_start"] = trim_start
                if trim_end is not None:
                    payload["trim_end"] = trim_end
                if disable_slicing is not None:
                    payload["disable_slicing"] = disable_slicing
                if tts_provider is not None:
                    payload["tts_provider"] = tts_provider
                resp = await c.post(
                    f"/api/videos/{youtube_id}/respec",
                    json=payload,
                    timeout=15.0,  # kill 处理最长约 2s+超时，15s 包含内容
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] respec_video failed: {e}")
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

    async def retry_recent(self, hours: int) -> Optional[dict]:
        """POST /api/videos/retry-recent?hours=N — 批量重试最近 N 小时内 FAILED 的任务。"""
        try:
            async with self._client() as c:
                resp = await c.post("/api/videos/retry-recent", params={"hours": hours})
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] retry_recent failed (API down?): {e}")
            return None

    async def process_video(self, youtube_id: str) -> Optional[dict]:
        """POST /api/videos/{youtube_id}/process — 立即处理指定视频（忽略分数阈值，后台执行）。"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/videos/{youtube_id}/process")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] process_video failed (API down?): {e}")
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

    async def get_slices(self, youtube_id: str) -> Optional[list]:
        """GET /api/videos/{youtube_id}/slices — 获取主视频下的所有切片子任务"""
        try:
            async with self._client() as c:
                resp = await c.get(f"/api/videos/{youtube_id}/slices")
                resp.raise_for_status()
                data = resp.json()
                return data.get("slices", [])
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_slices failed: {e}")
            return None

    async def retry_slice(self, youtube_id: str, slice_index: int) -> Optional[dict]:
        """POST /api/videos/{youtube_id}/slices/{slice_index}/retry — 重试单个切片任务"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/videos/{youtube_id}/slices/{slice_index}/retry")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] retry_slice failed: {e}")
            return None

    async def delete_slice(self, youtube_id: str, slice_index: int, delete_files: bool = True) -> Optional[dict]:
        """DELETE /api/videos/{youtube_id}?slice_index={slice_index} — 删除单个切片任务"""
        try:
            async with self._client() as c:
                resp = await c.delete(
                    f"/api/videos/{youtube_id}",
                    params={"delete_files": delete_files, "slice_index": slice_index}
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] delete_slice failed: {e}")
            return None
