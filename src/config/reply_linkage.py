"""回复设置的联动模式、推荐公式与有界本地容量模拟；不调用平台。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-25 | Codex | 每日额度联动、持久手动覆盖及实际检查节拍容量校验。 |
"""
from collections import deque
from math import ceil, floor

DEFAULT_LINKAGE = {"initialized": False, "hourly_quota": "auto", "min_interval_seconds": "auto"}


def validate_linkage(value):
    if (not isinstance(value, dict) or set(value) != set(DEFAULT_LINKAGE)
            or type(value["initialized"]) is not bool
            or any(value[key] not in ("auto", "manual") for key in ("hourly_quota", "min_interval_seconds"))):
        raise ValueError("回复联动状态无效")
    return value


def window_minutes(start, end):
    def minute(text, allow_end=False):
        import re
        if not isinstance(text, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d|24:00" if allow_end else r"(?:[01]\d|2[0-3]):[0-5]\d", text):
            raise ValueError("请填写有效的北京时间窗口")
        h, m = map(int, text.split(":"))
        return h * 60 + m
    a, b = minute(start), minute(end, True)
    return a, (b - a) % 1440 or 1440


def opportunities(start, minutes, hourly, interval, cadence):
    """固定检查节拍，逐次执行滚动小时门禁；取预热后两天的保守容量。"""
    history = deque()
    last = None
    counts = [0, 0, 0]
    for now in range(0, 3 * 86400, cadence):
        if ((now // 60 - start) % 1440) >= minutes:
            continue
        while history and history[0] <= now - 3600:
            history.popleft()
        if len(history) >= hourly or (last is not None and now - last < interval):
            continue
        history.append(now)
        last = now
        counts[now // 86400] += 1
    return min(counts[1:])


def calculate(config, cadence, *, max_hourly=50, min_interval=60):
    """只重算自动字段；无可核验调度时不伪造自动值或容量。"""
    result = dict(config)
    linkage = dict(validate_linkage(config.get("linkage", DEFAULT_LINKAGE)))
    result["linkage"] = linkage
    daily = config["daily_quota"]
    if type(daily) is not int or not 1 <= daily <= 1000:
        raise ValueError("最近24小时回复上限须为1–1000的整数")
    start, minutes = window_minutes(config["window_start_shanghai"], config["window_end_shanghai"])
    if type(cadence) is not int or not 1 <= cadence <= 3600:
        if linkage["initialized"] and "auto" in (linkage["hourly_quota"], linkage["min_interval_seconds"]):
            raise ValueError("发送检查周期尚未核实，不能生成自动推荐；请重新载入或改为手动")
        return result, {"opportunities": None, "attainable": None, "insufficient": None,
                        "message": "发送调度未核实，理论容量未知；已保存数值保持不变。"}
    recommended_hourly = min(daily, max_hourly, ceil(daily * 1.2 * 60 / minutes))
    if linkage["initialized"]:
        if linkage["hourly_quota"] == "auto":
            result["hourly_quota"] = recommended_hourly
        # 手动小时值也是自动间隔的输入；恢复自动不会覆盖该小时值。
        hourly = result["hourly_quota"]
        if type(hourly) is not int or not 1 <= hourly <= max_hourly or hourly > daily:
            raise ValueError("小时上限须在批准范围内，且不能超过最近24小时上限")
        if linkage["min_interval_seconds"] == "auto":
            result["min_interval_seconds"] = max(min_interval, cadence * floor(3600 / (hourly * cadence)))
    hourly, interval = result["hourly_quota"], result["min_interval_seconds"]
    if type(hourly) is not int or not 1 <= hourly <= max_hourly or hourly > daily:
        raise ValueError("小时上限须在批准范围内，且不能超过最近24小时上限")
    if type(interval) is not int or not min_interval <= interval <= 604800:
        raise ValueError("最小提交间隔须为批准范围内的整数")
    capacity = opportunities(start, minutes, hourly, interval, cadence)
    insufficient = capacity < daily
    message = (f"理想调度机会约 {capacity} 条/24小时；最近24小时硬上限 {daily} 条。"
               + ("容量不足，请增加小时额度、缩短间隔或延长时段；也可保留手动配置。" if insufficient
                  else "目标容量足够。" if capacity >= ceil(daily * 1.2) else "目标容量足够，余量不足20%。")
               + "实际数量还取决于合格待发任务、机器运行和平台限制。")
    return result, {"opportunities": capacity, "attainable": min(daily, capacity),
                    "insufficient": insufficient, "message": message, "cadence_seconds": cadence}
