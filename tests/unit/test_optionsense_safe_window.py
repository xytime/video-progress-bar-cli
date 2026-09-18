"""OptionSense 美东时间（ET）安全窗口与重负载避让门禁测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.1.0 | 2026-09-19 | Antigravity | 支持 16:15~17:50 与 19:00~08:30 多时段配置与标点容错。 |
| 1.0.0 | 2026-09-19 | Antigravity | 建立基于 America/New_York 的 OptionSense 避让与全马力安全窗口测试。 |
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import Settings


def test_optionsense_safe_window_trading_days_multi_slots():
    eastern = ZoneInfo("America/New_York")
    settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="optionsense",
        optionsense_trading_day_safe_windows="16:15-17:50,19:00-08:30",
    )

    # 2026-07-14 为周二 (NYSE 正常交易日)
    # 1. 08:29 ET 属于夜间跨午夜窗口 (19:00~08:30) 安全可用
    tue_early_safe = datetime(2026, 7, 14, 8, 29, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(tue_early_safe)
    assert not settings.is_us_market_guard_window(tue_early_safe)

    # 2. 08:30 ET 避让窗口开启 (盘前准备)，必须避让
    tue_morning_guard = datetime(2026, 7, 14, 8, 30, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_morning_guard)
    assert settings.is_us_market_guard_window(tue_morning_guard)

    # 3. 盘中 14:00 ET (正盘交易)，必须避让
    tue_noon = datetime(2026, 7, 14, 14, 0, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_noon)
    assert settings.is_us_market_guard_window(tue_noon)

    # 4. 16:14 ET 仍处于盘中收盘收尾，必须避让
    tue_post_pre = datetime(2026, 7, 14, 16, 14, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_post_pre)
    assert settings.is_us_market_guard_window(tue_post_pre)

    # 5. 16:15 ET 盘后空闲窗口 (16:15~17:50) 开启，安全可用
    tue_post_open = datetime(2026, 7, 14, 16, 15, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(tue_post_open)
    assert not settings.is_us_market_guard_window(tue_post_open)

    # 6. 17:49 ET 仍处于盘后空闲窗口，安全可用
    tue_post_mid = datetime(2026, 7, 14, 17, 49, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(tue_post_mid)
    assert not settings.is_us_market_guard_window(tue_post_mid)

    # 7. 17:50 ET 盘后分析/定时归档开始 (17:50~19:00)，必须避让
    tue_evening_guard = datetime(2026, 7, 14, 17, 50, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_evening_guard)
    assert settings.is_us_market_guard_window(tue_evening_guard)

    # 8. 18:59 ET 仍在避让
    tue_evening_pre = datetime(2026, 7, 14, 18, 59, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(tue_evening_pre)
    assert settings.is_us_market_guard_window(tue_evening_pre)

    # 9. 19:00 ET 晚间长安全窗口 (19:00~08:30) 开启，安全可用
    tue_night_open = datetime(2026, 7, 14, 19, 0, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(tue_night_open)
    assert not settings.is_us_market_guard_window(tue_night_open)

    # 10. 23:59 ET 深夜安全可用
    tue_midnight = datetime(2026, 7, 14, 23, 59, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(tue_midnight)
    assert not settings.is_us_market_guard_window(tue_midnight)

    # 11. 次日凌晨 04:15 ET 依然安全可用
    wed_early = datetime(2026, 7, 15, 4, 15, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(wed_early)
    assert not settings.is_us_market_guard_window(wed_early)


def test_optionsense_safe_window_weekend_continuity():
    eastern = ZoneInfo("America/New_York")
    settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="optionsense",
        optionsense_trading_day_safe_windows="16:15-17:50,19:00-08:30",
    )

    # 2026-07-10 为周五 (正常交易日)
    # 周五 19:00 ET 开始进入连续周末全马力模式
    fri_night = datetime(2026, 7, 10, 19, 0, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(fri_night)

    # 周六全天可用
    sat_noon = datetime(2026, 7, 11, 12, 0, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(sat_noon)

    # 周日全天可用
    sun_noon = datetime(2026, 7, 12, 12, 0, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(sun_noon)

    # 2026-07-13 周一 08:29 ET 仍在安全窗口
    mon_morning = datetime(2026, 7, 13, 8, 29, tzinfo=eastern)
    assert settings.is_optionsense_safe_window(mon_morning)

    # 周一 08:30 ET 避让开启
    mon_guard = datetime(2026, 7, 13, 8, 30, tzinfo=eastern)
    assert not settings.is_optionsense_safe_window(mon_guard)


def test_optionsense_syntax_tolerance():
    eastern = ZoneInfo("America/New_York")
    # 支持 ~ 波浪号、顿号、分号及单个小时位（如 8:30）
    tolerant_settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="optionsense",
        optionsense_trading_day_safe_windows="16:15~17:50 、 19:00~8:30",
    )

    in_slot1 = datetime(2026, 7, 14, 16, 30, tzinfo=eastern)
    assert tolerant_settings.is_optionsense_safe_window(in_slot1)

    in_slot2 = datetime(2026, 7, 14, 20, 0, tzinfo=eastern)
    assert tolerant_settings.is_optionsense_safe_window(in_slot2)

    in_morning = datetime(2026, 7, 14, 8, 15, tzinfo=eastern)
    assert tolerant_settings.is_optionsense_safe_window(in_morning)

    out_slot = datetime(2026, 7, 14, 18, 0, tzinfo=eastern)
    assert not tolerant_settings.is_optionsense_safe_window(out_slot)


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
    legacy_settings = Settings(
        enable_market_hours_guard=True,
        market_guard_policy="nyse_regular",
    )

    assert not legacy_settings.is_us_market_guard_window(datetime(2026, 7, 1, 9, 29, tzinfo=eastern))
    assert legacy_settings.is_us_market_guard_window(datetime(2026, 7, 1, 9, 30, tzinfo=eastern))
    assert not legacy_settings.is_us_market_guard_window(datetime(2026, 7, 1, 16, 0, tzinfo=eastern))
