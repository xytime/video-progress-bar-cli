"""OptionSense 美东时间（ET）安全窗口与重负载避让门禁测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-19 | Antigravity | 建立基于 America/New_York 的 OptionSense 避让与全马力安全窗口测试。 |
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import Settings


def test_optionsense_safe_window_weekend_58_5_hours():
    eastern = ZoneInfo("America/New_York")
    settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="optionsense",
    )

    # 2026-07-10 为周五 (NYSE 正常交易日)
    # 1. 周五 20:29 ET 仍处于盘后避让时段
    fri_pre = datetime(2026, 7, 10, 20, 29, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(fri_pre)
    assert settings.is_us_market_guard_window(fri_pre)

    # 2. 周五 20:30 ET 周末安全窗口正式开启
    fri_open = datetime(2026, 7, 10, 20, 30, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(fri_open)
    assert not settings.is_us_market_guard_window(fri_open)

    # 3. 周六全天全马力可用 (例如 12:00 ET)
    sat_noon = datetime(2026, 7, 11, 12, 0, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(sat_noon)
    assert not settings.is_us_market_guard_window(sat_noon)

    # 4. 周日全天全马力可用 (例如 23:59 ET)
    sun_night = datetime(2026, 7, 12, 23, 59, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(sun_night)
    assert not settings.is_us_market_guard_window(sun_night)

    # 5. 2026-07-13 为周一：06:59 ET 仍处于周末 58.5h 安全窗口
    mon_morning = datetime(2026, 7, 13, 6, 59, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(mon_morning)
    assert not settings.is_us_market_guard_window(mon_morning)

    # 6. 周一 07:00 ET OptionSense 交易日前序启动，进入避让
    mon_guard = datetime(2026, 7, 13, 7, 0, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(mon_guard)
    assert settings.is_us_market_guard_window(mon_guard)


def test_optionsense_safe_window_trading_days():
    eastern = ZoneInfo("America/New_York")
    settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="optionsense",
    )

    # 2026-07-14 为周二 (正常交易日)
    # 1. 04:14 ET 属于夜间安全时段尾声
    tue_early = datetime(2026, 7, 14, 4, 14, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(tue_early)
    assert not settings.is_us_market_guard_window(tue_early)

    # 2. 04:15 ET OptionSense 盘前扫描器启动，进入强制避让
    tue_pre = datetime(2026, 7, 14, 4, 15, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_pre)
    assert settings.is_us_market_guard_window(tue_pre)

    # 3. 盘中 14:00 ET (正盘交易) 必须避让
    tue_noon = datetime(2026, 7, 14, 14, 0, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_noon)
    assert settings.is_us_market_guard_window(tue_noon)

    # 4. 盘后 20:29 ET 仍在归档分析，必须避让
    tue_post = datetime(2026, 7, 14, 20, 29, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_post)
    assert settings.is_us_market_guard_window(tue_post)

    # 5. 20:30 ET OptionSense 当日收工，夜间可用窗口开启 (连续 7h45m)
    tue_night = datetime(2026, 7, 14, 20, 30, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(tue_night)
    assert not settings.is_us_market_guard_window(tue_night)


def test_optionsense_safe_window_holidays():
    eastern = ZoneInfo("America/New_York")
    settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="optionsense",
    )

    # 2026-07-03 为美国独立日休市（提前休市日）
    holiday_noon = datetime(2026, 7, 3, 12, 0, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(holiday_noon)
    assert not settings.is_us_market_guard_window(holiday_noon)


def test_optionsense_guard_policy_switch():
    eastern = ZoneInfo("America/New_York")
    # 模式为 legacy nyse_regular 时，仅在常规盘 09:30-16:00 避让
    legacy_settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="nyse_regular",
    )

    # 09:29 ET 在 legacy 下不避让
    assert not legacy_settings.is_us_market_guard_window(datetime(2026, 7, 1, 9, 29, tzinfo=eastern))
    # 09:30 ET 在 legacy 下避让
    assert legacy_settings.is_us_market_guard_window(datetime(2026, 7, 1, 9, 30, tzinfo=eastern))
    # 16:00 ET 在 legacy 下已收盘不避让
    assert not legacy_settings.is_us_market_guard_window(datetime(2026, 7, 1, 16, 0, tzinfo=eastern))
