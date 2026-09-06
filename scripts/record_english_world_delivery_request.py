#!/usr/bin/env python3
"""记录英语世界成片的宿主交付请求。

生产代理在受限工作区内只负责制作与质检；封面、Telegram 审计和视频号上传由
日更协调器的宿主进程领取这个原子请求后执行。这样 Chromium 不会再由受限
工作区启动，而真实的宿主标准封面链路仍是首选。

# Modification History
# | Version | Date | Author | Description |
# | --- | --- | --- | --- |
# | 1.0.0 | 2026-08-28 | Codex | 新增生产代理到宿主交付器的原子请求协议，隔离 Chromium 权限边界。 |
# | 1.1.0 | 2026-08-30 | Codex | 在成功或失败请求中持久化本轮已淘汰候选 ID，供后续运行机器化避让。 |
# | 1.2.0 | 2026-09-01 | Codex | 成功请求绑定 state=PASS 的最终音频 QA 报告，避免绕过末尾泄漏门禁。 |
# | 1.3.0 | 2026-09-01 | Codex | 要求 PASS 报告精确绑定本次 MP4 与 manifest，阻断复用旧成片 QA。 |
# | 1.3.1 | 2026-09-06 | Codex | 请求绑定三份产物内容指纹并区分来源质量与程序故障。 |
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


from video_processing.study_cards.qa_integrity import validate_audio_qa


YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="协调器指定的交付请求 JSON")
    parser.add_argument("--title", required=True, help="学习成片标题")
    parser.add_argument("--mp4", type=Path, help="已质检 MP4 的绝对路径")
    parser.add_argument("--manifest", type=Path, help="与 MP4 对应的 manifest 绝对路径")
    parser.add_argument("--audio-qa-report", type=Path, help="最终音频 QA 报告；必须为 state=PASS")
    parser.add_argument("--failure", help="无可交付成片时的准确失败原因")
    parser.add_argument(
        "--rejected-youtube-id",
        action="append",
        default=[],
        help="本轮来源预检已淘汰的 YouTube ID；可重复，最多五个",
    )
    parser.add_argument("--failure-kind", choices=("source_quality", "internal_error", "transport"), default="internal_error")
    return parser


def main() -> int:
    args = _parser().parse_args()
    title = args.title.strip()
    failure = (args.failure or "").strip()
    if not title:
        raise ValueError("--title must not be blank")
    if bool(failure) == bool(args.mp4 or args.manifest):
        raise ValueError("provide either --failure or both --mp4 and --manifest")
    if not failure and (args.mp4 is None or args.manifest is None):
        raise ValueError("successful delivery request requires --mp4 and --manifest")
    if not failure and args.audio_qa_report is None:
        raise ValueError("successful delivery request requires --audio-qa-report")
    if not failure:
        report_path = args.audio_qa_report.expanduser().resolve()
        if not report_path.is_file() or report_path.stat().st_size <= 0:
            raise ValueError("audio QA report does not exist or is empty")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("audio QA report is not valid JSON") from exc
        if not isinstance(report, dict) or report.get("state") != "PASS" or report.get("passed") is not True:
            raise ValueError("audio QA report is not PASS")
        for field, artifact in (("mp4", args.mp4), ("manifest", args.manifest)):
            if not report.get(field) or Path(str(report[field])).expanduser().resolve() != artifact.expanduser().resolve():
                raise ValueError(f"audio QA report does not match the current {field}")

        validate_audio_qa(report_path, mp4=args.mp4, manifest=args.manifest)

    rejected_youtube_ids = list(dict.fromkeys(str(value).strip() for value in args.rejected_youtube_id))
    if len(rejected_youtube_ids) > 5:
        raise ValueError("at most five --rejected-youtube-id values are allowed")
    if any(not YOUTUBE_ID_PATTERN.fullmatch(value) for value in rejected_youtube_ids):
        raise ValueError("every --rejected-youtube-id must be an 11-character YouTube ID")

    payload: dict[str, object] = {
        "title": title,
        "rejected_youtube_ids": rejected_youtube_ids,
        "source_rejections": [{"youtube_id": value, "kind": "source_quality"} for value in rejected_youtube_ids],
    }
    if failure:
        payload.update({"kind": "failure", "failure": failure, "failure_kind": args.failure_kind})
    else:
        payload.update(
            {
                "kind": "production",
                "mp4": str(args.mp4.resolve()),
                "manifest": str(args.manifest.resolve()),
                "audio_qa_report": str(args.audio_qa_report.expanduser().resolve()),
            }
        )

    request_path = args.request.resolve()
    request_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = request_path.with_suffix(request_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(request_path)
    print(f"English World delivery request recorded: {request_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
