"""预筛选 API；复用候选工作台会话/来源/CSRF，不暴露任何生产操作。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 严格输入、配置 CAS、手动检索与独立决定 |
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field


class RuleBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=40)
    keywords: list[str] = Field(min_length=1, max_length=10)
    lookback_hours: int = Field(ge=1, le=720)
    max_duration: int = Field(ge=1, le=1800)
    min_views: int = Field(ge=0, le=10**12)
    min_like_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    candidate_count: int = Field(ge=1, le=50)


class EditRuleBody(RuleBody):
    version: int = Field(ge=1)


class StartBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int = Field(ge=1)
    idempotency: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')


class DecideBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=1)
    content_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: str = Field(pattern=r'^(NEW|SAVED|REJECTED)$')


def create_prefilter_router(service, authorized, call):
    router = APIRouter(prefix='/api/video-prefilter')

    @router.get('/state')
    def state(actor=Depends(authorized)):
        return call(service().prefilter.view)

    @router.post('/rules')
    def create(body: RuleBody, actor=Depends(authorized)):
        return call(service().db.prefilter_save, body.model_dump(), actor, service().clock())

    @router.put('/rules/{rule_id}')
    def edit(rule_id: str, body: EditRuleBody, actor=Depends(authorized)):
        return call(service().db.prefilter_save, body.model_dump(), actor, service().clock(), rule_id=rule_id, version=body.version)

    @router.post('/rules/{rule_id}/search', status_code=202)
    def search(rule_id: str, body: StartBody, actor=Depends(authorized)):
        return call(service().prefilter.start, rule_id, body.version, body.idempotency, actor)

    @router.get('/results')
    def results(job_id: str = Query(min_length=1, max_length=64),
                category: str = Query('', pattern=r'^(|QUALIFIED|REJECTED|INCOMPLETE|FAILED)$'),
                page: int = Query(1, ge=1, le=10000), actor=Depends(authorized)):
        call(service().maintenance)
        return call(service().db.prefilter_results, job_id, category, page)

    @router.post('/jobs/{job_id}/videos/{key}/decision')
    def decide(job_id: str, key: str, body: DecideBody, actor=Depends(authorized)):
        return call(service().prefilter.decide, job_id, key, body.model_dump(), actor)

    return router
