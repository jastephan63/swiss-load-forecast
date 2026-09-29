from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from swiss_load_forecast import plots
from swiss_load_forecast.anomaly import (
    IsolationForestDetector,
    detection_metrics,
    if_features,
    inject_anomalies,
    residual_scores,
    summarise_events,
    threshold_from_scores,
)
from swiss_load_forecast.cleaning import clean_load, to_hourly, write_report
from swiss_load_forecast.config import Config
from swiss_load_forecast.download import download_all
from swiss_load_forecast.evaluation import (
    Fold,
    breakdown,
    conformal_margin,
    cv_summary,
    day_category,
    fit_predict,
    interval_coverage,
    metrics_table,
    model_columns,
    rolling_origin_folds,
    run_cv,
)
from swiss_load_forecast.features import build_feature_frame, feature_sets, setup_from_config
from swiss_load_forecast.models import Forecaster, LightGBMModel, build_models
from swiss_load_forecast.weather import national_weather

log = logging.getLogger(__name__)

H1 = pd.Timedelta(hours=1)
Q15 = pd.Timedelta(minutes=15)

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


def run_evaluate(cfg: Config) -> dict[str, pd.DataFrame]:
    frame, oof, test = read_training_outputs(cfg)
    reports = cfg.paths.reports
    per_fold = metrics_table(oof, by_fold=True)
    per_fold.to_csv(reports / "metrics_cv_per_fold.csv", index=False)
    summary = cv_summary(per_fold)
    summary.to_csv(reports / "metrics_cv_summary.csv")
    test_metrics = metrics_table(test, by_fold=False).drop(columns="fold")
    test_metrics = test_metrics.sort_values("MAE_MW")
    test_metrics.to_csv(reports / "metrics_test.csv", index=False)
    models = model_columns(test)
    enriched = frame.assign(day_category=day_category(frame))
    by_hour = breakdown(test, enriched, "hour", models)
    by_weekday = breakdown(test, enriched, "weekday", models)
    by_day = breakdown(test, enriched, "day_category", models)
    by_hour.to_csv(reports / "test_error_by_hour.csv", index=False)
    by_weekday.to_csv(reports / "test_error_by_weekday.csv", index=False)
    by_day.to_csv(reports / "test_error_by_day_category.csv", index=False)
    pairs = [(float(a), float(b)) for a, b in cfg.section("models")["interval_pairs"]]
    coverage = []
    for model in ("lgbm_lagged_weather", "lgbm_oracle_weather"):
        margins = {
            (lo, hi): conformal_margin(
                oof["target"], oof[f"{model}_q{lo:g}"], oof[f"{model}_q{hi:g}"], hi - lo
            )
            for lo, hi in pairs
        }
        cv_cov = interval_coverage(oof, model, pairs).assign(period="cv")
        test_cov = interval_coverage(test, model, pairs, margins).assign(period="test")
        coverage += [cv_cov, test_cov]
    cov = pd.concat(coverage, ignore_index=True)
    cov.to_csv(reports / "interval_coverage.csv", index=False)
    importance = pd.read_csv(reports / "feature_importance_gain.csv", index_col=0)
    plots.forecast_week(test, frame, cfg, cfg.paths.figures / "01_forecast_week.png")
    plots.error_by_hour(by_hour, cfg.paths.figures / "02_error_by_hour.png")
    plots.feature_importance(importance, cfg.paths.figures / "03_feature_importance.png")
    plots.interval_coverage(test, frame, cov, cfg.paths.figures / "04_interval_coverage.png")
    write_results_markdown(cfg, summary, test_metrics, per_fold, by_day, cov)
    return {"cv": summary, "test": test_metrics, "coverage": cov}


