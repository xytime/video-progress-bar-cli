"""商品配置 validate/apply/preview/status；只操作本地配置，不登录、上传或发表。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from config.settings import settings
from video_processing.utils.wechat_product_context import video_product_context
from video_processing.utils.wechat_product_config import (
    load_policy, activate_policy, policy_status, decision_payload,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=settings.wechat_product_policy_path)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    for name in ('validate', 'apply'):
        child = sub.add_parser(name)
        child.add_argument('candidate', type=Path)
    preview = sub.add_parser('preview')
    preview.add_argument('--video-id')
    preview.add_argument('--category')
    preview.add_argument('--content-type')
    preview.add_argument('--product-topic')
    preview.add_argument('--slice-index', type=int, default=0)
    preview.add_argument('--source-channel-id')
    preview.add_argument('--product-alias')
    args = parser.parse_args(argv)
    try:
        if args.action in ('validate', 'apply'):
            policy = (activate_policy(args.candidate, args.config) if args.action == 'apply'
                      else load_policy(args.candidate))
            output = {'valid': True, 'activated': args.action == 'apply',
                      'version': policy.version, 'digest': policy.digest}
        elif args.action == 'status':
            output = policy_status(args.config, settings.wechat_product_status_path)
        else:
            context = (video_product_context(ROOT / 'output', {'youtube_id': args.video_id,
                       'slice_index': args.slice_index, 'content_type': args.content_type}) if args.video_id else {})
            for key in ('category', 'source_channel_id', 'content_type', 'product_topic'):
                if getattr(args, key) is not None:
                    context[key] = getattr(args, key)
            decision = load_policy(args.config).decide(**context, product_alias=args.product_alias)
            output = dict(decision_payload(decision), preview_only=True, platform_availability='NOT_VERIFIED')
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        # 仅处理公开策略文件；不输出其他配置值或凭据。
        output = {'error': str(exc), 'activated': False}
        if args.action == 'apply':
            try:
                active = load_policy(args.config)
                output.update(active_version=active.version, active_digest=active.digest)
            except (ValueError, OSError):
                output['active_version'] = None
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
