from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from swiss_load_forecast.models import Forecaster, LightGBMModel

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fold:
    fold: int
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def rolling_origin_folds(
    first_start: str, n_folds: int, months: int, tz: str, limit: str
) -> list[Fold]:
    folds: list[Fold] = []
    start_local = pd.Timestamp(first_start, tz=tz)
    limit_utc = pd.Timestamp(limit, tz=tz).tz_convert("UTC")
    for i in range(n_folds):
        s = start_local + pd.DateOffset(months=months * i)
        e = min(s + pd.DateOffset(months=months), pd.Timestamp(limit, tz=tz))
        s_utc, e_utc = s.tz_convert("UTC"), e.tz_convert("UTC")
        if s_utc >= limit_utc:
            break
        folds.append(Fold(i + 1, s_utc, s_utc, e_utc))
    return folds


def regression_metrics(y: pd.Series, yhat: pd.Series) -> dict[str, float]:
    mask = y.notna() & yhat.notna()
    err = (yhat[mask] - y[mask]).to_numpy()
    actual = y[mask].to_numpy()
    return {
        "MAE_MW": float(np.mean(np.abs(err))),
        "RMSE_MW": float(np.sqrt(np.mean(err**2))),
        "MAPE_pct": float(100 * np.mean(np.abs(err) / np.abs(actual))),
        "n_hours": int(mask.sum()),
    }


def fit_predict(
    models: Sequence[Forecaster], train: pd.DataFrame, test: pd.DataFrame
) -> tuple[pd.DataFrame, list[Forecaster]]:
    out = pd.DataFrame(index=test.index)
    out["target"] = test["target"]
    for model in models:
        log.info("Fitting %s on %d rows", model.name, len(train))
        model.fit(train)
        out[model.name] = model.predict(test)
        if isinstance(model, LightGBMModel):
            out = out.join(model.predict_quantiles(test))
    return out, list(models)


def run_cv(
    frame: pd.DataFrame,
    make_models: Callable[[], list[Forecaster]],
    folds: Sequence[Fold],
) -> pd.DataFrame:
    parts = []
    for f in folds:
        train = frame[frame.index < f.train_end]
        test = frame[(frame.index >= f.test_start) & (frame.index < f.test_end)]
        preds, _ = fit_predict(make_models(), train, test)
        preds.insert(0, "fold", f.fold)
        parts.append(preds)
    return pd.concat(parts)


def model_columns(preds: pd.DataFrame) -> list[str]:
    return [c for c in preds.columns if c not in ("fold", "target") and "_q" not in c]


def metrics_table(preds: pd.DataFrame, by_fold: bool) -> pd.DataFrame:
    rows = []
    groups = preds.groupby("fold") if by_fold else [("test", preds)]
    for key, g in groups:
        for m in model_columns(preds):
            rows.append({"fold": key, "model": m, **regression_metrics(g["target"], g[m])})
    return pd.DataFrame(rows)


def cv_summary(per_fold: pd.DataFrame) -> pd.DataFrame:
    agg = per_fold.groupby("model")[["MAE_MW", "RMSE_MW", "MAPE_pct"]].agg(["mean", "std"])
    agg.columns = [f"{a}_{b}" for a, b in agg.columns]
    return agg.sort_values("MAE_MW_mean")


def conformal_margin(y: pd.Series, lo: pd.Series, hi: pd.Series, nominal: float) -> float:
    mask = y.notna() & lo.notna() & hi.notna()
    scores = np.maximum(lo[mask] - y[mask], y[mask] - hi[mask]).to_numpy()
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * nominal) / n)
    return float(np.quantile(scores, level, method="higher"))


def interval_coverage(
    preds: pd.DataFrame,
    model: str,
    pairs: Sequence[tuple[float, float]],
    margins: dict[tuple[float, float], float] | None = None,
) -> pd.DataFrame:
    rows = []
    y = preds["target"]
    for lo_q, hi_q in pairs:
        lo, hi = preds[f"{model}_q{lo_q:g}"], preds[f"{model}_q{hi_q:g}"]
        nominal = hi_q - lo_q
        variants = [("raw", 0.0)]
        if margins is not None:
            variants.append(("conformal", margins[(lo_q, hi_q)]))
        for label, m in variants:
            inside = (y >= lo - m) & (y <= hi + m)
            rows.append(
                {
                    "model": model,
                    "interval": f"{lo_q:g}-{hi_q:g}",
                    "nominal": nominal,
                    "variant": label,
                    "margin_MW": m,
                    "coverage": float(inside[y.notna()].mean()),
                    "mean_width_MW": float((hi - lo + 2 * m).mean()),
                }
            )
    return pd.DataFrame(rows)


def breakdown(preds: pd.DataFrame, frame: pd.DataFrame, by: str, models: list[str]) -> pd.DataFrame:
    joined = preds.join(frame[[by]] if by in frame.columns else pd.DataFrame(index=frame.index))
    rows = []
    for key, g in joined.groupby(by):
        for m in models:
            r = regression_metrics(g["target"], g[m])
            rows.append({by: key, "model": m, **r})
    return pd.DataFrame(rows)


def day_category(frame: pd.DataFrame) -> pd.Series:
    cat = np.select(
        [frame["is_holiday"] == 1, frame["bridge_day"] == 1, frame["is_weekend"] == 1],
        ["holiday", "bridge day", "weekend"],
        default="normal workday",
    )
    return pd.Series(cat, index=frame.index, name="day_category")
