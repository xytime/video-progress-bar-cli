"""商品配置 validate/apply/preview/status；只操作本地配置，不登录、上传或发表。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from config.settings import settings
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
            category, channel = args.category, args.source_channel_id
            if args.video_id:
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.video_id):
                    raise ValueError('非法 video-id')
                base = ROOT / 'output' / args.video_id
                category_path = base.with_name(base.name + '_category.txt')
                info_path = base.with_name(base.name + '.info.json')
                if category is None and category_path.exists():
                    category = category_path.read_text().strip()
                if channel is None and info_path.exists():
                    info = json.loads(info_path.read_text())
                    if not isinstance(info, dict):
                        raise ValueError('视频元数据必须为对象')
                    channel = info.get('channel_id')
            decision = load_policy(args.config).decide(category=category, source_channel_id=channel,
                                                       product_alias=args.product_alias)
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
