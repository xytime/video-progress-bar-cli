"""每日只读同步视频号橱窗；额度不足或证据不足只落尝试回执，不重试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| catalog-sync-v1 | 2026-11-02 | Codex | 原生维护准入，独立账号预算与只读DOM采集；不发送消息或投稿。 |
"""
import json
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_processing.utils.wechat_product_sync import run_catalog_sync


def main():
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--status',action='store_true',help='仅本地检查严格当前池，不访问平台')
    args=parser.parse_args()
    if args.status:
        from config.settings import settings
        from video_processing.utils.wechat_product_pool import load_live_pool
        result=load_live_pool(settings.wechat_product_policy_path)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    result = run_catalog_sync()
    print(json.dumps({k: v for k, v in result.items() if k != 'partial'}, ensure_ascii=False))
    return 0 if result['state'] == 'COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
