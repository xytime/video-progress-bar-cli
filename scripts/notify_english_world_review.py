#!/usr/bin/env python3
"""登记英语世界短视频质检包，并发送 Telegram 审计回执。

默认发送人工审核材料；启用显式自动策略后，只提交本次新建且已通过完整本地
质检的学习卡。既有审核项、失败项和任何未确认投稿都不会由本脚本自动重传。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-22 | Codex | 新增每日英语世界短视频的 Telegram 审核材料通知。 |
| 1.1.0 | 2026-08-23 | Codex | 审核回执绑定独立发布包与一次性 Telegram 审批按钮，避免模糊文字误投。 |
| 1.2.0 | 2026-08-24 | Codex | 封面只接受 enriched timeline，并将实际投稿封面发送给人工审核。 |
| 1.3.0 | 2026-08-24 | Codex | 英语世界审核包优先使用 agy/Gemini 主视觉，失败时回退确定性封面。 |
| 1.4.0 | 2026-08-24 | Codex | 记录 Telegram API 回执并将失败通知去重，避免无回执重发刷屏。 |
| 1.5.0 | 2026-08-24 | Codex | 创建审核包前以 manifest 与 ffprobe 双重拒绝非 30–300 秒范围的成片，杜绝短片绕过渲染入口直接投递。 |
| 1.6.0 | 2026-08-26 | Codex | 支持经显式策略授权的质检后自动投稿；只消费本次新建审核项，旧项及终态绝不自动重传。 |
| 1.7.0 | 2026-08-26 | Codex | 可选写入机器可读的日更投递回执，协调器不得再把代理退出成功误报为 Telegram 交付成功。 |
| 1.8.0 | 2026-08-27 | Codex | 兼容学习卡生产器的 `timeline.enriched.json` 命名，防止质检通过后在交付入口被拒绝。 |
| 1.9.0 | 2026-08-29 | Codex | 审核项绑定完整投稿包指纹并按 source_youtube_id 阻断重复审核/投稿。 |
| 1.10.0 | 2026-08-29 | Codex | Telegram 选题制作请求强制进入人工审核，不受全局自动投稿开关扩权。 |
"""

from __future__ import annotations

import argparse
import html
import json
import logging
from pathlib import Path
import subprocess
import sys

from config.settings import settings
from video_processing.core.cover_policy import validate_dedicated_cover_file
from video_processing.db.database import PipelineDB
from video_processing.english_world.package_integrity import calculate_package_hashes
from video_processing.telegram_delivery import send_document, send_text
from video_processing.utils.video_metadata import get_video_duration_ffprobe

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MIN_REVIEW_DURATION_SECONDS = 30.0
_MAX_REVIEW_DURATION_SECONDS = 300.0
_AUTO_SUBMIT_SCRIPT = _PROJECT_ROOT / "scripts" / "submit_english_world_review.py"


def _post_message(text: str, *, reply_markup: dict | None = None):
    """发送文字回执；凭据只从 settings 读取。"""
    result = send_text(
        event_type="english_world.review_ready", priority="P0", text=text,
        reply_markup=reply_markup, timeout_seconds=20,
    )
    if result.state != "ACCEPTED":
        raise RuntimeError(f"Telegram 审核文字回执未获 API 接受：{result.error_kind or result.state}")
    return result


def _post_document(path: Path, caption: str):
    """发送审核文件；不把发送成功误作平台发布成功。"""
    result = send_document(
        event_type="english_world.review_attachment", priority="P0", path=path, caption=caption,
    )
    if result.state != "ACCEPTED":
        raise RuntimeError(f"Telegram 审核附件回执未获 API 接受：{result.error_kind or result.state}")
    return result


def _resolve_enriched_timeline_path(manifest_path: Path) -> Path | None:
    """兼容渲染器的标准 enriched 输出名，优先最终复核时间线。"""
    for name in ("timeline_final_enriched.json", "timeline_enriched.json", "timeline.enriched.json"):
        candidate = manifest_path.parent / name
        if candidate.is_file():
            return candidate
    return None


def _write_delivery_receipt(path: Path | None, payload: dict) -> None:
    """仅在 Telegram API 已有可判定结果后原子落盘给日更协调器读取。"""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def _load_timeline(manifest_path: Path) -> dict:
    """读取与成片同目录的 enriched timeline；缺失时由调用方拒绝建立审核包。"""
    timeline_path = _resolve_enriched_timeline_path(manifest_path)
    if timeline_path is None:
        return {}
    try:
        payload = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取英语世界时间线：{timeline_path}") from exc
    return payload if isinstance(payload, dict) else {}


