"""仅本地渲染生词片尾；无数据库、上传或发布入口。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 提供可追踪子进程及真实成片验证入口 |
"""
import argparse
from pathlib import Path
from video_processing.processors.vocabulary_outro import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--subtitle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--recover-empty', action='store_true')
    parser.add_argument('--record-policy', action='store_true')
    args = parser.parse_args()
    from video_processing.utils.vocabulary_outro_policy import update_record
    from video_processing.processors.vocabulary_outro import receipt_path
    import json
    try:
        result = build(args.source, args.subtitle, args.output, args.title, recover_empty=args.recover_empty)
        if args.record_policy:
            receipt = json.loads(receipt_path(args.output).read_text())
            update_record(args.output.parent, args.subtitle.stem,
                          'RENDERED' if receipt['status'] == 'rendered' else 'NO_SUITABLE_TERMS',
                          items_count=len(receipt.get('items', [])), recovery_checked=receipt.get('recovery_checked', False))
        print(result)
    except Exception as exc:
        if args.record_policy:
            update_record(args.output.parent, args.subtitle.stem, 'FAILED',
                          error_code=getattr(exc, 'code', type(exc).__name__))
        raise


if __name__ == '__main__':
    main()
