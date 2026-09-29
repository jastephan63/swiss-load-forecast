from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from openpyxl import Workbook

from swiss_load_forecast.config import load_config
from swiss_load_forecast.pipeline import run_anomalies, run_data, run_evaluate, run_train

ROOT = Path(__file__).resolve().parents[1]
TZ = "Europe/Zurich"
PREFIX = "Summe endverbrauchte Energie Regelblock Schweiz"


def synthetic_load(utc: pd.DatetimeIndex) -> np.ndarray:
    local = utc.tz_convert(TZ)
    hour = local.hour + local.minute / 60
    daily = 900 * np.sin(2 * np.pi * (hour - 6) / 24)
    weekend = np.where(local.weekday >= 5, -700, 0)
    rng = np.random.default_rng(3)
    return 6500 + daily + weekend + rng.normal(0, 60, len(utc))


def write_swissgrid(path: Path) -> None:
    utc = pd.date_range(
        pd.Timestamp("2024-01-01", tz=TZ).tz_convert("UTC"),
        pd.Timestamp("2024-04-15", tz=TZ).tz_convert("UTC"),
        freq="15min",
        inclusive="left",
    )
    labels = (utc + pd.Timedelta(minutes=15)).tz_convert(TZ).strftime("%d.%m.%Y %H:%M")
    kwh = synthetic_load(utc) * 1000 / 4
    wb = Workbook()
    ws = wb.active
    ws.title = "Zeitreihen0h15"
    ws.append(["", f"{PREFIX}\nTotal energy consumed by end users"])
    ws.append(["Zeitstempel", "kWh"])
    for lab, v in zip(labels, kwh, strict=True):
        ws.append([lab, float(v)])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_weather(path: Path) -> None:
    idx = pd.date_range("2023-12-01", "2024-04-20", freq="h")
    rng = np.random.default_rng(5)
    frame = pd.DataFrame(
        {
            "time": idx.strftime("%Y-%m-%dT%H:%M"),
            "temperature_2m": 5
            + 5 * np.sin(2 * np.pi * idx.hour / 24)
            + rng.normal(0, 1, len(idx)),
            "shortwave_radiation": np.clip(400 * np.sin(np.pi * (idx.hour - 6) / 12), 0, None),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


@pytest.fixture
def small_project(tmp_path: Path) -> Path:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["swissgrid"]["years"] = [2024]
    cfg["split"] = {
        "start": "2024-01-01",
        "test_start": "2024-03-18",
        "end": "2024-04-15",
        "cv_first_fold_start": "2024-02-19",
        "cv_fold_months": 1,
        "cv_n_folds": 1,
    }
    cfg["weather"]["locations"] = [
        {"name": "Zurich", "latitude": 47.4, "longitude": 8.5, "cantons": {"ZH": 1.0}},
        {"name": "Geneva", "latitude": 46.2, "longitude": 6.1, "cantons": {"GE": 1.0}},
    ]
    cfg["canton_population_thousands"] = {"ZH": 1605, "GE": 523}
    cfg["models"]["lightgbm"].update({"n_estimators": 20, "num_leaves": 15})
    cfg["anomaly"]["isolation_forest"].update({"n_estimators": 50, "max_samples": 256})
    cfg["anomaly"]["injection"].update({"seeds": [0], "per_type": 1})
    cfg["anomaly"]["top_n_real"] = 3
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    write_swissgrid(tmp_path / "data/raw/swissgrid/EnergieUebersichtCH-2024.xlsx")
    for name in ("Zurich", "Geneva"):
        write_weather(tmp_path / f"data/raw/weather/open_meteo_{name}.csv")
    return tmp_path


@pytest.mark.slow
def test_pipeline_runs_end_to_end(small_project: Path) -> None:
    cfg = load_config(small_project / "config.yaml")
    report = run_data(cfg, download=False)
    assert "Missing intervals before cleaning: 0" in report.read_text(encoding="utf-8")
    run_train(cfg)
    results = run_evaluate(cfg)
    test = results["test"].set_index("model")
    assert {"seasonal_naive", "linear_calendar", "lgbm_lagged_weather"} <= set(test.index)
    assert (test["MAPE_pct"] < 50).all()
    anomalies = run_anomalies(cfg)
    assert set(anomalies["injection"].index) == {
        "residual",
        "isolation_forest",
        "flatline_rule",
        "residual_or_isolation_forest",
        "all_three_combined",
    }
    for name in (
        "01_forecast_week.png",
        "02_error_by_hour.png",
        "03_feature_importance.png",
        "04_interval_coverage.png",
        "05_anomalies.png",
    ):
        assert (cfg.paths.figures / name).stat().st_size > 10_000
