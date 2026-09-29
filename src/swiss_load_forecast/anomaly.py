from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

Q = pd.Timedelta(minutes=15)
PER_DAY = 96
PER_WEEK = 7 * PER_DAY
ANOMALY_TYPES = ("spike", "drop", "level_shift", "flatline")

IF_FEATURES = [
    "load_mw",
    "diff_1",
    "abs_diff_1",
    "roll_std_1h",
    "identical_run",
    "dev_ref_weeks",
    "dev_local_median",
    "hour_sin",
    "hour_cos",
    "is_weekend",
]


def residual_scores(y: pd.Series, lo: pd.Series, hi: pd.Series) -> pd.Series:
    width = (hi - lo).clip(lower=1.0)
    excess = np.maximum(np.maximum(lo - y, y - hi), 0.0)
    return (excess / width).rename("residual_score")


def threshold_from_scores(scores: pd.Series, false_flag_rate: float) -> float:
    return float(np.quantile(scores.dropna(), 1.0 - false_flag_rate))


def if_features(load: pd.Series, tz: str) -> pd.DataFrame:
    y = load.astype(float)
    out = pd.DataFrame(index=y.index)
    out["load_mw"] = y
    out["diff_1"] = y.diff()
    out["abs_diff_1"] = out["diff_1"].abs()
    out["roll_std_1h"] = y.rolling(4, min_periods=4).std()
    run_id = y.ne(y.shift()).cumsum()
    out["identical_run"] = run_id.map(run_id.value_counts()).astype(float)
    ref = pd.concat([y.shift(PER_WEEK * k) for k in (1, 2, 3)], axis=1).median(axis=1)
    out["dev_ref_weeks"] = y / ref - 1.0
    out["dev_local_median"] = (y - y.rolling(9, center=True, min_periods=5).median()) / y
    local = pd.DatetimeIndex(y.index).tz_convert(tz)
    frac = (local.hour + local.minute / 60.0) / 24.0
    out["hour_sin"] = np.sin(2 * np.pi * frac)
    out["hour_cos"] = np.cos(2 * np.pi * frac)
    out["is_weekend"] = (local.weekday >= 5).astype(int)
    return out


@dataclass
class IsolationForestDetector:
    n_estimators: int
    max_samples: int
    false_flag_rate: float
    seed: int
    model: IsolationForest | None = None
    medians: pd.Series | None = None
    threshold: float = np.inf

    def fit(self, feats: pd.DataFrame) -> IsolationForestDetector:
        x = feats[IF_FEATURES]
        self.medians = x.median()
        x = x.fillna(self.medians)
        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            max_samples=self.max_samples,
            random_state=self.seed,
            n_jobs=-1,
        ).fit(x)
        train_scores = -self.model.score_samples(x)
        self.threshold = float(np.quantile(train_scores, 1.0 - self.false_flag_rate))
        return self

    def score(self, feats: pd.DataFrame) -> pd.Series:
        if self.model is None or self.medians is None:
            raise RuntimeError("Detector is not fitted")
        x = feats[IF_FEATURES].fillna(self.medians)
        return pd.Series(-self.model.score_samples(x), index=feats.index, name="if_score")

    def flag(self, feats: pd.DataFrame) -> pd.Series:
        return (self.score(feats) > self.threshold).rename("if_flag")


