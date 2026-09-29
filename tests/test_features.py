from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swiss_load_forecast.calendar_features import daily_calendar, hourly_calendar
from swiss_load_forecast.features import (
    ForecastSetup,
    issue_time_utc,
    lag_feature_names,
    lagged_weather_features,
    load_lag_features,
)

TZ = "Europe/Zurich"
SETUP = ForecastSetup(tz=TZ, issue_hour=10, lag_hours=(48, 72, 168, 336), weekly_mean_weeks=4)
WEIGHTS = {"ZH": 0.5, "GE": 0.3, "TI": 0.2}
SCHOOL = [{"name": "summer", "start": "07-05", "end": "08-15"}]


def hourly_index(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(
        pd.Timestamp(start, tz=TZ).tz_convert("UTC"),
        pd.Timestamp(end, tz=TZ).tz_convert("UTC"),
        freq="h",
        inclusive="left",
    )


@pytest.fixture
def load() -> pd.Series:
    idx = hourly_index("2024-02-01", "2024-11-30")
    rng = np.random.default_rng(0)
    return pd.Series(6000 + rng.normal(0, 300, len(idx)), index=idx)


@pytest.fixture
def weather() -> pd.DataFrame:
    idx = hourly_index("2024-02-01", "2024-11-30")
    rng = np.random.default_rng(1)
    return pd.DataFrame(
        {
            "temperature_c": rng.normal(10, 5, len(idx)),
            "radiation_wm2": rng.uniform(0, 800, len(idx)),
        },
        index=idx,
    )


def target_day(day: str) -> pd.DatetimeIndex:
    return hourly_index(day, str((pd.Timestamp(day) + pd.Timedelta(days=1)).date()))


def corrupt_after_issue(data: pd.Series | pd.DataFrame, day: str) -> pd.Series | pd.DataFrame:
    issue = issue_time_utc(pd.DatetimeIndex([pd.Timestamp(day)]), SETUP)[0]
    corrupted = data.copy()
    corrupted.loc[corrupted.index >= issue] = 1e9
    return corrupted


@pytest.mark.parametrize("day", ["2024-03-31", "2024-04-01", "2024-07-15", "2024-10-27"])
def test_load_features_do_not_use_data_after_issue_time(load: pd.Series, day: str) -> None:
    idx = target_day(day)
    clean = load_lag_features(load, idx, SETUP)
    leaked = load_lag_features(corrupt_after_issue(load, day), idx, SETUP)
    pd.testing.assert_frame_equal(clean, leaked)
    assert clean.notna().all().all()


@pytest.mark.parametrize("day", ["2024-03-31", "2024-07-15", "2024-10-27"])
def test_lagged_weather_does_not_use_data_after_issue_time(weather: pd.DataFrame, day: str) -> None:
    idx = target_day(day)
    clean = lagged_weather_features(weather, idx, SETUP, 16.0, 22.0)
    leaked = lagged_weather_features(corrupt_after_issue(weather, day), idx, SETUP, 16.0, 22.0)
    pd.testing.assert_frame_equal(clean, leaked)


def test_corrupting_before_issue_time_changes_features(load: pd.Series) -> None:
    day = "2024-07-15"
    idx = target_day(day)
    issue = issue_time_utc(pd.DatetimeIndex([pd.Timestamp(day)]), SETUP)[0]
    changed = load.copy()
    changed.loc[issue - pd.Timedelta(hours=1)] += 5000
    a = load_lag_features(load, idx, SETUP)
    b = load_lag_features(changed, idx, SETUP)
    assert not a["load_dm1_last"].equals(b["load_dm1_last"])


def test_lag_features_match_manual_values(load: pd.Series) -> None:
    idx = target_day("2024-07-15")
    feats = load_lag_features(load, idx, SETUP)
    t = idx[5]
    assert feats.loc[t, "load_lag168h"] == load[t - pd.Timedelta(hours=168)]
    expected = np.mean([load[t - pd.Timedelta(hours=168 * w)] for w in range(1, 5)])
    assert feats.loc[t, "load_same_hour_mean_4w"] == pytest.approx(expected)
    d2 = load[hourly_index("2024-07-13", "2024-07-14")]
    assert feats.loc[t, "load_dm2_mean"] == pytest.approx(d2.mean())


def test_issue_time_respects_daylight_saving() -> None:
    days = pd.DatetimeIndex(["2024-03-31", "2024-04-01", "2024-10-27", "2024-10-28"])
    issue = issue_time_utc(days, SETUP)
    assert list(issue.strftime("%Y-%m-%d %H:%M")) == [
        "2024-03-30 09:00",
        "2024-03-31 08:00",
        "2024-10-26 08:00",
        "2024-10-27 09:00",
    ]


def test_short_lags_are_rejected() -> None:
    with pytest.raises(ValueError, match="leak"):
        ForecastSetup(tz=TZ, issue_hour=10, lag_hours=(24, 168), weekly_mean_weeks=4).validate()


def test_lag_feature_names_are_complete(load: pd.Series) -> None:
    feats = load_lag_features(load, target_day("2024-07-15"), SETUP)
    assert list(feats.columns) == lag_feature_names(SETUP)


def test_holiday_share_and_bridge_days() -> None:
    cal = daily_calendar([2024], WEIGHTS, 0.5, SCHOOL)
    assert cal.loc["2024-08-01", "holiday_share"] == pytest.approx(1.0)
    assert cal.loc["2024-12-26", "holiday_share"] == pytest.approx(0.7)
    assert cal.loc["2024-06-29", "holiday_share"] == pytest.approx(0.2)
    assert cal.loc["2024-05-10", "bridge_day"] == 1
    assert cal.loc["2024-05-13", "bridge_day"] == 0
    assert cal.loc["2024-12-25", "daytype"] == 2
    assert cal.loc["2024-07-20", "school_holiday_proxy"] == 1
    assert cal.loc["2024-09-20", "school_holiday_proxy"] == 0


def test_hourly_calendar_handles_dst_days() -> None:
    cal = daily_calendar([2024], WEIGHTS, 0.5, SCHOOL)
    spring = hourly_calendar(target_day("2024-03-31"), TZ, cal)
    autumn = hourly_calendar(target_day("2024-10-27"), TZ, cal)
    assert len(spring) == 23
    assert 2 not in set(spring["hour"])
    assert len(autumn) == 25
    assert (autumn["hour"] == 2).sum() == 2
    assert (spring["local_date"] == spring["local_date"].iloc[0]).all()
