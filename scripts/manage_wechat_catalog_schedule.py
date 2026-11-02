"""维护窗内安装每日07:35本机时间的只读商品同步；快照/CAS/回读沿用项目调度工具。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| catalog-sync-v1 | 2026-11-02 | Codex | 独立受管同步cron，保持其他调度和原运行意图。 |
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config.settings import settings
from video_processing.core.deployment_schedules import Schedules


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--expected-cron-sha', required=True)
    args = parser.parse_args()
    if args.directory.resolve().is_relative_to(settings.project_root.resolve()):
        raise ValueError('调度备份必须位于工作区外')
    result = Schedules(settings.project_root, args.directory).install_catalog_sync(args.expected_cron_sha)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