def _validate_review_duration(*, mp4: Path, manifest_payload: dict) -> float:
    """以最终 MP4 和 manifest 交叉核验英语世界审核成片的实际时长。"""
    try:
        manifest_duration = float(manifest_payload["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("英语世界 manifest 缺少可解析的 duration") from exc
    try:
        actual_duration = get_video_duration_ffprobe(mp4)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"无法用 ffprobe 核验英语世界成片时长：{mp4}") from exc
    if not (_MIN_REVIEW_DURATION_SECONDS < actual_duration <= _MAX_REVIEW_DURATION_SECONDS):
        raise ValueError(
            "英语世界审核成片实际时长必须严格大于 "
            f"{_MIN_REVIEW_DURATION_SECONDS:g} 秒且不超过 {_MAX_REVIEW_DURATION_SECONDS:g} 秒；"
            f"ffprobe={actual_duration:.3f} 秒"
        )
    if abs(manifest_duration - actual_duration) > 0.25:
        raise ValueError(
            "英语世界 manifest 时长与 MP4 不一致："
            f"manifest={manifest_duration:.3f} 秒，ffprobe={actual_duration:.3f} 秒"
        )
    return actual_duration


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
    _validate_review_duration(mp4=mp4, manifest_payload=manifest_payload)

    timeline = _load_timeline(manifest)
    if not timeline:
        raise ValueError("英语世界审核包缺少 enriched timeline，拒绝生成无来源封面")
    provenance = timeline.get("source_provenance") if isinstance(timeline.get("source_provenance"), dict) else {}
    headline = str(timeline.get("headline_zh") or display_title).strip()
    if not headline:
        raise ValueError("英语世界学习卡缺少可显示标题")
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
    timeline_path = _resolve_enriched_timeline_path(manifest)
    if timeline_path is None:
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

    package_hashes = calculate_package_hashes({
        "mp4_path": mp4,
        "manifest_path": manifest,
        "title_path": title_path,
        "copy_path": copy_path,
        "cover_path": cover_path,
        "cover_provenance_path": cover_provenance_path,
    })
    return PipelineDB().create_english_world_review_item(
        **package_hashes,
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


def _auto_submit_new_review_item(review_item: dict) -> str:
    """在显式策略开启时提交一条本次新建的质检包；绝不触碰历史审核项。"""
    if not settings.enable_english_world_auto_publish:
        return "disabled"
    if not review_item.get("_created_now"):
        return "existing_item_not_retried"
    if settings.wechat_publishing_paused:
        return "wechat_publishing_paused"
    review_id = str(review_item["id"])
    db = PipelineDB()
    db.approve_english_world_submission(review_id, authorization="AUTO_POLICY")
    # 投稿器自身有 25 分钟上传超时并持久化 UNDER_REVIEW / UNCERTAIN 等终态；
    # 此处不另设父超时，以免杀死已领取任务后遗留 SUBMITTING 状态。
    result = subprocess.run(
        [str(_PROJECT_ROOT / ".venv" / "bin" / "python"), str(_AUTO_SUBMIT_SCRIPT), "--review-id", review_id],
        cwd=str(_PROJECT_ROOT), text=True, capture_output=True, check=False,
    )
    item = db.get_english_world_review_item(review_id) or review_item
    return f"submission_worker_exit={result.returncode}; state={item.get('state', 'UNKNOWN')}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发送英语世界短视频 Telegram 审核回执")
    parser.add_argument("--title", required=True, help="成片标题")
    parser.add_argument("--mp4", type=Path, help="通过质检的成片 MP4")
    parser.add_argument("--manifest", type=Path, help="与成片对应的 manifest JSON")
    parser.add_argument("--failure", help="无合格素材或制作失败时的原因")
    parser.add_argument("--delivery-receipt", type=Path, help="可选：供日更协调器读取的机器可读 Telegram 回执")
    parser.add_argument(
        "--manual-review-only", action="store_true",
        help="强制只发送人工审核包；即使全局自动投稿开启也不得提交平台",
    )
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
        _write_delivery_receipt(
            args.delivery_receipt,
            {
                "kind": "failure_notice",
                "status": result.state,
                "telegram_message_id": result.message_id,
            },
        )
        return 0

    if not args.mp4 or not args.manifest:
        raise ValueError("成功审核回执必须同时提供 --mp4 与 --manifest")
    for artifact in (args.mp4, args.manifest):
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise FileNotFoundError(f"审核文件不存在或为空：{artifact}")

    review_item = _prepare_publish_package(display_title=args.title.strip(), mp4=args.mp4, manifest=args.manifest)
    review_id = str(review_item["id"])
    state = str(review_item["state"])
    will_auto_submit = (
        not args.manual_review_only
        and settings.enable_english_world_auto_publish
        and bool(review_item.get("_created_now"))
        and not settings.wechat_publishing_paused
    )
    if will_auto_submit:
        text_result = _post_message(
            "✅ <b>英语世界短视频｜自动投稿前审计</b>\n"
            f"标题：{html.escape(str(review_item['title']))}\n"
            f"审核编号：<code>{review_id[:8]}</code>\n"
            "本次新建成片已通过本地质检，正在按自动策略一次性提交视频号；"
            "Telegram 附件为提交前审计材料，不等同公开发布。"
        )
        cover_result = _post_document(Path(str(review_item["cover_path"])), "英语世界投稿封面｜自动提交前审计材料")
        mp4_result = _post_document(args.mp4, "英语世界短视频成片｜自动提交前审计材料")
        manifest_result = _post_document(args.manifest, "英语世界短视频 manifest｜自动提交前审计材料")
        auto_result = _auto_submit_new_review_item(review_item)
        completion_result = _post_message(
            "⏳ <b>英语世界短视频｜自动投稿执行完毕</b>\n"
            f"标题：{html.escape(str(review_item['title']))}\n"
            f"审核编号：<code>{review_id[:8]}</code>\n"
            f"执行结果：<code>{html.escape(auto_result)}</code>。\n"
            "“已受理 / 审核中”不等同公开发布；任何未确认结果均已停止自动重传。"
        )
        _write_delivery_receipt(
            args.delivery_receipt,
            {
                "kind": "review_and_auto_submission",
                "status": "ACCEPTED",
                "review_id": review_id,
                "review_state": state,
                "message_ids": [
                    text_result.message_id, cover_result.message_id, mp4_result.message_id,
                    manifest_result.message_id, completion_result.message_id,
                ],
                "submission_result": auto_result,
            },
        )
        return 0

    message = "✅ <b>英语世界短视频｜待处理</b>\n"
    message += f"标题：{html.escape(str(review_item['title']))}\n审核编号：<code>{review_id[:8]}</code>\n"
    manual_review = args.manual_review_only or not settings.enable_english_world_auto_publish
    markup = _review_keyboard(review_id) if state == "READY_FOR_REVIEW" and manual_review else None
    if manual_review:
        message += (
            "已生成学习成片、质检清单与投稿素材包；当前<b>尚未提交视频号</b>。\n\n"
            "<b>审核通过：</b>点击下方「✅ 确认提交视频号」。\n"
            "该操作仅提交本条审核编号绑定的成片；提交后会回执“已受理 / 审核中 / 未确认”，"
            "不将已受理误报为公开发布，也不会自动重传。\n"
            "需修改请点“↩️ 退回修改”；不发布请点“⏸ 暂不发布”。"
        )
    else:
        message += (
            f"\n\n当前状态：<code>{html.escape(state)}</code>；自动策略结果："
            "<code>existing_item_not_retried_or_wechat_publishing_paused</code>。"
            "为避免重复投稿，未触发新提交。"
        )
    if state != "READY_FOR_REVIEW" and manual_review:
        message += f"\n\n当前状态：<code>{html.escape(state)}</code>；为避免重复投稿，已不提供提交按钮。"
    text_result = _post_message(message, reply_markup=markup)
    audit_suffix = "人工审核材料" if manual_review else "待处理审计材料"
    cover_result = _post_document(Path(str(review_item["cover_path"])), f"英语世界投稿封面｜{audit_suffix}")
    mp4_result = _post_document(args.mp4, f"英语世界短视频成片｜{audit_suffix}")
    manifest_result = _post_document(args.manifest, f"英语世界短视频 manifest｜{audit_suffix}")
    _write_delivery_receipt(
        args.delivery_receipt,
        {
            "kind": "review",
            "status": "ACCEPTED",
            "review_id": review_id,
            "review_state": state,
            "message_ids": [
                text_result.message_id, cover_result.message_id, mp4_result.message_id,
                manifest_result.message_id,
            ],
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - launchd 必须获得非零退出码和可诊断错误
        logger.exception("英语世界 Telegram 审核回执失败：%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
