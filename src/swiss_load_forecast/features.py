from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from swiss_load_forecast.calendar_features import daily_calendar, hourly_calendar
from swiss_load_forecast.config import Config

H = pd.Timedelta(hours=1)

CALENDAR_FEATURES = [
    "hour",
    "weekday",
    "month",
    "day_of_year",
    "doy_sin",
    "doy_cos",
    "is_weekend",
    "holiday_share",
    "is_holiday",
    "bridge_day",
    "day_before_holiday",
    "day_after_holiday",
    "holiday_share_prev",
    "holiday_share_next",
    "school_holiday_proxy",
    "daytype",
]

LAGGED_WEATHER_FEATURES = [
    "temp_lag48h",
    "radiation_lag48h",
    "temp_dm2_mean",
    "hdd_dm2",
    "cdd_dm2",
    "temp_dm1_morning_mean",
    "temp_dm1_last",
]

ORACLE_WEATHER_FEATURES = [
    "temperature_c",
    "radiation_wm2",
    "temp_d_mean",
    "hdd_d",
    "cdd_d",
    "temp_mean_24h",
]


@dataclass(frozen=True)
class ForecastSetup:
    tz: str
    issue_hour: int
    lag_hours: tuple[int, ...]
    weekly_mean_weeks: int

    @property
    def max_horizon_hours(self) -> int:
        return 24 + (24 - self.issue_hour) + 1

    def validate(self) -> None:
        if not 0 < self.issue_hour <= 23:
            raise ValueError("issue_hour must be between 1 and 23")
        too_short = [k for k in self.lag_hours if k <= self.max_horizon_hours]
        if too_short:
            raise ValueError(
                f"Lags {too_short} h would leak: the longest horizon is "
                f"{self.max_horizon_hours} h after the issue time"
            )


def setup_from_config(cfg: Config) -> ForecastSetup:
    f = cfg.section("forecast")
    setup = ForecastSetup(
        tz=cfg.timezone,
        issue_hour=int(f["issue_hour_local"]),
        lag_hours=tuple(int(x) for x in f["lag_hours"]),
        weekly_mean_weeks=int(f["weekly_mean_weeks"]),
    )
    setup.validate()
    return setup


def lag_feature_names(setup: ForecastSetup) -> list[str]:
    return [
        *[f"load_lag{k}h" for k in setup.lag_hours],
        f"load_same_hour_mean_{setup.weekly_mean_weeks}w",
        "load_dm2_mean",
        "load_dm1_morning_mean",
        "load_dm1_last",
        "load_dm1_morning_ratio_w",
    ]


def issue_time_utc(local_dates: pd.DatetimeIndex, setup: ForecastSetup) -> pd.DatetimeIndex:
    issue_local = (local_dates - pd.Timedelta(days=1)) + pd.Timedelta(hours=setup.issue_hour)
    return pd.DatetimeIndex(issue_local.tz_localize(setup.tz).tz_convert("UTC"))


def _local_frame(series: pd.Series, tz: str) -> pd.DataFrame:
    local = pd.DatetimeIndex(series.index).tz_convert(tz)
    return pd.DataFrame(
        {
            "value": series.to_numpy(),
            "local_date": local.tz_localize(None).normalize(),
            "local_hour": local.hour,
        },
        index=series.index,
    )


def _daily_reference_features(series: pd.Series, setup: ForecastSetup, prefix: str) -> pd.DataFrame:
    lf = _local_frame(series, setup.tz)
    daily_mean = lf.groupby("local_date")["value"].mean()
    morning = lf[lf["local_hour"] < setup.issue_hour]
    morning_mean = morning.groupby("local_date")["value"].mean()
    last = lf[lf["local_hour"] == setup.issue_hour - 1].groupby("local_date")["value"].last()
    one = pd.Timedelta(days=1)
    out = pd.DataFrame(
        {
            f"{prefix}_dm2_mean": daily_mean.shift(freq=2 * one),
            f"{prefix}_dm1_morning_mean": morning_mean.shift(freq=one),
            f"{prefix}_dm1_last": last.shift(freq=one),
            f"{prefix}_dm8_morning_mean": morning_mean.shift(freq=8 * one),
        }
    )
    out.index.name = "local_date"
    return out


def load_lag_features(
    load: pd.Series, index: pd.DatetimeIndex, setup: ForecastSetup
) -> pd.DataFrame:
    full = load.asfreq("h")
    out = pd.DataFrame(index=index)
    for k in setup.lag_hours:
        out[f"load_lag{k}h"] = full.reindex(index - k * H).to_numpy()
    weekly = [
        full.reindex(index - 168 * w * H).to_numpy() for w in range(1, setup.weekly_mean_weeks + 1)
    ]
    out[f"load_same_hour_mean_{setup.weekly_mean_weeks}w"] = (
        pd.DataFrame(np.column_stack(weekly)).mean(axis=1).to_numpy()
    )
    daily = _daily_reference_features(full, setup, "load")
    local_date = pd.DatetimeIndex(index.tz_convert(setup.tz).tz_localize(None).normalize())
    joined = daily.reindex(local_date)
    out["load_dm2_mean"] = joined["load_dm2_mean"].to_numpy()
    out["load_dm1_morning_mean"] = joined["load_dm1_morning_mean"].to_numpy()
    out["load_dm1_last"] = joined["load_dm1_last"].to_numpy()
    out["load_dm1_morning_ratio_w"] = (
        joined["load_dm1_morning_mean"] / joined["load_dm8_morning_mean"]
    ).to_numpy()
    return out


