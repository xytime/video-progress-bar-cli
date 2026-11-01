"""原生流水线字幕入口；继承同一在途任务的维护凭据。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 复用现有单脚本凭据校验，维护排空期间保留字幕审计写入。 |
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_processing.core.maintenance_child import single_script


@single_script
def main():
    from cli.main import main as run_cli
    return run_cli()


if __name__ == '__main__':
    main()
