"""视频号二级回复工作台与运营策略路由（支持服务端多维筛选、最新优先排序、分页账本及策略 CAS 热加载）。

# Modification History
| reply-recovery-v1 | 2026-10-25 | Codex | 迁移后保存复用本机会话与活动版本，区分校验失败和真实并发冲突。 |
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.0.0 | 2026-10-18 | Antigravity | 重设计 /api/secondary-reply-settings/history：支持服务端分页 (page/size)、默认最新在最上排序 (newest_desc/comment_time_desc 等)、多维筛选 (status/platform_post_id/style/provider_kind/time_window/search) 与视频中英标题补齐 |
| 1.1.0 | 2026-10-18 | Antigravity | 新增 /api/secondary-reply-settings/history 端点，提供二级回复任务与自动回复历史账本查询 |
| 1.0.0 | 2026-10-18 | Antigravity | 初始创建：提供二级回复运营策略读取、CAS 原子保存与立即热加载 API |
"""

from __future__ import annotations

import datetime
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from video_processing.db.database import PipelineDB
from video_processing.utils.secondary_reply_policy import (
    PolicyConflict,
    digest,
    load_policy,
    save_policy,
    policy_view,
)
from config.settings import settings
from config.runtime_policy import ConfigurationUnavailable

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class SecondaryReplySaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def _parse_utc_to_epoch(val: Any) -> int:
    """将数据库 UTC 时间字符串或 ISO 字符串转换为秒级时间戳（用于时间窗过滤与兜底排序）。"""
    raw = str(val or "").strip()
    if not raw:
        return 0
    try:
        if "T" in raw:
            dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=datetime.timezone.utc
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0


def _comment_epoch(item: dict[str, Any]) -> int:
    """提取原评论发布时间戳（秒），若缺失则回退至首次发现时间或任务创建时间。"""
    ct = str(item.get("comment_createtime") or "").strip()
    if ct.isdigit():
        val = int(ct)
        return val // 1000 if val > 10_000_000_000 else val
    return _parse_utc_to_epoch(item.get("comment_discovered_at")) or _parse_utc_to_epoch(
        item.get("created_at")
    )


