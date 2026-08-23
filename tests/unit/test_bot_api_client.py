"""tests/unit/test_bot_api_client.py — API 客户端 TDD (Red → Green)

使用 respx 模拟 FastAPI 接口，验证 api_client 的调用合约。
测试纯粹在内存中运行，不需要真实的 FastAPI 服务。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | TDD Red phase: 先写测试定义合约 |
| 1.1.0 | 2026-06-01 | Gemini_3.5_Flash_planning | 新增 respec_video API 接口调用契约单元测试 |
| 1.3.0 | 2026-08-20 | Codex | 新增 Highlight Clip 人工选定接口调用契约 |
| 1.2.0 | 2026-08-20 | Codex | 新增 Highlight Job 选择、创建和状态读取 API 调用契约 |
| 1.4.0 | 2026-08-21 | Codex | 覆盖英语世界候选研究、选题和二次制作确认接口的发布隔离。 |
"""
import json

import pytest
import respx
import httpx
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

BASE_URL = "http://localhost:8765"


@pytest.fixture
def api_client():
    """创建一个指向 localhost:8765 的 API 客户端"""
    from bot.api_client import PipelineAPIClient
    return PipelineAPIClient(base_url=BASE_URL)


@pytest.mark.asyncio
class TestAddVideo:
    """测试 /api/videos/add 的调用合约"""

    @respx.mock
    async def test_add_video_success(self, api_client):
        """成功添加视频时应返回 title 和 video_id"""
        respx.post(f"{BASE_URL}/api/videos/add").mock(
            return_value=httpx.Response(200, json={
                "success": True,
                "video_id": "PtbZY9HCatE",
                "title": "AI巨头IPO暗战",
                "channel_name": "Bloomberg"
            })
        )
        result = await api_client.add_video("https://youtu.be/PtbZY9HCatE")
        assert result["success"] is True
        assert result["title"] == "AI巨头IPO暗战"

    @respx.mock
    async def test_add_video_duplicate(self, api_client):
        """视频已存在时应返回 already_exists 标志"""
        respx.post(f"{BASE_URL}/api/videos/add").mock(
            return_value=httpx.Response(200, json={
                "success": False,
                "already_exists": True,
                "current_status": "DOWNLOADING",
                "error": "视频已在队列中"
            })
        )
        result = await api_client.add_video("https://youtu.be/PtbZY9HCatE")
        assert result["success"] is False
        assert result.get("already_exists") is True

    @respx.mock
    async def test_add_video_api_down_returns_none(self, api_client):
        """FastAPI 断线时应返回 None，不抛出异常"""
        respx.post(f"{BASE_URL}/api/videos/add").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        result = await api_client.add_video("https://youtu.be/abc123")
        assert result is None  # 降级处理，不崩溃


@pytest.mark.asyncio
class TestGetVideos:
    """测试 /api/videos 的调用合约"""

    @respx.mock
    async def test_get_queue(self, api_client):
        """获取处理队列应返回 videos 列表"""
        respx.get(f"{BASE_URL}/api/videos").mock(
            return_value=httpx.Response(200, json={
                "videos": [
                    {"youtube_id": "abc", "title": "Test", "status": "PENDING"}
                ],
                "total_count": 1
            })
        )
        result = await api_client.get_videos(tab="waitlist")
        assert isinstance(result, list)
        assert result[0]["youtube_id"] == "abc"

    @respx.mock
    async def test_get_videos_api_down_returns_empty(self, api_client):
        """FastAPI 断线时返回 None，不抛出异常"""
        respx.get(f"{BASE_URL}/api/videos").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        result = await api_client.get_videos(tab="waitlist")
        assert result is None


@pytest.mark.asyncio
class TestHighlightJobs:
    """Highlight Job 仅调用候选分析接口，不能出现发布请求。"""

    @respx.mock
    async def test_get_sources(self, api_client):
        respx.get(f"{BASE_URL}/api/highlights/sources").mock(
            return_value=httpx.Response(200, json={"sources": [{"youtube_id": "abc123def45"}]})
        )
        result = await api_client.get_highlight_sources(limit=10)
        assert result == [{"youtube_id": "abc123def45"}]

    @respx.mock
    async def test_create_job_is_analysis_only(self, api_client):
        route = respx.post(f"{BASE_URL}/api/highlights/jobs").mock(
            return_value=httpx.Response(200, json={"success": True, "job": {"id": "a" * 32}})
        )
        result = await api_client.create_highlight_job("abc123def45")
        assert result["success"] is True
        assert route.called
        assert json.loads(route.calls.last.request.content)["requested_by"] == "telegram"

    @respx.mock
    async def test_get_jobs(self, api_client):
        respx.get(f"{BASE_URL}/api/highlights/jobs").mock(
            return_value=httpx.Response(200, json={"jobs": [{"id": "a" * 32, "state": "CANDIDATES_READY"}]})
        )
        result = await api_client.get_highlight_jobs()
        assert result[0]["state"] == "CANDIDATES_READY"

    @respx.mock
    async def test_select_clip_keeps_render_and_publish_out_of_scope(self, api_client):
        clip_id = "a" * 32
        route = respx.post(f"{BASE_URL}/api/highlights/clips/{clip_id}/select").mock(
            return_value=httpx.Response(200, json={
                "success": True,
                "clip": {"id": clip_id, "publication_subject_id": f"highlight_clip:{clip_id}"},
            })
        )

        result = await api_client.select_highlight_clip(clip_id)

        assert route.called
        assert result["clip"]["publication_subject_id"] == f"highlight_clip:{clip_id}"