def lagged_weather_features(
    weather: pd.DataFrame,
    index: pd.DatetimeIndex,
    setup: ForecastSetup,
    heat_base: float,
    cool_base: float,
) -> pd.DataFrame:
    temp = weather["temperature_c"].asfreq("h")
    rad = weather["radiation_wm2"].asfreq("h")
    out = pd.DataFrame(index=index)
    out["temp_lag48h"] = temp.reindex(index - 48 * H).to_numpy()
    out["radiation_lag48h"] = rad.reindex(index - 48 * H).to_numpy()
    daily = _daily_reference_features(temp, setup, "temp")
    local_date = pd.DatetimeIndex(index.tz_convert(setup.tz).tz_localize(None).normalize())
    joined = daily.reindex(local_date)
    out["temp_dm2_mean"] = joined["temp_dm2_mean"].to_numpy()
    out["hdd_dm2"] = np.maximum(heat_base - out["temp_dm2_mean"], 0.0)
    out["cdd_dm2"] = np.maximum(out["temp_dm2_mean"] - cool_base, 0.0)
    out["temp_dm1_morning_mean"] = joined["temp_dm1_morning_mean"].to_numpy()
    out["temp_dm1_last"] = joined["temp_dm1_last"].to_numpy()
    return out


def oracle_weather_features(
    weather: pd.DataFrame, index: pd.DatetimeIndex, tz: str, heat_base: float, cool_base: float
) -> pd.DataFrame:
    w = weather.asfreq("h")
    out = pd.DataFrame(index=index)
    out["temperature_c"] = w["temperature_c"].reindex(index).to_numpy()
    out["radiation_wm2"] = w["radiation_wm2"].reindex(index).to_numpy()
    lf = _local_frame(w["temperature_c"], tz)
    day_mean = lf.groupby("local_date")["value"].mean()
    local_date = pd.DatetimeIndex(index.tz_convert(tz).tz_localize(None).normalize())
    out["temp_d_mean"] = day_mean.reindex(local_date).to_numpy()
    out["hdd_d"] = np.maximum(heat_base - out["temp_d_mean"], 0.0)
    out["cdd_d"] = np.maximum(out["temp_d_mean"] - cool_base, 0.0)
    out["temp_mean_24h"] = (
        w["temperature_c"].rolling(24, min_periods=18).mean().reindex(index).to_numpy()
    )
    return out


def build_feature_frame(load: pd.Series, weather: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    setup = setup_from_config(cfg)
    split = cfg.section("split")
    start = pd.Timestamp(split["start"], tz=setup.tz).tz_convert("UTC")
    end = pd.Timestamp(split["end"], tz=setup.tz).tz_convert("UTC")
    index = pd.date_range(start, end, freq="h", inclusive="left", name="utc_start")
    cal_cfg = cfg.section("calendar")
    daily = daily_calendar(
        range(index[0].year, index[-1].year + 1),
        cfg.canton_weights(),
        float(cal_cfg["holiday_threshold"]),
        list(cal_cfg["school_holiday_proxy"]),
    )
    w = cfg.section("weather")
    heat, cool = float(w["heating_base_c"]), float(w["cooling_base_c"])
    frame = pd.concat(
        [
            hourly_calendar(index, setup.tz, daily),
            load_lag_features(load, index, setup),
            lagged_weather_features(weather, index, setup, heat, cool),
            oracle_weather_features(weather, index, setup.tz, heat, cool),
        ],
        axis=1,
    )
    frame["holiday_name"] = daily["holiday_name"].reindex(frame["local_date"]).to_numpy()
    frame["target"] = load.reindex(index).to_numpy()
    frame["issue_time_utc"] = issue_time_utc(pd.DatetimeIndex(frame["local_date"]), setup)
    return frame


def feature_sets(setup: ForecastSetup) -> dict[str, list[str]]:
    lags = lag_feature_names(setup)
    return {
        "calendar": CALENDAR_FEATURES,
        "no_weather": CALENDAR_FEATURES + lags,
        "lagged_weather": CALENDAR_FEATURES + lags + LAGGED_WEATHER_FEATURES,
        "oracle_weather": CALENDAR_FEATURES
        + lags
        + LAGGED_WEATHER_FEATURES
        + ORACLE_WEATHER_FEATURES,
    }