def create_secondary_reply_settings_router(
    *,
    active: Path,
    history_lookup: Optional[Callable[[int], list[dict[str, Any]]]] = None,
    access_db: Optional[PipelineDB] = None,
) -> APIRouter:
    router = APIRouter()
    static_dir = Path(__file__).parent / "static"
    output_dir = Path(__file__).resolve().parents[2] / "output"

    from .local_runtime_access import create_runtime_access
    # 仅迁移后的配置写入需要配置中心权限，旧离线策略工具保持原合同。
    boundary, authorized, page_response = create_runtime_access(access_db, settings.dashboard_port)

    async def access(request: Request, response: Response):
        if settings.runtime_configuration_enabled:
            boundary(request)
            return await authorized(request, response)
        return 'legacy-reply-settings'

    def origin_check(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(403, "请从当前控制台页面操作")

    def view(config: dict) -> dict:
        return dict(config=config, digest=digest(config))

    def _enrich_item(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        yid = str(item.get("youtube_id") or "").strip()
        slice_idx = int(item.get("slice_index") or 0)
        if yid:
            prefix = yid if slice_idx == 0 else f"{yid}_s{slice_idx}"
            title_file = output_dir / f"{prefix}_title.txt"
            copy_file = output_dir / f"{prefix}_copy.txt"
            zh_short = ""
            if title_file.is_file():
                try:
                    lines = title_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                    zh_short = lines[0].strip() if lines else ""
                except OSError:
                    zh_short = ""
            copy_lead = ""
            if copy_file.is_file():
                try:
                    raw_copy = copy_file.read_text(encoding="utf-8", errors="ignore").strip()
                    if raw_copy:
                        first_line = raw_copy.splitlines()[0].strip()
                        copy_lead = first_line[:96] + ("…" if len(first_line) > 96 else "")
                except OSError:
                    copy_lead = ""
            if zh_short:
                item["video_zh_title"] = zh_short
                item["video_title"] = zh_short
            if copy_lead:
                item["video_copy_lead"] = copy_lead
        item["comment_epoch"] = _comment_epoch(item)
        return item

    @router.get("/secondary-reply-settings", response_class=HTMLResponse)
    def page(request: Request) -> HTMLResponse:
        html_path = Path(__file__).parent / "templates" / "secondary_reply_settings.html"
        content = html_path.read_text(encoding="utf-8")
        css_path = static_dir / "css" / "secondary_reply_settings.css"
        js_path = static_dir / "js" / "secondary_reply_settings.js"
        css_v = int(css_path.stat().st_mtime) if css_path.exists() else int(time.time())
        js_v = int(js_path.stat().st_mtime) if js_path.exists() else int(time.time())
        content = re.sub(
            r'/static/css/secondary_reply_settings\.css(?:\?v=[^"\'\s>]+)?',
            f"/static/css/secondary_reply_settings.css?v={css_v}",
            content,
        )
        content = re.sub(
            r'/static/js/secondary_reply_settings\.js(?:\?v=[^"\'\s>]+)?',
            f"/static/js/secondary_reply_settings.js?v={js_v}",
            content,
        )
        if settings.runtime_configuration_enabled:
            boundary(request)
            return page_response(request, content)
        return HTMLResponse(
            content,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @router.get("/api/secondary-reply-settings")
    def read(actor=Depends(access)) -> dict:
        try:
            return policy_view(active)
        except (ValueError, OSError) as exc:
            raise HTTPException(503, "二级回复策略读取失败，请检查配置文件后重新载入。") from exc

    @router.get("/api/secondary-reply-settings/history")
    def history(
        page: int = 1,
        size: Optional[int] = None,
        limit: Optional[int] = None,
        sort: str = "newest_desc",
        status: str = "all",
        platform_post_id: str = "",
        style: str = "all",
        provider_kind: str = "all",
        time_window: str = "all",
        search: str = "",
    ) -> dict:
        try:
            fetch_limit = 500 if history_lookup is None else max(50, int(limit or 500))
            raw_items = (
                history_lookup(fetch_limit)
                if history_lookup is not None
                else PipelineDB().list_secondary_reply_history(limit=fetch_limit)
            )
            all_items = [_enrich_item(r) for r in raw_items]

            # 1. 全局状态计数与筛选项聚合（基于全量账本，不受当前筛选影响）
            counts: dict[str, int] = {}
            video_map: dict[str, dict[str, Any]] = {}
            styles_set: set[str] = set()
            for row in all_items:
                st = str(row.get("status") or "UNKNOWN")
                counts[st] = counts.get(st, 0) + 1
                pid = str(row.get("platform_post_id") or "").strip()
                if pid:
                    if pid not in video_map:
                        vtitle = (
                            str(row.get("video_zh_title") or "").strip()
                            or str(row.get("video_title") or "").strip()
                            or str(row.get("video_en_title") or "").strip()
                            or pid[-16:]
                        )
                        video_map[pid] = {
                            "platform_post_id": pid,
                            "video_title": vtitle,
                            "count": 0,
                        }
                    video_map[pid]["count"] += 1
                row_style = str(row.get("style") or "").strip()
                if row_style:
                    styles_set.add(row_style)

            # 2. 多维过滤
            filtered = all_items
            status_norm = (status or "all").strip().upper()
            if status_norm and status_norm != "ALL":
                if status_norm == "ACTIONABLE":
                    filtered = [
                        r for r in filtered if str(r.get("status") or "") in {"APPROVED", "PENDING_REVIEW"}
                    ]
                elif status_norm == "INACTIVE":
                    filtered = [
                        r for r in filtered if str(r.get("status") or "") in {"SKIPPED", "MANUAL"}
                    ]
                else:
                    filtered = [r for r in filtered if str(r.get("status") or "") == status_norm]

            post_norm = (platform_post_id or "").strip()
            if post_norm and post_norm != "all":
                filtered = [r for r in filtered if str(r.get("platform_post_id") or "") == post_norm]

            style_norm = (style or "all").strip().upper()
            if style_norm and style_norm != "ALL":
                filtered = [r for r in filtered if str(r.get("style") or "").upper() == style_norm]

            prov_norm = (provider_kind or "all").strip().lower()
            if prov_norm == "ai":
                filtered = [
                    r
                    for r in filtered
                    if str(r.get("provider") or "").lower().startswith(("codex", "agy", "gemini"))
                ]
            elif prov_norm == "manual":
                filtered = [
                    r for r in filtered if "manual" in str(r.get("provider") or "").lower()
                ]

            win_norm = (time_window or "all").strip().lower()
            if win_norm and win_norm != "all":
                now_bj = datetime.datetime.now(SHANGHAI_TZ)
                now_ts = int(now_bj.timestamp())
                if win_norm == "24h":
                    cutoff = now_ts - 86400
                elif win_norm == "today_bj":
                    midnight_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
                    cutoff = int(midnight_bj.timestamp())
                elif win_norm == "7d":
                    cutoff = now_ts - 7 * 86400
                elif win_norm == "30d":
                    cutoff = now_ts - 30 * 86400
                else:
                    cutoff = 0
                if cutoff > 0:
                    filtered = [
                        r
                        for r in filtered
                        if max(
                            int(r.get("comment_epoch") or 0),
                            _parse_utc_to_epoch(r.get("created_at")),
                        )
                        >= cutoff
                    ]

            q = (search or "").strip().lower()
            if q:
                def _match(item: dict[str, Any]) -> bool:
                    haystack = " ".join(
                        str(item.get(k) or "")
                        for k in (
                            "task_id",
                            "nickname",
                            "comment_content",
                            "chinese_reply",
                            "english_reply",
                            "video_title",
                            "video_zh_title",
                            "video_en_title",
                            "video_copy_lead",
                            "comment_id",
                            "platform_reply_comment_id",
                            "platform_post_id",
                            "reason_code",
                            "provider",
                        )
                    ).lower()
                    return q in haystack

                filtered = [r for r in filtered if _match(r)]

            # 3. 排序（默认严格按最新任务 ID 倒序：最新的永远在最上面！）
            sort_key = (sort or "newest_desc").strip().lower()
            if sort_key == "comment_time_desc":
                filtered.sort(
                    key=lambda r: (int(r.get("comment_epoch") or 0), int(r.get("task_id") or 0)),
                    reverse=True,
                )
            elif sort_key == "comment_time_asc":
                filtered.sort(
                    key=lambda r: (int(r.get("comment_epoch") or 0), int(r.get("task_id") or 0)),
                    reverse=False,
                )
            elif sort_key == "updated_desc":
                filtered.sort(
                    key=lambda r: (
                        _parse_utc_to_epoch(r.get("updated_at")),
                        int(r.get("task_id") or 0),
                    ),
                    reverse=True,
                )
            elif sort_key == "verified_time_desc":
                filtered.sort(
                    key=lambda r: (
                        1 if r.get("verified_at") else 0,
                        _parse_utc_to_epoch(r.get("verified_at") or r.get("updated_at")),
                        int(r.get("task_id") or 0),
                    ),
                    reverse=True,
                )
            elif sort_key == "likes_desc":
                filtered.sort(
                    key=lambda r: (
                        int(r.get("comment_like_count") or 0),
                        int(r.get("task_id") or 0),
                    ),
                    reverse=True,
                )
            else:
                sort_key = "newest_desc"
                filtered.sort(key=lambda r: int(r.get("task_id") or 0), reverse=True)

            # 4. 服务端分页
            effective_size = size if size is not None else (limit if limit is not None else 10)
            page_size = max(1, min(100, int(effective_size)))
            total_count = len(filtered)
            total_pages = max(1, (total_count + page_size - 1) // page_size)
            curr_page = max(1, min(int(page), total_pages))
            start_idx = (curr_page - 1) * page_size
            paged_items = filtered[start_idx : start_idx + page_size]

            return {
                "items": paged_items,
                "total_count": total_count,
                "global_total": len(all_items),
                "page": curr_page,
                "size": page_size,
                "total_pages": total_pages,
                "sort": sort_key,
                "counts": counts,
                "filter_options": {
                    "videos": list(video_map.values()),
                    "styles": sorted(styles_set),
                },
            }
        except Exception as exc:
            raise HTTPException(503, "二级回复历史记录读取失败。") from exc

    @router.put("/api/secondary-reply-settings")
    def save(body: SecondaryReplySaveRequest, request: Request, actor=Depends(access)) -> dict:
        origin_check(request)
        try:
            save_policy(active, body.config, body.expected_digest, expected_revision=body.expected_revision, actor=actor)
            return policy_view(active)
        except PolicyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ConfigurationUnavailable as exc:
            raise HTTPException(503, '活动配置不可读取；草稿已保留，请重新载入核对。') from exc
        except ValueError as exc:
            raise HTTPException(422, f"策略校验未通过：{exc}") from exc
        except OSError as exc:
            raise HTTPException(503, "保存结果未确认，草稿已保留，请重新载入核对。") from exc

    return router
