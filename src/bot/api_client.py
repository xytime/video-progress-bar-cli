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
| 1.8.0 | 2026-07-05 | Codex | 新增 get_wechat_status()，供 /status 首屏展示发布登录态 |
| 1.9.0 | 2026-07-05 | Codex | 新增 get_video_page() 返回 total_count，供 /status 展示失败总数与最近失败样例 |
| 1.10.0 | 2026-07-05 | Codex | 新增 retry_recent_preview()，供 /status 展示 /retry 24 会影响几条 |
| 1.11.0 | 2026-08-09 | Codex | add_video 透传内容生产类型，支持英语世界短视频的显式入库标识 |
| 1.12.0 | 2026-08-20 | Codex | 新增 Highlight Job 的显式选择、创建和状态查询 API 封装；不包含发布接口 |
| 1.13.0 | 2026-08-20 | Codex | 新增 Highlight Clip 人工选定与独立发布主体创建接口；不触发发布 |
| 1.14.0 | 2026-08-21 | Codex | 新增英语世界短视频候选研究、选定和二次制作确认接口；不触发发布 |
| 1.15.0 | 2026-08-23 | Codex | 新增英语世界审核项的显式视频号投稿批准与搁置接口。 |
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

    async def add_video(self, url: str, trim_start: Optional[str] = None, trim_end: Optional[str] = None, disable_slicing: Optional[bool] = None, tts_provider: Optional[str] = None, content_type: Optional[str] = None) -> Optional[dict]:  # [Claude_Sonnet_4.6_Thinking_planning]
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
                if content_type is not None:
                    payload["content_type"] = content_type
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

    async def get_highlight_sources(self, *, limit: int = 10, offset: int = 0) -> Optional[list]:
        """GET /api/highlights/sources — 读取可显式选择的源视频。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/highlights/sources", params={"limit": limit, "offset": offset})
                resp.raise_for_status()
                return resp.json().get("sources", [])
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_highlight_sources failed: {e}")
            return None

    async def create_highlight_job(
        self,
        source_youtube_id: str,
        *,
        max_clips: int = 3,
        min_duration_sec: float = 35,
        max_duration_sec: float = 90,
        requested_by: str = "telegram",
    ) -> Optional[dict]:
        """POST /api/highlights/jobs — 创建候选分析任务，不会发布。"""
        try:
            async with self._client() as c:
                resp = await c.post(
                    "/api/highlights/jobs",
                    json={
                        "source_youtube_id": source_youtube_id,
                        "max_clips": max_clips,
                        "min_duration_sec": min_duration_sec,
                        "max_duration_sec": max_duration_sec,
                        "requested_by": requested_by,
                    },
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] create_highlight_job failed: {e}")
            return None

    async def get_highlight_jobs(self, *, limit: int = 10) -> Optional[list]:
        """GET /api/highlights/jobs — 读取独立 Highlight Job 的当前状态。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/highlights/jobs", params={"limit": limit})
                resp.raise_for_status()
                return resp.json().get("jobs", [])
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_highlight_jobs failed: {e}")
            return None

    async def select_highlight_clip(self, clip_id: str) -> Optional[dict]:
        """POST /api/highlights/clips/{id}/select — 选定候选，不会渲染或发布。"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/highlights/clips/{clip_id}/select")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] select_highlight_clip failed: {e}")
            return None

    async def create_english_world_research(
        self, *, requested_by: str = "telegram", notification_target: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Optional[dict]:
        """POST /api/english-world/research — 只启动候选研究，不下载、制作或发布。"""
        try:
            async with self._client() as c:
                payload = {"requested_by": requested_by, "notification_target": notification_target}
                if source_url:
                    payload["source_url"] = source_url
                resp = await c.post("/api/english-world/research", json=payload, timeout=45.0)
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] create_english_world_research failed: {e}")
            return None

    async def get_english_world_jobs(self, *, limit: int = 10) -> Optional[list]:
        """GET /api/english-world/jobs — 读取独立研究/制作请求状态。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/english-world/jobs", params={"limit": limit})
                resp.raise_for_status()
                return resp.json().get("jobs", [])
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_english_world_jobs failed: {e}")
            return None

    async def select_english_world_candidate(self, candidate_id: str) -> Optional[dict]:
        """POST candidate select — 选题后仍需要独立制作确认。"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/english-world/candidates/{candidate_id}/select")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] select_english_world_candidate failed: {e}")
            return None

    async def request_english_world_production(self, job_id: str) -> Optional[dict]:
        """POST production request — 仅登记二次确认，绝不触发平台投递。"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/english-world/jobs/{job_id}/request-production")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] request_english_world_production failed: {e}")
            return None

    async def approve_english_world_submission(self, review_id: str) -> Optional[dict]:
        """POST 审核项投稿批准；仅接受服务端绑定的一次性审核 ID。"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/english-world/review-items/{review_id}/approve-submission")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] approve_english_world_submission failed: {e}")
            return None

    async def get_english_world_review_items(self, *, limit: int = 10) -> Optional[list]:
        """GET 英语世界审核/投稿回执；只读，不触发 worker。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/english-world/review-items", params={"limit": limit})
                resp.raise_for_status()
                return resp.json().get("items", [])
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_english_world_review_items failed: {e}")
            return None

    async def hold_english_world_review_item(self, review_id: str) -> Optional[dict]:
        """POST 搁置某条待审核学习卡；不触发制作或投稿。"""
        try:
            async with self._client() as c:
                resp = await c.post(f"/api/english-world/review-items/{review_id}/hold")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] hold_english_world_review_item failed: {e}")
            return None

    async def get_video_page(self, tab: str = "waitlist", page: int = 1, size: int = 10) -> Optional[dict]:
        """GET /api/videos — 获取分页原始响应，包含 total_count。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/videos", params={"tab": tab, "page": page, "size": size})
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_video_page failed (API down?): {e}")
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

    async def get_wechat_status(self) -> Optional[dict]:
        """GET /api/wechat/status — 获取微信视频号发布登录态。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/wechat/status")
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] get_wechat_status failed (API down?): {e}")
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
        """POST /api/videos/retry-recent?hours=N — 批量重试最近 N 小时内失败/需登录任务。"""
        try:
            async with self._client() as c:
                resp = await c.post("/api/videos/retry-recent", params={"hours": hours})
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] retry_recent failed (API down?): {e}")
            return None

    async def retry_recent_preview(self, hours: int) -> Optional[dict]:
        """GET /api/videos/retry-recent/preview?hours=N — 只读预览批量重试影响范围。"""
        try:
            async with self._client() as c:
                resp = await c.get("/api/videos/retry-recent/preview", params={"hours": hours})
                resp.raise_for_status()
                return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.warning(f"[api_client] retry_recent_preview failed (API down?): {e}")
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
