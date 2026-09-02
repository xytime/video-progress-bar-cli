"""按抖音账本 ID 执行一次只读作品管理回查，并可显式回账。

默认只调用 ``douyin_uploader.py --verify-only``，绝不上传、填写或发布；只有同时提供
``--apply-ledger`` 时，才把创作者中心明确返回的 PUBLISHED / UNDER_REVIEW 写回原记录。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-02 | Codex | 手工只读回查在启动浏览器前遵守持久阶段熔断，防止绕过录屏校准边界。 |
| 1.0.0 | 2026-08-30 | Codex | 新增单记录、单浏览器动作、默认只读的抖音人工回查入口 |
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.settings import settings  # noqa: E402
from video_processing.core.douyin_ui_guard_policy import (  # noqa: E402
    active_douyin_ui_failure_stages,
    douyin_management_verify_is_blocked,
)
from video_processing.db.database import PipelineDB  # noqa: E402
from video_processing.pipeline_manager import _build_subprocess_env  # noqa: E402

EXIT_OK = 0
EXIT_UNDER_REVIEW = 6
VERIFYABLE_STATES = {"UNCERTAIN", "UNDER_REVIEW"}


def _artifact_prefix(publication: dict[str, Any]) -> str:
    yid = str(publication["youtube_id"])
    slice_index = int(publication.get("slice_index") or 0)
    return f"{yid}_s{slice_index}" if slice_index > 0 else yid


def reconcile_publication(
    db: PipelineDB,
    publication_id: int,
    *,
    apply_ledger: bool = False,
    project_root: Path = PROJECT_ROOT,
    output_dir: Path | None = None,
    python_executable: str | None = None,
    no_headless: bool | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    env_builder: Callable[[], dict[str, str]] = _build_subprocess_env,
) -> dict[str, Any]:
    """回查一次指定记录；非明确平台结果保持原账本状态。"""
    publication = db.get_douyin_publication_by_id(int(publication_id))
    if not publication:
        raise ValueError("抖音投递记录不存在")
    original_state = str(publication.get("state") or "").upper()
    if original_state not in VERIFYABLE_STATES:
        raise ValueError(f"仅允许回查 {sorted(VERIFYABLE_STATES)}，当前状态为 {original_state}")
    try:
        active_stages = active_douyin_ui_failure_stages(
            db.get_platform_ui_failure_streaks("douyin"),
            recording_threshold=settings.douyin_ui_failure_recording_threshold,
        )
    except Exception as exc:  # noqa: BLE001 - 账本不可读时不能绕过浏览器熔断
        raise ValueError(f"无法读取抖音 UI 熔断账本，拒绝打开管理页：{exc}") from exc
    if douyin_management_verify_is_blocked(active_stages):
        raise ValueError(
            "抖音 UI 熔断已激活（"
            + ", ".join(sorted(active_stages))
            + "），请先录制并完成对应 selector 校准后再回查"
        )

    artifact_root = output_dir or project_root / "output"
    prefix = _artifact_prefix(publication)
    copy_file = artifact_root / f"{prefix}_copy.txt"
    title_file = artifact_root / f"{prefix}_title.txt"
    missing = [path.name for path in (copy_file, title_file) if not path.is_file()]
    if missing:
        raise ValueError("缺少精确回查身份文件：" + ",".join(missing))

    executable = python_executable or str(project_root / ".venv" / "bin" / "python")
    command = [
        executable,
        str(project_root / "scripts" / "douyin_uploader.py"),
        "--copy", str(copy_file),
        "--title-file", str(title_file),
        "--state", str(artifact_root / "douyin_state.json"),
        "--fail-fast-login",
        "--verify-only",
    ]
    should_show_browser = (not settings.douyin_browser_headless) if no_headless is None else bool(no_headless)
    if should_show_browser:
        command.append("--no-headless")

    result = runner(
        command,
        cwd=str(project_root),
        env=env_builder(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    exit_code = int(result.returncode)
    observed_state = {EXIT_OK: "PUBLISHED", EXIT_UNDER_REVIEW: "UNDER_REVIEW"}.get(
        exit_code, "UNCONFIRMED"
    )
    applied = False
    if apply_ledger and observed_state in {"PUBLISHED", "UNDER_REVIEW"}:
        message = (
            "抖音作品管理页按完整标题精确回查，已确认本次作品为已发布。"
            if observed_state == "PUBLISHED"
            else "抖音作品管理页按完整标题精确回查，本次作品仍在审核中。"
        )
        applied = db.update_douyin_publication_state(
            int(publication_id), observed_state, error_message=message
        )

    return {
        "publication_id": int(publication_id),
        "youtube_id": publication["youtube_id"],
        "slice_index": int(publication.get("slice_index") or 0),
        "original_state": original_state,
        "observed_state": observed_state,
        "exit_code": exit_code,
        "ledger_applied": bool(applied),
        "stdout": (result.stdout or "").strip()[-1000:],
        "stderr": (result.stderr or "").strip()[-1000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="单条抖音账本只读回查；默认不改账")
    parser.add_argument("--publication-id", type=int, required=True, help="douyin_publications.id")
    parser.add_argument("--apply-ledger", action="store_true", help="仅将明确 PUBLISHED/UNDER_REVIEW 回写原记录")
    parser.add_argument("--no-headless", action="store_true", help="显示只读回查浏览器")
    args = parser.parse_args()
    try:
        outcome = reconcile_publication(
            PipelineDB(),
            args.publication_id,
            apply_ledger=args.apply_ledger,
            no_headless=args.no_headless,
        )
    except (ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"success": True, **outcome}, ensure_ascii=False, indent=2))
    if outcome["observed_state"] in {"PUBLISHED", "UNDER_REVIEW"}:
        return 0
    return int(outcome["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
