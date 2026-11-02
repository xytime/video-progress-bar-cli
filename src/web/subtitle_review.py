"""字幕人工复核与单次放行 API；不清理产物、不更改内容审核或提交保护。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 只读当前证据、具名 CAS 放行；新旧失败共用 DAL。 |
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


class SubtitleReleaseRequest(BaseModel):
    expected_review_token: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_receipt_sha: str = Field(pattern=r'^[0-9a-f]{64}$')
    actor: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1000)


def create_subtitle_review_router(db):
    router = APIRouter()

    @router.get('/api/videos/{youtube_id}/subtitle-review')
    def review(youtube_id: str, slice_index: int = 0):
        video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
        if not video:
            raise HTTPException(404, '视频不存在')
        return {'success': True, **db.get_subtitle_manual_review(video['id'])}

    @router.post('/api/videos/{youtube_id}/subtitle-release')
    def release(youtube_id: str, body: SubtitleReleaseRequest, request: Request, slice_index: int = 0):
        # 浏览器必须同源；无 Origin 的本机运维客户端仍可走正式 API。
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '字幕放行请求必须同源')
        video = db.get_video_by_youtube_id(youtube_id, slice_index=slice_index)
        if not video:
            raise HTTPException(404, '视频不存在')
        try:
            accepted = db.release_subtitle_recovery_after_repair(video['id'], body.expected_receipt_sha,
                expected_review_token=body.expected_review_token, actor=body.actor, reason=body.reason)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not accepted:
            raise HTTPException(409, '当前失败证据已变化、已经放行或仍有投稿/身份保护；请重新复核')
        return {'success': True, 'video_id': video['id'], 'youtube_id': youtube_id,
                'slice_index': slice_index, 'status': 'PENDING', 'allowed_claims': 1,
                'message': '已记录人工复核并放行一次领取；后续仍须通过全部加工和发布门禁'}

    return router
