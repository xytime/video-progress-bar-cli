"""英语世界生产时刻的共享配置与已安装调度核验。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-18 | Antigravity | 生产时刻优先读取 english_world_production_slots，支持多时段生产调度。 |
| 1.0.0 | 2026-09-06 | Codex | 安装器与监控器共享时刻；检测漂移后禁止错误补跑。 |
"""
from datetime import time
from pathlib import Path
import plistlib

from config.settings import settings


def production_slots() -> tuple[time, ...]:
    slots_str = getattr(settings, "english_world_production_slots", "") or settings.english_world_daily_slots
    try:
        slots = tuple(sorted({time.fromisoformat(value.strip())
                              for value in slots_str.split(",") if value.strip()}))
    except ValueError as exc:
        raise ValueError("english_world_production_slots 必须为逗号分隔的 HH:MM") from exc
    if not slots or any(slot.second or slot.microsecond for slot in slots):
        raise ValueError("英语世界生产时刻不能为空且必须精确到分钟")
    return slots


def calendar_intervals() -> list[dict[str, int]]:
    return [{"Hour": slot.hour, "Minute": slot.minute} for slot in production_slots()]


def validate_installed_schedule(path: Path) -> None:
    with path.open("rb") as stream:
        actual = plistlib.load(stream).get("StartCalendarInterval")
    if actual != calendar_intervals():
        raise ValueError("英语世界已安装 LaunchAgent 与配置时刻不一致；先重装调度，禁止自动补跑")
