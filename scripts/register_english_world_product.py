#!/usr/bin/env python3
"""来源预检通过后、首次翻译/富化前登记独立英语世界正式制作商品任务。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from video_processing.db.database import PipelineDB
from video_processing.english_world.product_production import start_product_production
from video_processing.utils.wechat_product_config import atomic_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeline', type=Path, required=True)
    parser.add_argument('--product-intent', choices=('AUTO', 'NONE', 'PRODUCT'), default='AUTO')
    parser.add_argument('--product-id')
    parser.add_argument('--product-title')
    parser.add_argument('--shadow-only', action='store_true', help='仅本地预演，不占正式制作名额')
    args = parser.parse_args(argv)
    try:
        if args.shadow_only:
            print('影子制作不登记自动英语世界商品名额')
            return 0
        payload = json.loads(args.timeline.read_text(encoding='utf-8'))
        result = start_product_production(PipelineDB(), payload, product_intent=args.product_intent,
                                         product_id=args.product_id, product_title=args.product_title,
                                         state_path=PROJECT_ROOT / 'output' / 'wechat_state.json')
        atomic_json(args.timeline, result)
        print(json.dumps({'product_context': result['product_context'],
                          'product_production': result.get('product_production')}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f'英语世界商品正式制作登记失败：{exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
