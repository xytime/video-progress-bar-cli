"""只读核验当前回复发送计划的检查节拍；不启动或修改计划。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 从实际加载定义核实检查周期，未知时不作容量承诺。 |
"""
import plistlib
import subprocess
from .deployment import DeploymentDenied
from pathlib import Path
from config.settings import settings
from .deployment_schedules import Schedules


def verified_cadence():
    try:
        schedules = Schedules(settings.project_root, settings.default_output_dir)
        label = "com.videopipeline.secondary-reply-send"
        state = schedules.service(label)
        if not state["loaded"] or schedules.disabled().get(label):
            return None
        definition = plistlib.loads(Path(state["path"]).read_bytes())
        args = definition.get("ProgramArguments", [])
        interval = definition.get("StartInterval")
        expected = ["tick", "--max-reconcile", "0", "--max-submit", "1", "--scan-posts", "0", "--max-drafts", "0"]
        if (definition.get("Label") != label or definition.get("WorkingDirectory") != str(settings.project_root)
                or str(settings.project_root / "scripts/wechat_secondary_reply.py") not in args
                or args[-len(expected):] != expected or definition.get("KeepAlive")
                or type(interval) is not int or not 1 <= interval <= 3600):
            return None
        return interval
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, DeploymentDenied):
        # 宿主查询失败不影响既有配置读取；页面明确显示容量未知。
        return None
