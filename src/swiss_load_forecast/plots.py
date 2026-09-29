from __future__ import annotations

from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from swiss_load_forecast.config import Config

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
BLUE_LIGHT = "#b7d3f6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
VIOLET = "#4a3aa7"
RED = "#e34948"

MODEL_LABELS = {
    "seasonal_naive": "Seasonal naive (same hour last week)",
    "linear_calendar": "Linear, calendar only",
    "linear_lags_weather": "Linear, lags + weather at issue time",
    "lgbm_no_weather": "LightGBM, no weather",
    "lgbm_lagged_weather": "LightGBM, weather at issue time",
    "lgbm_oracle_weather": "LightGBM, oracle weather",
}
MODEL_COLORS = {
    "seasonal_naive": ORANGE,
    "linear_lags_weather": AQUA,
    "lgbm_lagged_weather": BLUE,
    "lgbm_oracle_weather": VIOLET,
    "linear_calendar": YELLOW,
    "lgbm_no_weather": RED,
}


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.labelsize": 10,
            "axes.grid": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "font.family": "DejaVu Sans",
            "lines.linewidth": 2.0,
        }
    )


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _local_index(index: pd.Index, tz: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index).tz_convert(tz).tz_localize(None)


def typical_week_start(test: pd.DataFrame, model: str, tz: str) -> pd.Timestamp:
    local = test.copy()
    local.index = _local_index(test.index, tz)
    err = (local[model] - local["target"]).abs()
    weekly = err.groupby(local.index.to_period("W-SUN")).agg(["mean", "size"])
    weekly = weekly[weekly["size"] >= 167]
    median_week = (weekly["mean"] - weekly["mean"].median()).abs().idxmin()
    return pd.Timestamp(median_week.start_time)


def forecast_week(test: pd.DataFrame, frame: pd.DataFrame, cfg: Config, path: Path) -> None:
    _style()
    tz = cfg.timezone
    model = "lgbm_lagged_weather"
    start = typical_week_start(test, model, tz)
    local = test.copy()
    local.index = _local_index(test.index, tz)
    week = local.loc[start : start + pd.Timedelta(days=7) - pd.Timedelta(hours=1)]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.fill_between(
        week.index,
        week[f"{model}_q0.05"],
        week[f"{model}_q0.95"],
        color=BLUE_LIGHT,
        lw=0,
        label="90% prediction interval",
    )
    ax.plot(
        week.index,
        week["seasonal_naive"],
        color=ORANGE,
        lw=1.5,
        ls="--",
        label=MODEL_LABELS["seasonal_naive"],
    )
    ax.plot(week.index, week[model], color=BLUE, label=MODEL_LABELS[model])
    ax.plot(week.index, week["target"], color=INK, lw=1.5, label="Actual")
    mae = (week[model] - week["target"]).abs().mean()
    ax.set_title(
        f"Day-ahead forecast vs. actual, week of {start:%d %b %Y} "
        f"(median-error test week, MAE {mae:.0f} MW)"
    )
    ax.set_ylabel("Swiss end-user load (MW)")
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax.legend(loc="upper left", ncols=2)
    _save(fig, path)


