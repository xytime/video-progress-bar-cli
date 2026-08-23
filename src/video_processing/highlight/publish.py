"""Highlight Clip 的视频号投递与按 post_id 回查服务。

只接受已经生成完整资产、且人工审核过当前资产清单的独立 Clip。提交回执并不等同于
公开可见：服务会先记录不可变提交尝试，再仅按同会话获得的 ``platform_post_id`` 回查。
没有原生 ID 时保持 ``SUBMITTED_UNBOUND``，绝不按标题猜测、绝不自动重传。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-20 | Codex | 新增 Highlight Clip 的人工审核门、提交回执入账和 post_id 精确回查 |
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from video_processing.db.database import PipelineDB

logger = logging.getLogger(__name__)

_EXIT_SUBMITTED_FOR_REVIEW = 6
_EXIT_MANAGEMENT_UNCERTAIN = 7
_EXIT_MANAGEMENT_REJECTED = 8
_EXIT_MANAGEMENT_NOT_FOUND = 9


class HighlightPublicationService:
    """独立 Clip 的 fail-closed 视频号投递服务。"""

    def __init__(self, db: PipelineDB, project_root: Path | None = None):
        self.db = db
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
        self.python = self.project_root / ".venv" / "bin" / "python"
        self.state_path = self.project_root / "output" / "wechat_state.json"

    def approve_current_assets(self, clip_id: str, *, approved_by: str) -> dict[str, Any]:
        """核验所有资产哈希后记录人工审核；不会打开平台页面。"""
        clip = self._ready_clip(clip_id)
        manifest = _load_manifest(Path(str(clip["artifact_manifest_path"])))
        self._assert_asset_manifest_matches(clip, manifest)
        return self.db.approve_highlight_clip_publication(
            clip_id,
            asset_manifest_sha256=_sha256(Path(str(clip["artifact_manifest_path"]))),
            approved_by=approved_by,
        )

    def submit(self, clip_id: str, *, approved_by: str) -> dict[str, Any]:
        """提交一个已审核 Clip，并立即按获得的原生 post_id 做一次只读回查。"""
        review = self.approve_current_assets(clip_id, approved_by=approved_by)
        clip = self._ready_clip(clip_id)
        subject_id = str(clip.get("publication_subject_id") or "")
        if not subject_id:
            raise RuntimeError("Highlight Clip 缺少独立发布主体")
        existing = self.db.get_wechat_publication_for_subject(subject_id)
        if existing:
            return {
                "action": "not_submitted",
                "reason": "该 Highlight Clip 已存在视频号账本；禁止重复上传",
                "review": review,
                "publication": existing,
            }

        evidence_dir = Path(str(clip["evidence_dir"]))
        evidence_dir.mkdir(parents=True, exist_ok=True)
        result = self._run(
            [
                str(self.python), "scripts/wechat_uploader.py",
                "--video", str(clip["rendered_video_path"]),
                "--copy", str(clip["copy_path"]),
                "--title-file", str(clip["title_path"]),
                "--cover", str(clip["cover_path"]),
                "--cover-provenance", str(clip["cover_provenance_path"]),
                "--category-file", str(clip["category_path"]),
                "--state", str(self.state_path),
                "--evidence-dir", str(evidence_dir),
                "--fail-fast-login", "--no-original-declaration",
            ],
            timeout=900,
            label="Highlight 视频号提交",
        )
        if result.returncode != _EXIT_SUBMITTED_FOR_REVIEW:
            return self._record_nonfinal_submission_result(clip, result)

        receipt_path = evidence_dir / "submission_receipt.json"
        receipt = _load_submission_receipt(receipt_path)
        evidence_path = _latest_evidence(evidence_dir)
        title = Path(str(clip["title_path"])).read_text(encoding="utf-8").strip()
        attempt = self.db.record_wechat_submission_attempt_for_subject(
            subject_id,
            final_title=title,
            evidence_path=evidence_path or (str(receipt_path) if receipt_path.is_file() else None),
            video_sha256=_sha256(Path(str(clip["rendered_video_path"]))),
            cover_sha256=_sha256(Path(str(clip["cover_path"]))),
        )
        platform_post_id = str(receipt.get("platform_post_id") or "").strip()
        if not platform_post_id:
            publication = self.db.record_wechat_publication_confirmation_for_subject(
                subject_id,
                evidence_path=evidence_path,
                state="SUBMITTED_UNBOUND",
                error_message="平台已受理提交，但未取得唯一同会话 post_id；禁止自动重传。",
            )
            return {
                "action": "submitted_unbound",
                "review": review,
                "attempt": attempt,
                "publication": publication,
                "uploader_exit": result.returncode,
            }
        platform_url = str(receipt.get("platform_url") or "").strip() or None
        attempt = self.db.bind_wechat_submission_attempt_platform_id(
            str(attempt["attempt_id"]), platform_post_id=platform_post_id, platform_url=platform_url,
        )
        publication = self.db.record_wechat_publication_confirmation_for_subject(
            subject_id,
            evidence_path=str(receipt_path) if receipt_path.is_file() else None,
            state="SUBMITTED_BOUND",
            platform_post_id=platform_post_id,
            platform_url=platform_url,
            error_message="平台已受理；已绑定同会话取得的原生 post_id，等待按 ID 回查。",
        )
        verification = self.verify(clip_id)
        return {
            "action": "submitted_bound",
            "review": review,
            "attempt": attempt,
            "publication": publication,
            "verification": verification,
            "uploader_exit": result.returncode,
        }

    def verify(self, clip_id: str) -> dict[str, Any]:
        """只按已绑定平台原生 ID 回查；绝不上传、绝不依据标题匹配。"""
        clip = self.db.get_highlight_clip_assets(clip_id)
        if not clip:
            raise ValueError("Highlight Clip 不存在")
        subject_id = str(clip.get("publication_subject_id") or "")
        publication = self.db.get_wechat_publication_for_subject(subject_id)
        platform_post_id = str((publication or {}).get("platform_post_id") or "").strip()
        if not publication or not platform_post_id:
            return {"action": "not_verified", "reason": "没有已绑定原生 post_id；禁止标题匹配或重传", "publication": publication}
        evidence_dir = Path(str(clip["evidence_dir"]))
        result = self._run(
            [
                str(self.python), "scripts/wechat_uploader.py", "--verify-only",
                "--platform-post-id", platform_post_id, "--state", str(self.state_path),
                "--evidence-dir", str(evidence_dir), "--fail-fast-login",
            ],
            timeout=180,
            label="Highlight 视频号 post_id 回查",
        )
        evidence_path = _latest_evidence(evidence_dir)
        state, error = _verification_state(result.returncode)
        recorded = self.db.record_wechat_publication_confirmation_for_subject(
            subject_id,
            evidence_path=evidence_path if state in {"PUBLISHED", "UNDER_REVIEW", "REJECTED", "NOT_FOUND"} else None,
            state=state,
            error_message=error,
            platform_post_id=platform_post_id,
            platform_url=(publication or {}).get("platform_url"),
            reconciled=True,
        )
        return {"action": "verified", "uploader_exit": result.returncode, "publication": recorded}

    def _ready_clip(self, clip_id: str) -> dict[str, Any]:
        clip = self.db.get_highlight_clip_assets(clip_id)
        if not clip or clip.get("state") != "ASSETS_READY":
            raise ValueError("Highlight Clip 尚未完成独立资产生成")
        required = (
            "publication_subject_id", "rendered_video_path", "title_path", "copy_path", "cover_path",
            "cover_provenance_path", "artifact_manifest_path", "evidence_dir",
        )
        if any(not str(clip.get(key) or "").strip() for key in required):
            raise ValueError("Highlight Clip 资产账本不完整")
        return clip

    def _assert_asset_manifest_matches(self, clip: dict[str, Any], manifest: dict[str, Any]) -> None:
        if manifest.get("publication", {}).get("review_required") is not True:
            raise ValueError("Highlight 资产清单未声明人工审核要求")
        if manifest.get("publication", {}).get("declare_original") is not False:
            raise ValueError("转载/二创 Highlight 必须明确不声明原创")
        expected = {
            "video": "rendered_video_path",
            "title": "title_path",
            "copy": "copy_path",
            "cover": "cover_path",
            "cover_provenance": "cover_provenance_path",
        }
        for asset_name, clip_key in expected.items():
            path = Path(str(clip[clip_key]))
            item = (manifest.get("assets") or {}).get(asset_name) or {}
            if not path.is_file() or item.get("path") != str(path) or item.get("sha256") != _sha256(path):
                raise ValueError(f"Highlight {asset_name} 与已审计资产清单不一致")

    def _record_nonfinal_submission_result(self, clip: dict[str, Any], result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        subject_id = str(clip["publication_subject_id"])
        evidence_path = _latest_evidence(Path(str(clip["evidence_dir"])))
        # 登录失效或页面上传失败并不等同于提交；仅把可能已到达平台但无回执的状态封为
        # UNCERTAIN，阻止下一轮盲目重传。
        if result.returncode in {3, _EXIT_MANAGEMENT_UNCERTAIN, _EXIT_MANAGEMENT_NOT_FOUND}:
            publication = self.db.record_wechat_publication_confirmation_for_subject(
                subject_id,
                evidence_path=None,
                state="UNCERTAIN",
                error_message=f"提交/回查未能确认（uploader exit={result.returncode}）；禁止自动重传。",
            )
            return {"action": "uncertain", "uploader_exit": result.returncode, "publication": publication}
        return {
            "action": "not_submitted",
            "uploader_exit": result.returncode,
            "evidence_path": evidence_path,
            "reason": "上传器未报告平台受理；未创建提交账本。",
        }

    def _run(self, command: list[str], *, timeout: int, label: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command, cwd=self.project_root, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{label}超时；未自动重传") from exc


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Highlight 资产清单缺失")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Highlight 资产清单不可读取") from exc


def _load_submission_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _latest_evidence(directory: Path) -> str | None:
    if not directory.is_dir():
        return None
    candidates = [path for path in directory.glob("*.png") if path.is_file()]
    if not candidates:
        return None
    return str(max(candidates, key=lambda path: path.stat().st_mtime))


def _verification_state(returncode: int) -> tuple[str, str]:
    if returncode == 0:
        return "PUBLISHED", "作品管理页按已绑定 post_id 确认已发布。"
    if returncode == _EXIT_SUBMITTED_FOR_REVIEW:
        return "UNDER_REVIEW", "作品管理页按已绑定 post_id 显示审核中。"
    if returncode == _EXIT_MANAGEMENT_REJECTED:
        return "REJECTED", "作品管理页按已绑定 post_id 显示审核未通过。"
    if returncode == _EXIT_MANAGEMENT_NOT_FOUND:
        return "NOT_FOUND", "作品管理页按已绑定 post_id 未找到记录。"
    return "UNCERTAIN", "作品管理页按已绑定 post_id 未能确定状态；禁止重传。"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
