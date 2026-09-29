from __future__ import annotations

from typing import Any

import pandas as pd

from swiss_load_forecast.cleaning import DataValidationError
from swiss_load_forecast.config import Config
from swiss_load_forecast.download import weather_path

TEMP_RANGE = (-35.0, 45.0)
RADIATION_RANGE = (0.0, 1300.0)


def load_location(cfg: Config, name: str) -> pd.DataFrame:
    path = weather_path(cfg, name)
    if not path.exists():
        raise DataValidationError(f"Missing weather file {path}. Run `make data` first.")
    raw = pd.read_csv(path)
    idx = pd.DatetimeIndex(pd.to_datetime(raw["time"], format="%Y-%m-%dT%H:%M"), name="utc_start")
    frame = raw.drop(columns="time").set_index(idx.tz_localize("UTC"))
    return align_to_interval_start(frame)


def align_to_interval_start(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    out["temperature_c"] = (frame["temperature_2m"] + frame["temperature_2m"].shift(-1)) / 2.0
    out["radiation_wm2"] = frame["shortwave_radiation"].shift(-1)
    return out


def national_weather(cfg: Config) -> tuple[pd.DataFrame, dict[str, Any]]:
    weights = cfg.location_weights()
    frames = {name: load_location(cfg, name) for name in weights}
    info: dict[str, Any] = {
        "locations_and_weights": ", ".join(f"{k} {v:.3f}" for k, v in weights.items())
    }
    total = sum(weights.values())
    national = sum(frames[n] * (w / total) for n, w in weights.items())
    if not isinstance(national, pd.DataFrame):
        raise DataValidationError("No weather locations configured")
    national = national.dropna(how="all")
    missing = {n: int(f.isna().any(axis=1).sum()) for n, f in frames.items()}
    info["rows_with_missing_values_per_location"] = missing
    t_bad = ~national["temperature_c"].between(*TEMP_RANGE)
    r_bad = ~national["radiation_wm2"].between(*RADIATION_RANGE)
    info["implausible_temperature_values"] = int((t_bad & national["temperature_c"].notna()).sum())
    info["implausible_radiation_values"] = int((r_bad & national["radiation_wm2"].notna()).sum())
    national = national.mask(t_bad | r_bad)
    national = national.interpolate(limit=3, limit_area="inside")
    info["hours"] = len(national)
    info["remaining_missing_hours"] = int(national.isna().any(axis=1).sum())
    info["alignment"] = (
        "temperature averaged over the start and end of each hour; "
        "radiation (preceding-hour mean in Open-Meteo) shifted to the interval start"
    )
    return national, info
