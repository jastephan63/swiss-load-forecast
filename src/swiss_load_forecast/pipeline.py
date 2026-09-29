from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import joblib
import pandas as pd

from swiss_load_forecast.cleaning import clean_load, write_report
from swiss_load_forecast.config import Config
from swiss_load_forecast.download import download_all
from swiss_load_forecast.evaluation import Fold, fit_predict, rolling_origin_folds, run_cv
from swiss_load_forecast.features import build_feature_frame, feature_sets, setup_from_config
from swiss_load_forecast.models import Forecaster, LightGBMModel, build_models
from swiss_load_forecast.weather import national_weather

log = logging.getLogger(__name__)

LOAD_15 = "load_15min.parquet"
LOAD_H = "load_hourly.parquet"
WEATHER_H = "weather_hourly.parquet"
FEATURES = "features.parquet"
OOF = "cv_predictions.parquet"
TEST = "test_predictions.parquet"


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


def make_model_factory(cfg: Config) -> Callable[[], list[Forecaster]]:
    m = cfg.section("models")
    sets = feature_sets(setup_from_config(cfg))

    def factory() -> list[Forecaster]:
        return build_models(
            sets,
            dict(m["lightgbm"]),
            [float(q) for q in m["quantiles"]],
            float(m["linear_alpha"]),
            cfg.seed,
        )

    return factory


def dev_test_split(cfg: Config, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    test_start = pd.Timestamp(cfg.section("split")["test_start"], tz=cfg.timezone)
    cut = test_start.tz_convert("UTC")
    return frame[frame.index < cut], frame[frame.index >= cut]


def cv_folds(cfg: Config) -> list[Fold]:
    s = cfg.section("split")
    return rolling_origin_folds(
        str(s["cv_first_fold_start"]),
        int(s["cv_n_folds"]),
        int(s["cv_fold_months"]),
        cfg.timezone,
        str(s["test_start"]),
    )


def run_train(cfg: Config) -> None:
    cfg.paths.ensure()
    load, weather = read_hourly(cfg)
    frame = build_feature_frame(load, weather, cfg)
    frame.to_parquet(cfg.paths.processed / FEATURES)
    dev, test = dev_test_split(cfg, frame)
    factory = make_model_factory(cfg)
    oof = run_cv(dev, factory, cv_folds(cfg))
    oof.to_parquet(cfg.paths.processed / OOF)
    test_preds, models = fit_predict(factory(), dev, test)
    test_preds.to_parquet(cfg.paths.processed / TEST)
    joblib.dump(models, cfg.paths.models / "models.joblib")
    importance = pd.concat(
        [m.feature_importance() for m in models if isinstance(m, LightGBMModel)], axis=1
    )
    importance.to_csv(cfg.paths.reports / "feature_importance_gain.csv")
    log.info("Training done: %d CV rows, %d test rows", len(oof), len(test_preds))


def read_training_outputs(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = pd.read_parquet(cfg.paths.processed / FEATURES)
    oof = pd.read_parquet(cfg.paths.processed / OOF)
    test = pd.read_parquet(cfg.paths.processed / TEST)
    return frame, oof, test