@pytest.mark.asyncio
class TestEnglishWorldJobs:
    """英语世界接口只研究、选题和登记生产请求，不触发通用视频添加。"""

    @respx.mock
    async def test_research_request_is_not_generic_video_enqueue(self, api_client):
        route = respx.post(f"{BASE_URL}/api/english-world/research").mock(
            return_value=httpx.Response(200, json={"success": True, "job": {"id": "a" * 32}})
        )

        result = await api_client.create_english_world_research(notification_target="123")

        assert result["success"] is True
        assert json.loads(route.calls.last.request.content)["notification_target"] == "123"

    @respx.mock
    async def test_selection_and_production_request_have_separate_endpoints(self, api_client):
        candidate_id = "a" * 32
        job_id = "b" * 32
        respx.post(f"{BASE_URL}/api/english-world/candidates/{candidate_id}/select").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        route = respx.post(f"{BASE_URL}/api/english-world/jobs/{job_id}/request-production").mock(
            return_value=httpx.Response(200, json={"success": True, "job": {"state": "PRODUCTION_REQUESTED"}})
        )

        selected = await api_client.select_english_world_candidate(candidate_id)
        requested = await api_client.request_english_world_production(job_id)

        assert selected["success"] is True
        assert requested["job"]["state"] == "PRODUCTION_REQUESTED"
        assert route.called


@pytest.mark.asyncio
class TestDeleteVideo:
    """测试 DELETE /api/videos/{youtube_id} 的调用合约"""

    @respx.mock
    async def test_delete_video_success(self, api_client):
        """删除成功"""
        respx.delete(f"{BASE_URL}/api/videos/abc123").mock(
            return_value=httpx.Response(200, json={"success": True, "message": "已彻底清除"})
        )
        result = await api_client.delete_video("abc123")
        assert result["success"] is True

    @respx.mock
    async def test_delete_video_not_found(self, api_client):
        """视频不存在时应返回 success=False"""
        respx.delete(f"{BASE_URL}/api/videos/notexist").mock(
            return_value=httpx.Response(200, json={"success": False, "error": "视频不存在"})
        )
        result = await api_client.delete_video("notexist")
        assert result["success"] is False


@pytest.mark.asyncio
class TestRetryVideo:
    """测试 POST /api/videos/{youtube_id}/retry 的调用合约"""

    @respx.mock
    async def test_retry_video_success(self, api_client):
        """重试成功"""
        respx.post(f"{BASE_URL}/api/videos/abc123/retry").mock(
            return_value=httpx.Response(200, json={"success": True, "triggered": True})
        )
        result = await api_client.retry_video("abc123")
        assert result["success"] is True


@pytest.mark.asyncio
class TestRespecVideo:
    """测试 POST /api/videos/{youtube_id}/respec 的调用合约"""

    @respx.mock
    async def test_respec_video_success(self, api_client):
        """覆盖规格成功"""
        respx.post(f"{BASE_URL}/api/videos/abc123/respec").mock(
            return_value=httpx.Response(200, json={
                "success": True,
                "youtube_id": "abc123",
                "title": "Test Video",
                "trim_start": "0",
                "trim_end": "10",
                "disable_slicing": True,
                "tts_provider": "indextts",
                "was_stopped": True,
                "triggered": True
            })
        )
        result = await api_client.respec_video(
            "abc123",
            trim_start="0",
            trim_end="10",
            disable_slicing=True,
            tts_provider="indextts"
        )
        assert result["success"] is True
        assert result["trim_start"] == "0"
        assert result["tts_provider"] == "indextts"
        assert result["was_stopped"] is True

    @respx.mock
    async def test_respec_video_api_down_returns_none(self, api_client):
        """FastAPI 断线时应返回 None，不抛出异常"""
        respx.post(f"{BASE_URL}/api/videos/abc123/respec").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        result = await api_client.respec_video("abc123", trim_start="0")
        assert result is None
