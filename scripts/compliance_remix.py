#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合规二创可信本地人工入口；--execute 是对绑定哈希内容的一次批准。

本地调用者为本机操作者信任边界。Telegram 必须先在 Bot 校验管理员与绑定上下文，
随后用 --approved 消耗已有审批；CLI 的 actor 参数本身不是远端鉴权。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-25 | GPT-6.1 Sol | 显式绑定批准、旧清单仅只读演练、发布授权隔离 |
| 1.0.0 | 2026-10-25 | Antigravity | 初始入口 |
"""
import argparse
import asyncio
import json
import sys
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_processing.compliance_remix.remix_service import ComplianceRemixService
from video_processing.compliance_remix.manifest_contract import validate_manifest


def main():
    parser = argparse.ArgumentParser(description="合规二创：不可变提案、人工批准与一次性制作")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--propose", action="store_true", help="仅取字幕和元数据生成提案")
    modes.add_argument("--execute", action="store_true", help="本地人工批准绑定哈希的提案并制作一次")
    parser.add_argument("--url")
    parser.add_argument("--video-id", help="独立提案 ID，不是原片 ID")
    parser.add_argument("--content-hash", help="已审阅清单的完整 SHA256")
    parser.add_argument("--actor", default="local")
    parser.add_argument("--chat", default="local")
    parser.add_argument("--approved", action="store_true", help="消耗 Bot 已持久批准的任务，不另行批准")
    parser.add_argument("--manifest", help="旧清单只支持 --dry-run")
    parser.add_argument("--source-video")
    parser.add_argument("--work-dir")
    parser.add_argument("--dry-run", action="store_true", help="只读验证，不领取、不创建文件或修改状态")
    parser.add_argument("--publish", action="store_true", help="独立发布用途；缺拟用画面审核证据时阻断")
    parser.add_argument("--source-reviewed", action="store_true", help="人工确认已核对完整来源事实、脚本与全部拟用镜头")
    args = parser.parse_args()
    # 旧入口在初始化 DB / 媒体引擎之前拒绝生产。
    if args.manifest:
        if not args.dry_run or args.publish or args.execute or args.propose:
            parser.error("旧 manifest 只支持独立 --dry-run，不可制作或发布")
        manifest = json.loads(Path(args.manifest).read_text("utf-8"))
        validate_manifest(manifest)
        from video_processing.compliance_remix.censor_guard import ComplianceCensorGuard
        report = ComplianceCensorGuard().validate_script_manifest(manifest)
        if not report.passed:
            raise PermissionError("清单全量内容检查未通过")
        print(json.dumps({"status": "VALIDATED", "upload_status": "NOT_SUBMITTED"}, ensure_ascii=False))
        return
    if not (args.propose or args.execute):
        parser.print_help()
        return
    if args.propose and (not args.url or args.dry_run or args.approved):
        parser.error("--propose 需要 --url，不能与 dry-run/approved 混用")
    if args.execute and not args.video_id:
        parser.error("--execute 需要 --video-id")
    if args.execute and not args.dry_run and not args.content_hash:
        parser.error("实际执行需要显式 --content-hash，绑定已审内容")
    if args.execute and not args.dry_run and not args.approved and not args.source_reviewed:
        parser.error("实际制作前必须 --source-reviewed 确认已核对来源事实、脚本及全部拟用镜头")
    if args.execute and args.publish:
        parser.error("目前无可核验源画面审核证据，发布被阻断")
    from compliance_remix_adapters import build_pipeline
    if args.dry_run:
        from config.settings import settings
        from video_processing.db.database import PipelineDB
        service = ComplianceRemixService(db=PipelineDB(str(PROJECT_ROOT / "output/pipeline.db"), read_only=True), pipeline_factory=build_pipeline)
    else:
        service = ComplianceRemixService(pipeline_factory=build_pipeline)
    if args.propose:
        result = service.propose_remix(args.url, args.work_dir, actor=args.actor, chat=args.chat,
                                      purpose="publish" if args.publish else "produce")
    else:
        if not args.dry_run and not args.approved:
            service.approve_remix(args.video_id, actor=args.actor, chat=args.chat, content_hash=args.content_hash,
                                  purpose="publish" if args.publish else "produce", source_reviewed=args.source_reviewed)
        result = asyncio.run(service.execute_approved_remix(args.video_id, upload_now=args.publish,
                  dry_run=args.dry_run, actor=args.actor, chat=args.chat, content_hash=args.content_hash or ""))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    def _terminate(signum, frame):
        raise KeyboardInterrupt("SIGTERM: 终止生产并清理子进程")
    signal.signal(signal.SIGTERM, _terminate)
    main()
