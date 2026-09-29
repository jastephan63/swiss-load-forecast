from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

import holidays
import numpy as np
import pandas as pd
from dateutil.easter import easter

DAYTYPE_WORKDAY = 0
DAYTYPE_SATURDAY = 1
DAYTYPE_SUNDAY_OR_HOLIDAY = 2


def holiday_table(years: Iterable[int], canton_weights: Mapping[str, float]) -> pd.DataFrame:
    years = sorted(set(years))
    start, end = date(years[0], 1, 1), date(years[-1], 12, 31)
    days = pd.date_range(start, end, freq="D")
    share = pd.Series(0.0, index=days)
    names: dict[pd.Timestamp, set[str]] = {}
    for canton, weight in canton_weights.items():
        cal = holidays.Switzerland(subdiv=canton, years=years, language="en_US")
        for d, name in cal.items():
            ts = pd.Timestamp(d)
            if ts in share.index:
                share.loc[ts] += weight
                names.setdefault(ts, set()).add(str(name))
    national = holidays.Switzerland(years=years)
    frame = pd.DataFrame(
        {
            "holiday_share": share.clip(0.0, 1.0).round(6),
            "national_holiday": [d.date() in national for d in days],
            "holiday_name": ["; ".join(sorted(names.get(d, set()))) for d in days],
        },
        index=days,
    )
    frame.index.name = "local_date"
    return frame


def school_holiday_proxy(days: pd.DatetimeIndex, periods: list[dict[str, Any]]) -> pd.Series:
    flag = pd.Series(False, index=days)
    for year in sorted({d.year for d in days}):
        for p in periods:
            if "easter_offset_start" in p:
                e = easter(year)
                s = e + timedelta(days=int(p["easter_offset_start"]))
                t = e + timedelta(days=int(p["easter_offset_end"]))
                flag |= (days.date >= s) & (days.date <= t)
                continue
            sm, sd = (int(x) for x in str(p["start"]).split("-"))
            em, ed = (int(x) for x in str(p["end"]).split("-"))
            s = date(year, sm, sd)
            t = date(year, em, ed) if (em, ed) >= (sm, sd) else date(year + 1, em, ed)
            flag |= (days.date >= s) & (days.date <= t)
            if (em, ed) < (sm, sd):
                flag |= (days.date >= date(year, 1, 1)) & (days.date <= date(year, em, ed))
    return flag.astype(int)


def daily_calendar(
    years: Iterable[int],
    canton_weights: Mapping[str, float],
    holiday_threshold: float,
    school_periods: list[dict[str, Any]],
) -> pd.DataFrame:
    years = sorted(set(years))
    padded = [years[0] - 1, *years, years[-1] + 1]
    cal = holiday_table(padded, canton_weights)
    days = pd.DatetimeIndex(cal.index)
    weekday = days.weekday
    is_holiday = cal["holiday_share"] >= holiday_threshold
    off = pd.Series((weekday >= 5) | is_holiday.to_numpy(), index=days)
    workday = ~off
    bridge = workday & off.shift(1, fill_value=False) & off.shift(-1, fill_value=False)
    cal["is_holiday"] = is_holiday.astype(int)
    cal["bridge_day"] = bridge.astype(int)
    cal["day_before_holiday"] = is_holiday.shift(-1, fill_value=False).astype(int)
    cal["day_after_holiday"] = is_holiday.shift(1, fill_value=False).astype(int)
    cal["holiday_share_prev"] = cal["holiday_share"].shift(1, fill_value=0.0)
    cal["holiday_share_next"] = cal["holiday_share"].shift(-1, fill_value=0.0)
    cal["school_holiday_proxy"] = school_holiday_proxy(days, school_periods)
    daytype = np.where(
        (weekday == 6) | is_holiday.to_numpy(),
        DAYTYPE_SUNDAY_OR_HOLIDAY,
        np.where(weekday == 5, DAYTYPE_SATURDAY, DAYTYPE_WORKDAY),
    )
    cal["daytype"] = daytype
    return cal


def hourly_calendar(index: pd.DatetimeIndex, tz: str, daily: pd.DataFrame) -> pd.DataFrame:
    local = index.tz_convert(tz)
    local_date = pd.DatetimeIndex(local.tz_localize(None).normalize())
    out = pd.DataFrame(index=index)
    out["local_date"] = local_date
    out["hour"] = local.hour
    out["weekday"] = local.weekday
    out["month"] = local.month
    out["day_of_year"] = local.dayofyear
    out["is_weekend"] = (local.weekday >= 5).astype(int)
    doy = 2 * np.pi * (local.dayofyear - 1) / 365.25
    out["doy_sin"] = np.sin(doy)
    out["doy_cos"] = np.cos(doy)
    joined = daily.reindex(local_date)
    for col in (
        "holiday_share",
        "is_holiday",
        "bridge_day",
        "day_before_holiday",
        "day_after_holiday",
        "holiday_share_prev",
        "holiday_share_next",
        "school_holiday_proxy",
        "daytype",
    ):
        out[col] = joined[col].to_numpy()
    out["hour_daytype"] = out["hour"] + 24 * out["daytype"]
    return out
