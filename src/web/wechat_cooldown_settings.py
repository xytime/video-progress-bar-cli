"""视频号冷却与账户调度策略管理路由（实时冷却观测、确认平台已解冻、CAS 策略保存与热加载）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| publishing-recovery-v1 | 2026-10-23 | Codex | 接入发布恢复控制台，复用统一准入并保留任务和投稿保护。 |
| 1.0.0 | 2026-10-22 | Antigravity | 初始创建：提供视频号账户冷却状态查询、操作者确认解冻 (acknowledge_unfrozen) 及调度参数 CAS 保存与热加载 API |
"""

from __future__ import annotations

import math
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from video_processing.core.wechat_account_schedule import DAY
from video_processing.core.wechat_request_guard import WeChatRequestDeferred, WeChatRequestGuard
from video_processing.utils.wechat_product_config import PolicyConflict
from video_processing.utils.wechat_scheduler_policy import (
    DEFAULT_WECHAT_SCHEDULER_POLICY,
    digest,
    load_policy,
    save_policy,
)


class WeChatCooldownSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class UnfreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[a-f0-9]{64}$")


def _build_runtime_status(state_path: Path) -> dict[str, Any]:
    """读取当前账户冷却、恢复期与 24h 会话配额使用情况（纯脱敏元数据）。"""
    guard = WeChatRequestGuard(state_path)
    cooldown = guard.cooldown()
    admission = guard.evaluate(account_only=True)
    row = guard.snapshot()
    cooldown["version"] = guard.recovery_version(row)
    now = time.time()
    schedule = row.get("schedule", {})
    sessions = [s for s in schedule.get("sessions", []) if isinstance(s, dict) and s.get("at", 0) > now - DAY]
    queue = [q for q in schedule.get("queue", []) if isinstance(q, dict) and q.get("seen", 0) > now - 600]
    recovery_started = schedule.get("recovery_started")
    last_limited_at = float(row.get("last_limited_at") or 0)
    blocked_until = float(row.get("blocked_until") or 0)
    next_session_at = float(row.get("next_session_at") or 0)
    last_session_at = float(row.get("last_session_at") or 0)
    recovering = bool(last_limited_at) and (recovery_started is None or now < float(recovery_started) + DAY)
    platform_frozen = blocked_until > now

    interval = (
        settings.wechat_scheduler_recovery_interval_seconds
        if recovering
        else settings.wechat_scheduler_stable_interval_seconds
    )
    limit = (
        settings.wechat_scheduler_recovery_limit
        if recovering
        else settings.wechat_scheduler_daily_limit
    )
    next_schedule_at = (float(sessions[-1]["at"]) + interval) if sessions else 0.0
    effective_until = max(blocked_until, next_session_at, next_schedule_at if settings.wechat_account_scheduler_enabled else 0.0)
    effective_remaining = max(0, math.ceil(effective_until - now))

    return {
        "cooldown": cooldown,
        "admission": admission,
        "platform_frozen": platform_frozen,
        "recovering": recovering,
        "can_unfreeze": platform_frozen or recovering,
        "blocked_until": blocked_until,
        "next_session_at": next_session_at,
        "next_schedule_at": next_schedule_at,
        "effective_until": effective_until,
        "effective_remaining_seconds": effective_remaining,
        "last_session_at": last_session_at,
        "last_limited_at": last_limited_at,
        "failure_streak": int(row.get("failure_streak") or 0),
        "reason_code": str(row.get("reason") or "NORMAL"),
        "business_code": row.get("business_code"),
        "sessions_24h_count": admission["sessions_24h_count"],
        "effective_daily_limit": limit,
        "effective_interval_seconds": interval,
        "queue_count": len(queue),
        "recent_sessions": [
            {
                "at": float(s.get("at", 0)),
                "purpose": str(s.get("purpose") or ""),
                "task": Path(str(s.get("task") or "")).name or str(s.get("task") or ""),
            }
            for s in sessions[-8:]
        ],
    }


def create_wechat_cooldown_settings_router(
    *,
    active: Path,
    state_path: Optional[Path] = None,
) -> APIRouter:
    router = APIRouter()
    static_dir = Path(__file__).parent / "static"
    resolved_state = Path(state_path) if state_path is not None else (settings.default_output_dir / "wechat_state.json")

    def origin_check(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(403, "请从当前控制台页面操作")

    def view(config: dict) -> dict[str, Any]:
        return {
            "config": config,
            "digest": digest(config),
            "defaults": DEFAULT_WECHAT_SCHEDULER_POLICY,
            "runtime": _build_runtime_status(resolved_state),
        }

    @router.get("/wechat-cooldown-settings", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        html_path = Path(__file__).parent / "templates" / "wechat_cooldown_settings.html"
        content = html_path.read_text(encoding="utf-8")
        css_path = static_dir / "css" / "wechat_cooldown_settings.css"
        js_path = static_dir / "js" / "wechat_cooldown_settings.js"
        css_v = int(css_path.stat().st_mtime) if css_path.exists() else int(time.time())
        js_v = int(js_path.stat().st_mtime) if js_path.exists() else int(time.time())
        content = re.sub(
            r'/static/css/wechat_cooldown_settings\.css(?:\?v=[^"\'\s>]+)?',
            f"/static/css/wechat_cooldown_settings.css?v={css_v}",
            content,
        )
        content = re.sub(
            r'/static/js/wechat_cooldown_settings\.js(?:\?v=[^"\'\s>]+)?',
            f"/static/js/wechat_cooldown_settings.js?v={js_v}",
            content,
        )
        recovery_js = static_dir / "js" / "publishing_recovery.js"
        content = content.replace('/static/js/publishing_recovery.js"',
                                  f'/static/js/publishing_recovery.js?v={int(recovery_js.stat().st_mtime)}"')
        return HTMLResponse(
            content,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @router.get("/api/wechat-cooldown-settings")
    def read() -> dict[str, Any]:
        try:
            return view(load_policy(active))
        except WeChatRequestDeferred as exc:
            raise HTTPException(503, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(503, "冷却与调度策略读取失败，请检查配置文件后重新载入。") from exc

    @router.put("/api/wechat-cooldown-settings")
    def save(body: WeChatCooldownSaveRequest, request: Request) -> dict[str, Any]:
        origin_check(request)
        if settings.runtime_configuration_enabled:
            raise HTTPException(409,'额度已迁移到运行配置中心；此旧接口不能覆盖活动策略')
        try:
            saved = save_policy(active, body.config, body.expected_digest)
            return view(saved)
        except PolicyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, f"配置校验未通过：{exc}") from exc
        except OSError as exc:
            raise HTTPException(503, "保存结果未确认，草稿已保留，请重新载入核对。") from exc

    @router.post("/api/wechat-cooldown-settings/unfreeze")
    def unfreeze(body: UnfreezeRequest, request: Request) -> dict[str, Any]:
        origin_check(request)
        if settings.runtime_configuration_enabled:
            raise HTTPException(403,'真实退避和恢复保护不能由普通配置按钮清除；需要单独核实与批准')
        try:
            config = load_policy(active)
            guard = WeChatRequestGuard(resolved_state)
            guard.recover_local(operation_id=str(uuid.uuid4()), expected_version=body.version,
                                reset_cooldown=True)
            payload = view(config)
            payload["message"] = "已清除本地冷却与恢复期；平台真实状态仍需人工核实，其它限制继续生效。"
            return payload
        except WeChatRequestDeferred as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(503, f"解冻操作未确认：{exc}") from exc

    return router
