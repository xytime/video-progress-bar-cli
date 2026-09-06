"""英语世界生产时刻的共享配置与已安装调度核验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-06 | Codex | 安装器与监控器共享时刻；检测漂移后禁止错误补跑。 |
"""
from datetime import time
from pathlib import Path
import plistlib

from config.settings import settings


def production_slots() -> tuple[time, ...]:
    try:
        slots = tuple(sorted({time.fromisoformat(value.strip())
                              for value in settings.english_world_daily_slots.split(",")}))
    except ValueError as exc:
        raise ValueError("english_world_daily_slots 必须为逗号分隔的 HH:MM") from exc
    if not slots or any(slot.second or slot.microsecond for slot in slots):
        raise ValueError("英语世界日更时刻不能为空且必须精确到分钟")
    return slots


def calendar_intervals() -> list[dict[str, int]]:
    return [{"Hour": slot.hour, "Minute": slot.minute} for slot in production_slots()]


def validate_installed_schedule(path: Path) -> None:
    with path.open("rb") as stream:
        actual = plistlib.load(stream).get("StartCalendarInterval")
    if actual != calendar_intervals():
        raise ValueError("英语世界已安装 LaunchAgent 与配置时刻不一致；先重装调度，禁止自动补跑")
