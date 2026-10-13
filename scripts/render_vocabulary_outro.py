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
    args = parser.parse_args()
    print(build(args.source, args.subtitle, args.output, args.title))


if __name__ == '__main__':
    main()