def _md_table(df: pd.DataFrame, floatfmt: str = ".1f") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        cells = [format(v, floatfmt) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_results_markdown(
    cfg: Config,
    summary: pd.DataFrame,
    test_metrics: pd.DataFrame,
    per_fold: pd.DataFrame,
    by_day: pd.DataFrame,
    cov: pd.DataFrame,
) -> Path:
    s = summary.reset_index()
    fold_mae = per_fold.pivot_table(index="fold", columns="model", values="MAE_MW").reset_index()
    day = by_day.pivot_table(index="day_category", columns="model", values="MAPE_pct").reset_index()
    parts = [
        "# Forecast results",
        "",
        "Generated by `make evaluate`. Errors in MW of hourly average load; MAPE in percent.",
        "",
        "## Rolling-origin cross-validation (mean and std over folds)",
        "",
        _md_table(s),
        "",
        "## MAE per fold (MW)",
        "",
        _md_table(fold_mae),
        "",
        "## Held-out test period",
        "",
        _md_table(test_metrics),
        "",
        "## Test MAPE by day category (%)",
        "",
        _md_table(day, ".2f"),
        "",
        "## Prediction interval coverage",
        "",
        _md_table(cov, ".3f"),
        "",
    ]
    path = cfg.paths.reports / "results.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _example_window(events: pd.DataFrame, days: int = 7) -> tuple[pd.Timestamp, pd.Timestamp]:
    starts = pd.DatetimeIndex(events["start"]).sort_values()
    span = pd.Timedelta(days=days)
    counts = [((starts >= s) & (starts < s + span)).sum() for s in starts]
    first = starts[int(np.argmax(counts))] - pd.Timedelta(hours=12)
    return first, first + span


def run_anomalies(cfg: Config) -> dict[str, pd.DataFrame]:
    frame, oof, test = read_training_outputs(cfg)
    a = cfg.section("anomaly")
    tz = cfg.timezone
    gap = pd.Timedelta(hours=int(a["event_merge_gap_hours"]))
    top_n = int(a["top_n_real"])
    reports = cfg.paths.reports
    models = joblib.load(cfg.paths.models / "models.joblib")
    oracle = next(m for m in models if m.name == "lgbm_oracle_weather")
    lo_q, hi_q = (float(x) for x in a["residual_interval"])
    col_lo, col_hi = f"{oracle.name}_q{lo_q:g}", f"{oracle.name}_q{hi_q:g}"
    rate = float(a["residual_false_flag_rate"])
    threshold = threshold_from_scores(
        residual_scores(oof["target"], oof[col_lo], oof[col_hi]), rate
    )
    holidays_daily = frame.groupby("local_date")["holiday_name"].first()
    calendar = pd.DataFrame({"holiday_name": holidays_daily})
    preds = pd.concat([oof.drop(columns="fold"), test])
    scores = residual_scores(preds["target"], preds[col_lo], preds[col_hi])
    res_events = summarise_events(
        scores > threshold, scores, preds["target"], preds[oracle.name], calendar, tz, gap, H1
    )
    res_events = res_events.sort_values("abs_deviation_MWh", ascending=False)
    res_events.to_csv(reports / "anomalies_residual_all.csv", index=False)
    q15 = read_load_15(cfg)["load_mw"]
    feats = if_features(q15, tz)
    test_start = pd.Timestamp(cfg.section("split")["test_start"], tz=tz).tz_convert("UTC")
    iso = a["isolation_forest"]
    detector = IsolationForestDetector(
        n_estimators=int(iso["n_estimators"]),
        max_samples=int(iso["max_samples"]),
        false_flag_rate=float(iso["false_flag_rate"]),
        seed=cfg.seed,
    ).fit(feats[feats.index < test_start])
    if_score = detector.score(feats)
    if_events = summarise_events(
        if_score > detector.threshold, if_score, q15, None, calendar, tz, gap, Q15
    )
    if_events = if_events.sort_values("max_score", ascending=False)
    if_events.to_csv(reports / "anomalies_isolation_forest_all.csv", index=False)
    _, weather = read_hourly(cfg)
    test15 = q15[q15.index >= test_start]
    inj = a["injection"]
    rows = []
    example = None
    for seed in inj["seeds"]:
        corrupted, labels, events = inject_anomalies(test15, inj, int(inj["per_type"]), int(seed))
        full15 = q15.copy()
        full15.loc[corrupted.index] = corrupted.to_numpy()
        hourly = to_hourly(full15)["load_mw"]
        fr = build_feature_frame(hourly, weather, cfg)
        te = fr.loc[fr.index >= test_start]
        qs = oracle.predict_quantiles(te)
        s = residual_scores(te["target"], qs[col_lo], qs[col_hi])
        res_h = s > threshold
        res_flag = pd.Series(
            res_h.reindex(corrupted.index.floor("h")).fillna(False).to_numpy(dtype=bool),
            index=corrupted.index,
        )
        if_flag = detector.flag(if_features(full15, tz).loc[corrupted.index])
        for method, flags in (
            ("residual", res_flag),
            ("isolation_forest", if_flag),
            ("either", res_flag | if_flag),
        ):
            m = detection_metrics(flags, labels, events, gap)
            rows.append({"seed": int(seed), "method": method, **m})
        if example is None:
            s0, s1 = _example_window(events)
            win = slice(s0, s1)
            example = (
                test15.loc[win],
                corrupted.loc[win],
                res_flag.loc[win],
                if_flag.loc[win],
                events[(events["start"] >= s0) & (events["start"] < s1)],
            )
    per_seed = pd.DataFrame(rows)
    per_seed.to_csv(reports / "anomaly_injection_per_seed.csv", index=False)
    metric_cols = [c for c in per_seed.columns if c not in ("seed", "method")]
    summary = per_seed.groupby("method")[metric_cols].agg(["mean", "std"])
    summary.columns = [f"{c}_{s}" for c, s in summary.columns]
    summary.to_csv(reports / "anomaly_injection_summary.csv")
    plots.anomalies(
        preds["target"],
        res_events.head(top_n),
        if_events.head(top_n),
        tz,
        cfg.paths.figures / "05_anomalies.png",
        example,
    )
    write_anomaly_markdown(cfg, threshold, detector.threshold, summary, res_events, if_events)
    return {"injection": summary, "residual": res_events, "isolation_forest": if_events}


def write_anomaly_markdown(
    cfg: Config,
    res_threshold: float,
    if_threshold: float,
    summary: pd.DataFrame,
    res_events: pd.DataFrame,
    if_events: pd.DataFrame,
) -> Path:
    top_n = int(cfg.section("anomaly")["top_n_real"])
    means = summary[[c for c in summary.columns if c.endswith("_mean")]].copy()
    means.columns = [c.removesuffix("_mean") for c in means.columns]
    parts = [
        "# Anomaly detection results",
        "",
        "Generated by `make anomalies`.",
        "",
        f"* Residual threshold (exceedance beyond the 5 to 95% interval, in interval widths): "
        f"{res_threshold:.3f}",
        f"* Isolation Forest score threshold: {if_threshold:.4f}",
        "",
        "## Synthetic anomaly injection (mean over seeds)",
        "",
        _md_table(means.reset_index(), ".2f"),
        "",
        f"## Top {top_n} real anomalies, residual method (ranked by absolute deviation)",
        "",
        _md_table(res_events.head(top_n), ".1f"),
        "",
        f"## Top {top_n} real anomalies, Isolation Forest (ranked by score)",
        "",
        _md_table(if_events.head(top_n), ".3f"),
        "",
    ]
    path = cfg.paths.reports / "anomalies.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
