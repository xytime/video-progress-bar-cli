"""Codex AI 封面底图任务协议与完成物校验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-31 | Codex | 新增 Markdown 任务单、完成物验收与超时降级判定 |
| 1.1.0 | 2026-07-31 | Codex | 提供无副作用的可领取任务判定，避免空队列唤起外部 Codex 执行器 |
| 1.2.0 | 2026-08-03 | Codex | 任务协议写明已有底图优先复用与高消耗生成需确认的执行边界 |
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from PIL import Image


_TASK_MARKER = "AI_COVER_TASK_JSON"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class AICoverTask:
    task_id: str
    path: Path
    payload: Mapping[str, Any]

    @property
    def finish_dir(self) -> Path:
        return Path(str(self.payload["finish_dir"]))

    @property
    def generation_deadline(self) -> datetime:
        return _parse_time(str(self.payload["generation_deadline_at"]))

    @property
    def fallback_after(self) -> datetime:
        return _parse_time(str(self.payload["fallback_after_at"]))


class AICoverQueue:
    """文件系统任务队列；任务 Markdown 不可变，完成物仅可在 deadline 前被消费。"""

    def __init__(self, queue_dir: Path, finish_dir: Path) -> None:
        self.queue_dir = queue_dir
        self.finish_dir = finish_dir

    def create_task(
        self,
        *,
        prefix: str,
        youtube_id: str,
        slice_index: int,
        cover_payload: Mapping[str, Any],
        visual_brief: Mapping[str, Any],
        final_cover_path: Path,
        provenance_path: Path,
        brief_path: Path,
        content_aware: bool,
        generation_deadline_minutes: int,
        fallback_after_minutes: int,
        now: Optional[datetime] = None,
    ) -> AICoverTask:
        if fallback_after_minutes <= generation_deadline_minutes:
            raise ValueError("fallback_after_minutes must be greater than generation_deadline_minutes")
        created_at = now or _utc_now()
        identity = json.dumps(
            {"prefix": prefix, "cover_payload": cover_payload, "visual_brief": visual_brief},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        task_id = f"{prefix}-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}"
        task_path = self.queue_dir / f"{task_id}.md"
        finish_dir = self.finish_dir / task_id
        if task_path.is_file():
            return AICoverTask(task_id=task_id, path=task_path, payload=self.read_task(task_path).payload)

        task_payload = {
            "schema_version": 1,
            "task_id": task_id,
            "created_at": _iso(created_at),
            "generation_deadline_at": _iso(created_at + timedelta(minutes=generation_deadline_minutes)),
            "fallback_after_at": _iso(created_at + timedelta(minutes=fallback_after_minutes)),
            "prefix": prefix,
            "youtube_id": youtube_id,
            "slice_index": int(slice_index),
            "finish_dir": str(finish_dir.resolve()),
            "expected_visual_filename": "visual.png",
            "final_cover_path": str(final_cover_path.resolve()),
            "provenance_path": str(provenance_path.resolve()),
            "brief_path": str(brief_path.resolve()),
            "content_aware": bool(content_aware),
            "cover_payload": dict(cover_payload),
            "visual_brief": dict(visual_brief),
            "rules": {
                "generate_text": False,
                "uses_video_frame": False,
                "dedicated_image_only": True,
                "no_broad_dark_overlay": True,
                "no_large_text_card": True,
                "text_legibility": "large text with local stroke/shadow/weight",
                "reuse_existing_visual_before_generation": True,
                "ask_before_high_cost_regeneration": True,
                "headline_safe_zone": "upper_left",
                "minimum_width": 720,
                "minimum_height": 960,
            },
        }
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        finish_dir.mkdir(parents=True, exist_ok=True)
        markdown = self._render_markdown(task_payload)
        temporary = task_path.with_suffix(".md.tmp")
        temporary.write_text(markdown, encoding="utf-8")
        temporary.replace(task_path)
        return AICoverTask(task_id=task_id, path=task_path, payload=task_payload)

    def read_task(self, path: Path) -> AICoverTask:
        content = path.read_text(encoding="utf-8")
        match = re.search(rf"<!-- {re.escape(_TASK_MARKER)}\n(.*?)\n{re.escape(_TASK_MARKER)} -->", content, re.DOTALL)
        if not match:
            raise ValueError(f"invalid AI cover task: {path}")
        payload = json.loads(match.group(1))
        return AICoverTask(task_id=str(payload["task_id"]), path=path, payload=payload)

    def list_tasks(self) -> Iterable[AICoverTask]:
        if not self.queue_dir.is_dir():
            return ()
        tasks = []
        for path in sorted(self.queue_dir.glob("*.md")):
            try:
                tasks.append(self.read_task(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return tuple(tasks)

    def accepted_visual(self, task: AICoverTask) -> Optional[Path]:
        result_path = task.finish_dir / "result.json"
        if not result_path.is_file():
            return None
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            visual = task.finish_dir / str(result["visual_filename"])
            completed_at = _parse_time(str(result["completed_at"]))
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return None
        if result.get("task_id") != task.task_id or result.get("generated_by") != "codex_imagegen":
            return None
        if result.get("uses_video_frame") is not False or completed_at > task.generation_deadline:
            return None
        if not visual.is_file() or visual.parent.resolve() != task.finish_dir.resolve():
            return None
        if result.get("sha256") != _sha256(visual) or not self._valid_visual(visual):
            return None
        return visual

    def has_eligible_task(self, now: Optional[datetime] = None) -> bool:
        """是否存在尚未完成、未超时且未被有效 claim 占用的任务。"""
        current_time = now or _utc_now()
        for task in self.list_tasks():
            if (task.finish_dir / "result.json").is_file() or (task.finish_dir / "resolution.json").is_file():
                continue
            if current_time >= task.generation_deadline:
                continue
            if self._has_fresh_claim(task, current_time):
                continue
            return True
        return False

    def should_fallback(self, task: AICoverTask, now: Optional[datetime] = None) -> bool:
        return (now or _utc_now()) >= task.fallback_after

    @staticmethod
    def _has_fresh_claim(task: AICoverTask, now: datetime) -> bool:
        claim_path = task.finish_dir / "claim.json"
        if not claim_path.is_file():
            return False
        try:
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            expires_at = _parse_time(str(claim["claim_expires_at"]))
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return False
        return claim.get("task_id") == task.task_id and expires_at > now

    @staticmethod
    def _valid_visual(path: Path) -> bool:
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
            return width >= 720 and height >= 960
        except (OSError, ValueError):
            return False

    @staticmethod
    def _render_markdown(payload: Mapping[str, Any]) -> str:
        brief = payload["visual_brief"]
        return (
            f"<!-- {_TASK_MARKER}\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n{_TASK_MARKER} -->\n\n"
            f"# AI 封面底图任务：{payload['task_id']}\n\n"
            f"- 创建时间（UTC）：{payload['created_at']}\n"
            f"- Codex 生成截止（UTC）：{payload['generation_deadline_at']}\n"
            f"- 本地降级起点（UTC）：{payload['fallback_after_at']}\n"
            f"- 最终封面由项目统一排版，Codex 只生成无文字底图。\n\n"
            "## 视觉需求\n\n"
            f"- 视觉方向：{brief.get('visual_direction', '')}\n"
            f"- 关键词：{'、'.join(brief.get('visual_keywords', []))}\n"
            "- 构图：主体避开左上标题安全区；保留完整人物、物体和地平线。\n"
            "- 排版边界：最终标题会由项目用大字号、描边/阴影叠加；底图不得预留大遮罩或文字卡片。\n"
            "- 资源边界：如果已有可用 `visual.png` 或只需要文字重排，不得重新生成底图；高消耗重生成必须先获人工确认。\n"
            "- 禁止：任何文字、Logo、水印、视频帧、视频截图、YouTube 缩略图。\n"
            "- 输出：`finish_dir/visual.png`，以及同目录的 `result.json`。\n"
        )
