"""显式原值迁移到运行配置中心；不初始化业务库、不访问平台、不重置账本。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| runtime-center-v1 | 2026-10-24 | Codex | 原值快照、只写非秘密批准基线和不可变版本，重复运行不覆盖。 |
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from config.settings import settings
from config.runtime_policy import atomic
from video_processing.utils.runtime_configuration import store,initial_domains,validate_domains


def main():
    import argparse
    from config.runtime_policy import PolicyStore,decode
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory',type=Path)
    parser.add_argument('--input',type=Path)
    args=parser.parse_args()
    if settings.runtime_configuration_enabled and not args.input:
        print('配置中心已启用，不重新迁移或重置基线。')
        return 2
    if bool(args.directory)!=bool(args.input):
        parser.error('--directory与--input须同时指定；只接受经过核对的原值快照')
    data=decode(args.input.read_bytes()) if args.input else initial_domains();validate_domains(data)
    target=PolicyStore(args.directory) if args.directory else store()
    if (target.root/'active.json').exists():
        current=target.read()
        print('活动版本已存在，保留 '+current.version)
        return 0
    # 原始批准基线不是活动领域；没有HTTP写入口。
    with target.locked(write=True):
        if not (target.root/'approved-baseline.json').exists():
            atomic(target.root/'approved-baseline.json',data)
    current=target.initialize(data,validate=validate_domains)
    print('原值迁移完成 '+current.version+' '+current.revision)
    return 0


if __name__=='__main__':raise SystemExit(main())
