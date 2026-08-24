#!/usr/bin/env python3
"""向 Telegram 发送英语世界短视频的人工审核回执。

该脚本只发送人工审核材料，绝不调用任何平台上传或投稿逻辑。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-22 | Codex | 新增每日英语世界短视频的 Telegram 审核材料通知。 |
| 1.1.0 | 2026-08-23 | Codex | 审核回执绑定独立发布包与一次性 Telegram 审批按钮，避免模糊文字误投。 |
| 1.2.0 | 2026-08-24 | Codex | 封面只接受 enriched timeline，并将实际投稿封面发送给人工审核。 |
| 1.3.0 | 2026-08-24 | Codex | 英语世界审核包优先使用 agy/Gemini 主视觉，失败时回退确定性封面。 |
| 1.4.0 | 2026-08-24 | Codex | 记录 Telegram API 回执并将失败通知去重，避免无回执重发刷屏。 |
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
from pathlib import Path
import subprocess
import sys

from config.settings import settings
from video_processing.core.cover_policy import validate_dedicated_cover_file
from video_processing.db.database import PipelineDB
from video_processing.telegram_delivery import send_document, send_text

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _post_message(text: str, *, reply_markup: dict | None = None) -> None:
    """发送文字回执；凭据只从 settings 读取。"""
    result = send_text(
        event_type="english_world.review_ready", priority="P0", text=text,
        reply_markup=reply_markup, timeout_seconds=20,
    )
    if result.state != "ACCEPTED":
        raise RuntimeError(f"Telegram 审核文字回执未获 API 接受：{result.error_kind or result.state}")


def _post_document(path: Path, caption: str) -> None:
    """发送审核文件；不把发送成功误作平台发布成功。"""
    result = send_document(
        event_type="english_world.review_attachment", priority="P0", path=path, caption=caption,
    )
    if result.state != "ACCEPTED":
        raise RuntimeError(f"Telegram 审核附件回执未获 API 接受：{result.error_kind or result.state}")


def _load_timeline(manifest_path: Path) -> dict:
    """读取与成片同目录的 enriched timeline；缺失时由调用方拒绝建立审核包。"""
    timeline_path = manifest_path.parent / "timeline_final_enriched.json"
    if not timeline_path.is_file():
        return {}
    try:
        payload = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取英语世界时间线：{timeline_path}") from exc
    return payload if isinstance(payload, dict) else {}


def _short_wechat_title(title: str) -> str:
    """视频号短标题保守裁为 16 个字符，避免将下一段文案混入标题字段。"""
    clean = "".join((title or "").split())
    return clean[:16] if len(clean) > 16 else clean


def _prepare_publish_package(*, display_title: str, mp4: Path, manifest: Path) -> dict:
    """生成可审计的投稿包并登记审核身份；这里不调用上传器或任何平台接口。"""
    try:
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取学习卡 manifest：{manifest}") from exc
    if manifest_payload.get("content_type") != "ENGLISH_WORLD_SHORT":
        raise ValueError("审核回执只接受 content_type=ENGLISH_WORLD_SHORT 的学习卡")

    timeline = _load_timeline(manifest)
    if not timeline:
        raise ValueError("英语世界审核包缺少 enriched timeline，拒绝生成无来源封面")
    provenance = timeline.get("source_provenance") if isinstance(timeline.get("source_provenance"), dict) else {}
    headline = str(timeline.get("headline_zh") or display_title).strip()
    if not headline:
        raise ValueError("英语世界学习卡缺少可显示标题")
    artifact_hash = hashlib.sha256(mp4.read_bytes()).hexdigest()
    package_dir = mp4.parent / "wechat_submission"
    package_dir.mkdir(parents=True, exist_ok=True)
    title_path = package_dir / "title.txt"
    copy_path = package_dir / "copy.txt"
    cover_path = package_dir / "cover.jpg"
    cover_provenance_path = package_dir / "cover_provenance.json"
    cover_payload_path = package_dir / "cover_payload.json"
    title_path.write_text(_short_wechat_title(headline), encoding="utf-8")
    source_publisher = str(provenance.get("publisher") or provenance.get("source_channel") or "").strip()
    source_url = str(provenance.get("source_url") or "").strip()
    copy_path.write_text(
        "英语世界｜每日英文听读\n"
        f"{headline}\n\n"
        "本期以英文新闻片段为听读素材，结合逐词跟读、重点词汇与完整中文释义进行学习设计。\n"
        f"素材来源：{source_publisher or '公开英文新闻素材'}"
        + (f"（{source_url}）\n" if source_url else "\n")
        + "#英语学习 #英语听力 #英文阅读\n",
        encoding="utf-8",
    )
    timeline_path = manifest.parent / "timeline_final_enriched.json"
    if not timeline_path.is_file():
        raise ValueError("英语世界审核包缺少 enriched timeline，拒绝生成无来源封面")
    if not validate_dedicated_cover_file(cover_path, cover_provenance_path) and settings.enable_english_world_antigravity_primary:
        agy_command = [
            str(_PROJECT_ROOT / ".venv" / "bin" / "python"),
            str(_PROJECT_ROOT / "scripts" / "generate_english_agi_cover.py"),
            "--timeline", str(timeline_path),
            "--output-dir", str(package_dir / "agi_cover"),
            "--variants", str(settings.english_world_antigravity_variants),
            "--model", settings.english_world_antigravity_model,
            "--timeout-seconds", str(settings.english_world_antigravity_timeout_seconds),
            "--cover-output", str(cover_path),
            "--provenance-output", str(cover_provenance_path),
            "--payload-output", str(cover_payload_path),
        ]
        if settings.english_world_antigravity_allow_ocr_suspect:
            agy_command.append("--allow-ocr-suspect")
        agy_timeout = settings.english_world_antigravity_variants * (settings.english_world_antigravity_timeout_seconds + 30) + 180
        try:
            agy_result = subprocess.run(
                agy_command,
                cwd=str(_PROJECT_ROOT), capture_output=True, text=True, timeout=agy_timeout,
            )
            attempt = {
                "returncode": agy_result.returncode,
                "stdout_tail": agy_result.stdout[-2000:],
                "stderr_tail": agy_result.stderr[-2000:],
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            agy_result = None
            attempt = {"returncode": None, "error": str(exc)[:2000]}
        (package_dir / "agy_cover_attempt.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "model": settings.english_world_antigravity_model,
                    "variants": settings.english_world_antigravity_variants,
                    "allow_ocr_suspect": settings.english_world_antigravity_allow_ocr_suspect,
                    **attempt,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        if agy_result is None or agy_result.returncode != 0 or not validate_dedicated_cover_file(cover_path, cover_provenance_path):
            logger.warning("英语世界 agy 主视觉未通过验收，回退确定性封面：%s", attempt.get("stderr_tail") or attempt.get("error", ""))

    if not validate_dedicated_cover_file(cover_path, cover_provenance_path):
        command = [
            str(_PROJECT_ROOT / ".venv" / "bin" / "python"),
            str(_PROJECT_ROOT / "scripts" / "generate_english_cover.py"),
        ]
        command.extend(["--timeline", str(timeline_path)])
        command.extend([
            "--output", str(cover_path),
            "--provenance-output", str(cover_provenance_path),
            "--payload-output", str(cover_payload_path),
        ])
        result = subprocess.run(
            command,
            cwd=str(_PROJECT_ROOT), capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0 or not validate_dedicated_cover_file(cover_path, cover_provenance_path):
            raise RuntimeError(f"英语世界投稿封面未通过验证：{result.stderr[-500:]}")

    return PipelineDB().create_english_world_review_item(
        artifact_sha256=artifact_hash,
        title=headline,
        mp4_path=str(mp4.resolve()),
        manifest_path=str(manifest.resolve()),
        title_path=str(title_path.resolve()),
        copy_path=str(copy_path.resolve()),
        cover_path=str(cover_path.resolve()),
        cover_provenance_path=str(cover_provenance_path.resolve()),
        source_url=source_url or None,
        source_title=str(provenance.get("source_title") or "").strip() or None,
        source_publisher=source_publisher or None,
        source_youtube_id=str(provenance.get("youtube_id") or "").strip() or None,
        notification_target=(settings.active_telegram_chat_id or "").strip() or None,
    )


def _review_keyboard(review_id: str) -> dict:
    """回调只携带受限审核 ID；禁止把来源 URL 或文件路径暴露给 Telegram callback。"""
    return {
        "inline_keyboard": [
            [{"text": "✅ 确认提交视频号", "callback_data": f"ew:r:{review_id}"}],
            [
                {"text": "↩️ 退回修改", "callback_data": f"ew:m:{review_id}"},
                {"text": "⏸ 暂不发布", "callback_data": f"ew:h:{review_id}"},
            ],
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发送英语世界短视频 Telegram 审核回执")
    parser.add_argument("--title", required=True, help="成片标题")
    parser.add_argument("--mp4", type=Path, help="通过质检的成片 MP4")
    parser.add_argument("--manifest", type=Path, help="与成片对应的 manifest JSON")
    parser.add_argument("--failure", help="无合格素材或制作失败时的原因")
    return parser


def main() -> int:
    args = _parser().parse_args()
    safe_title = html.escape(args.title.strip())
    if args.failure:
        result = send_text(
            event_type="english_world.not_delivered", priority="P1", cooldown_seconds=6 * 60 * 60,
            text=(
                "⚠️ <b>英语世界短视频｜今日未交付</b>\n"
                f"任务：{safe_title}\n"
                f"原因：{html.escape(args.failure.strip())}\n"
                "未生成成片，未触发任何视频号操作。"
            ),
        )
        if result.state not in {"ACCEPTED", "SUPPRESSED"}:
            raise RuntimeError(f"Telegram 未交付回执未获 API 接受：{result.error_kind or result.state}")
        return 0

    if not args.mp4 or not args.manifest:
        raise ValueError("成功审核回执必须同时提供 --mp4 与 --manifest")
    for artifact in (args.mp4, args.manifest):
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise FileNotFoundError(f"审核文件不存在或为空：{artifact}")

    review_item = _prepare_publish_package(display_title=args.title.strip(), mp4=args.mp4, manifest=args.manifest)
    review_id = str(review_item["id"])
    state = str(review_item["state"])
    message = (
        "✅ <b>英语世界短视频｜待人工审核</b>\n"
        f"标题：{html.escape(str(review_item['title']))}\n"
        f"审核编号：<code>{review_id[:8]}</code>\n"
        "已生成学习成片、质检清单与投稿素材包；当前<b>尚未提交视频号</b>。\n\n"
        "<b>审核通过：</b>点击下方「✅ 确认提交视频号」。\n"
        "该操作仅提交本条审核编号绑定的成片；提交后会回执“已受理 / 审核中 / 未确认”，不将已受理误报为公开发布，也不会自动重传。\n"
        "需修改请点“↩️ 退回修改”；不发布请点“⏸ 暂不发布”。"
    )
    markup = _review_keyboard(review_id) if state == "READY_FOR_REVIEW" else None
    if state != "READY_FOR_REVIEW":
        message += f"\n\n当前状态：<code>{html.escape(state)}</code>；为避免重复投稿，已不提供提交按钮。"
    _post_message(message, reply_markup=markup)
    _post_document(Path(str(review_item["cover_path"])), "英语世界投稿封面｜请与成片一并审核，尚未提交视频号")
    _post_document(args.mp4, "英语世界短视频成片｜待审核，未提交视频号")
    _post_document(args.manifest, "英语世界短视频 manifest｜审核证据")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - launchd 必须获得非零退出码和可诊断错误
        logger.exception("英语世界 Telegram 审核回执失败：%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