def inject_anomalies(
    load: pd.Series, spec: dict[str, Any], per_type: int, seed: int
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    y = load.to_numpy(dtype=float).copy()
    n = len(y)
    labels = np.array([""] * n, dtype=object)
    taken = np.zeros(n, dtype=bool)
    events = []
    plan = [t for t in ANOMALY_TYPES for _ in range(per_type)]
    rng.shuffle(plan)
    for kind in plan:
        s = spec[kind]
        length = int(rng.integers(int(s["min_len"]), int(s["max_len"]) + 1))
        for _ in range(1000):
            start = int(rng.integers(PER_DAY, n - length - PER_DAY))
            lo, hi = start - PER_DAY, start + length + PER_DAY
            if not taken[lo:hi].any():
                break
        else:
            raise RuntimeError("Could not place anomaly without overlap")
        sl = slice(start, start + length)
        mag = 0.0
        if kind == "flatline":
            y[sl] = y[start - 1]
        else:
            mag = float(rng.uniform(float(s["min_mag"]), float(s["max_mag"])))
            sign = {"spike": 1.0, "drop": -1.0}.get(kind, float(rng.choice([-1.0, 1.0])))
            mag *= sign
            y[sl] = y[sl] * (1.0 + mag)
        labels[sl] = kind
        taken[sl] = True
        events.append(
            {
                "type": kind,
                "start": load.index[start],
                "end": load.index[start + length - 1] + Q,
                "intervals": length,
                "relative_magnitude": mag,
            }
        )
    corrupted = pd.Series(y, index=load.index, name=load.name)
    return corrupted, pd.Series(labels, index=load.index, name="label"), pd.DataFrame(events)


def flag_runs(flags: pd.Series, max_gap: pd.Timedelta, step: pd.Timedelta) -> pd.DataFrame:
    f = flags[flags.astype(bool)]
    if f.empty:
        return pd.DataFrame(columns=["start", "end"])
    idx = pd.DatetimeIndex(f.index)
    new_run = np.r_[True, np.diff(idx.asi8) > (max_gap + step).value]
    run_id = np.cumsum(new_run)
    grp = pd.Series(idx, index=idx).groupby(run_id)
    return pd.DataFrame({"start": grp.min().to_numpy(), "end": (grp.max() + step).to_numpy()})


def detection_metrics(
    flags: pd.Series, labels: pd.Series, events: pd.DataFrame, max_gap: pd.Timedelta
) -> dict[str, float]:
    is_anom = labels != ""
    f = flags.reindex(labels.index, fill_value=False).astype(bool)
    tp = int((f & is_anom).sum())
    fp = int((f & ~is_anom).sum())
    fn = int((~f & is_anom).sum())
    out: dict[str, float] = {
        "point_precision": tp / (tp + fp) if tp + fp else np.nan,
        "point_recall": tp / (tp + fn) if tp + fn else np.nan,
    }
    hit = [bool(f.loc[e.start : e.end - Q].any()) for e in events.itertuples()]
    out["event_recall"] = float(np.mean(hit))
    for kind in ANOMALY_TYPES:
        mask = (events["type"] == kind).to_numpy()
        out[f"event_recall_{kind}"] = float(np.mean(np.array(hit)[mask])) if mask.any() else np.nan
    runs = flag_runs(f, max_gap, Q)
    if runs.empty:
        out["event_precision"] = np.nan
    else:
        overlaps = [
            bool(is_anom.loc[r.start : r.end - pd.Timedelta(seconds=1)].any())
            for r in runs.itertuples()
        ]
        out["event_precision"] = float(np.mean(overlaps))
    out["flagged_events"] = float(len(runs))
    return out


def summarise_events(
    flags: pd.Series,
    score: pd.Series,
    actual: pd.Series,
    expected: pd.Series | None,
    calendar: pd.DataFrame,
    tz: str,
    max_gap: pd.Timedelta,
    step: pd.Timedelta,
) -> pd.DataFrame:
    runs = flag_runs(flags, max_gap, step)
    rows = []
    for r in runs.itertuples():
        window = slice(r.start, r.end - pd.Timedelta(seconds=1))
        a = actual.loc[window]
        row: dict[str, Any] = {
            "start_local": pd.Timestamp(r.start).tz_convert(tz).strftime("%Y-%m-%d %H:%M"),
            "end_local": pd.Timestamp(r.end).tz_convert(tz).strftime("%Y-%m-%d %H:%M"),
            "weekday": pd.Timestamp(r.start).tz_convert(tz).day_name(),
            "duration_h": (pd.Timestamp(r.end) - pd.Timestamp(r.start)) / pd.Timedelta(hours=1),
            "max_score": float(score.loc[window].max()),
            "mean_actual_MW": float(a.mean()),
        }
        if expected is not None:
            e = expected.loc[window]
            row["mean_expected_MW"] = float(e.mean())
            row["mean_deviation_MW"] = float((a - e).mean())
            row["mean_deviation_pct"] = float(100 * ((a - e) / e).mean())
            row["abs_deviation_MWh"] = float((a - e).abs().sum() * step / pd.Timedelta(hours=1))
        local_days = pd.DatetimeIndex(a.index).tz_convert(tz).tz_localize(None).normalize().unique()
        names = calendar.reindex(local_days)["holiday_name"].dropna()
        row["holidays"] = "; ".join(sorted({n for n in names if n}))
        rows.append(row)
    return pd.DataFrame(rows)