def error_by_hour(by_hour: pd.DataFrame, path: Path) -> None:
    _style()
    models = ["seasonal_naive", "linear_lags_weather", "lgbm_lagged_weather", "lgbm_oracle_weather"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for m in models:
        d = by_hour[by_hour["model"] == m].sort_values("hour")
        ax.plot(
            d["hour"], d["MAE_MW"], color=MODEL_COLORS[m], marker="o", ms=4, label=MODEL_LABELS[m]
        )
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Hour of day (local time)")
    ax.set_ylabel("MAE (MW)")
    ax.set_ylim(bottom=0)
    ax.set_title("Test-period error by hour of day")
    ax.legend(loc="upper left")
    _save(fig, path)


PRETTY_FEATURES = {
    "load_dm1_last": "Load D-1, 09:00 to 10:00",
    "load_dm1_morning_mean": "Mean load D-1 morning",
    "load_dm2_mean": "Mean load D-2",
    "load_lag168h": "Load same hour last week",
    "load_same_hour_mean_4w": "Load same hour, 4-week mean",
    "load_lag48h": "Load 48 h earlier",
    "load_lag72h": "Load 72 h earlier",
    "load_lag336h": "Load 2 weeks earlier",
    "load_dm1_morning_ratio_w": "D-1 morning vs. week before",
    "holiday_share": "Population share on holiday",
    "holiday_share_prev": "Holiday share previous day",
    "holiday_share_next": "Holiday share next day",
    "school_holiday_proxy": "School holiday proxy",
    "day_of_year": "Day of year",
    "doy_sin": "Season (sine)",
    "doy_cos": "Season (cosine)",
    "temp_dm2_mean": "Mean temperature D-2",
    "temp_dm1_morning_mean": "Temperature D-1 morning",
    "temp_dm1_last": "Temperature D-1 at 10:00",
    "temp_lag48h": "Temperature 48 h earlier",
    "radiation_lag48h": "Radiation 48 h earlier",
    "hdd_dm2": "Heating degrees D-2",
    "cdd_dm2": "Cooling degrees D-2",
    "daytype": "Day type",
    "is_holiday": "Holiday flag",
    "bridge_day": "Bridge day",
    "is_weekend": "Weekend",
}


def feature_importance(importance: pd.DataFrame, path: Path, top: int = 15) -> None:
    _style()
    s = importance["lgbm_lagged_weather"].dropna()
    s = (100 * s / s.sum()).sort_values(ascending=False).head(top)[::-1]
    labels = [PRETTY_FEATURES.get(i, i.replace("_", " ").capitalize()) for i in s.index]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.barh(labels, s.to_numpy(), color=BLUE, height=0.6)
    for y, v in enumerate(s.to_numpy()):
        ax.text(v + 0.3, y, f"{v:.1f}%", va="center", fontsize=8, color=INK_2)
    ax.set_xlabel("Share of total split gain (%)")
    ax.set_title("LightGBM (weather at issue time): top feature importances")
    ax.grid(axis="y", visible=False)
    _save(fig, path)


def interval_coverage(
    test: pd.DataFrame, frame: pd.DataFrame, cov: pd.DataFrame, path: Path
) -> None:
    _style()
    model = "lgbm_lagged_weather"
    row = cov[
        (cov["model"] == model)
        & (cov["interval"] == "0.05-0.95")
        & (cov["period"] == "test")
        & (cov["variant"] == "conformal")
    ]
    margin = float(row["margin_MW"].iloc[0]) if len(row) else 0.0
    hour = frame.loc[test.index, "hour"]
    y, lo, hi = test["target"], test[f"{model}_q0.05"], test[f"{model}_q0.95"]
    raw = ((y >= lo) & (y <= hi)).groupby(hour).mean()
    adj = ((y >= lo - margin) & (y <= hi + margin)).groupby(hour).mean()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.axhline(0.9, color=INK_2, lw=1.2, ls="--", label="Nominal 90%")
    ax.plot(
        raw.index,
        raw.to_numpy(),
        color=ORANGE,
        marker="o",
        ms=4,
        label=f"Quantile regression (overall {raw.mean():.1%})",
    )
    ax.plot(
        adj.index,
        adj.to_numpy(),
        color=BLUE,
        marker="o",
        ms=4,
        label=f"After conformal widening by {margin:.0f} MW (overall {adj.mean():.1%})",
    )
    ax.set_xticks(range(0, 24, 2))
    ax.set_ylim(min(0.6, float(np.nanmin(raw.to_numpy())) - 0.05), 1.0)
    ax.yaxis.set_major_formatter(mpl.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Hour of day (local time)")
    ax.set_ylabel("Empirical coverage")
    ax.set_title("90% prediction interval coverage on the test period")
    ax.legend(loc="lower left")
    _save(fig, path)


def anomalies(
    actual: pd.Series,
    residual_events: pd.DataFrame,
    if_events: pd.DataFrame,
    tz: str,
    path: Path,
    example: tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.DataFrame] | None = None,
) -> None:
    _style()
    nrows = 2 if example is not None else 1
    fig, axes = plt.subplots(nrows, 1, figsize=(11, 4.0 * nrows))
    axes = np.atleast_1d(axes)
    ax = axes[0]
    daily = actual.copy()
    daily.index = _local_index(daily.index, tz)
    daily = daily.resample("D").mean()
    ax.plot(daily.index, daily.to_numpy(), color=INK_2, lw=1.2, label="Daily mean load")
    for events, color, label in (
        (residual_events, ORANGE, "Residual method (outside interval)"),
        (if_events, VIOLET, "Isolation Forest"),
    ):
        if events.empty:
            continue
        days = pd.to_datetime(events["start_local"]).dt.normalize()
        vals = daily.reindex(days).to_numpy()
        ax.scatter(
            days, vals, color=color, s=40, zorder=3, label=label, edgecolor=SURFACE, linewidth=1.5
        )
    ax.set_title("Top 10 real anomalies per method, shown on daily mean load")
    ax.set_ylabel("MW")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncols=3)
    if example is not None:
        clean, corrupted, res_flag, if_flag, events = example
        ax2 = axes[1]
        idx = _local_index(corrupted.index, tz)
        ax2.plot(idx, clean.to_numpy(), color=BLUE, lw=1.2, label="Original")
        ax2.plot(idx, corrupted.to_numpy(), color=INK, lw=1.4, label="With injected anomalies")
        ymin, ymax = float(corrupted.min()), float(corrupted.max())
        for e in events.itertuples():
            s = pd.Timestamp(e.start).tz_convert(tz).tz_localize(None)
            t = pd.Timestamp(e.end).tz_convert(tz).tz_localize(None)
            ax2.axvspan(s, t, color=YELLOW, alpha=0.25, lw=0)
            ax2.text(s, ymax, e.type.replace("_", " "), fontsize=8, color=INK_2, va="bottom")
        rf = res_flag.reindex(corrupted.index, fill_value=False).astype(bool).to_numpy()
        ff = if_flag.reindex(corrupted.index, fill_value=False).astype(bool).to_numpy()
        ax2.scatter(
            idx[rf],
            np.full(rf.sum(), ymin - 150),
            color=ORANGE,
            s=120,
            marker="|",
            linewidths=2,
            label="Residual flag",
        )
        ax2.scatter(
            idx[ff],
            np.full(ff.sum(), ymin - 300),
            color=VIOLET,
            s=120,
            marker="|",
            linewidths=2,
            label="Isolation Forest or flatline rule",
        )
        ax2.set_title("Synthetic anomaly example (shaded = injected, ticks = detections)")
        ax2.set_ylabel("MW (15-minute)")
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
        ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncols=4)
    _save(fig, path)
