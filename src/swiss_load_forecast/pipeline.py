from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from swiss_load_forecast.cleaning import clean_load, write_report
from swiss_load_forecast.config import Config
from swiss_load_forecast.download import download_all
from swiss_load_forecast.weather import national_weather

log = logging.getLogger(__name__)

LOAD_15 = "load_15min.parquet"
LOAD_H = "load_hourly.parquet"
WEATHER_H = "weather_hourly.parquet"


def run_data(cfg: Config, download: bool = True, force: bool = False) -> Path:
    cfg.paths.ensure()
    if download:
        download_all(cfg, force=force)
    q15, hourly, report = clean_load(cfg)
    weather, info = national_weather(cfg)
    report.weather = info
    q15.to_parquet(cfg.paths.interim / LOAD_15)
    hourly.to_parquet(cfg.paths.processed / LOAD_H)
    weather.to_parquet(cfg.paths.processed / WEATHER_H)
    path = write_report(report, cfg.paths.reports)
    log.info("Wrote validation report to %s", path)
    return path


def read_load_15(cfg: Config) -> pd.DataFrame:
    return pd.read_parquet(cfg.paths.interim / LOAD_15)


def read_hourly(cfg: Config) -> tuple[pd.Series, pd.DataFrame]:
    load = pd.read_parquet(cfg.paths.processed / LOAD_H)["load_mw"]
    weather = pd.read_parquet(cfg.paths.processed / WEATHER_H)
    return load, weather
