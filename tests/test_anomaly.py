from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swiss_load_forecast.anomaly import (
    detection_metrics,
    flag_runs,
    flatline_flags,
    inject_anomalies,
    residual_scores,
)

SPEC = {
    "spike": {"min_len": 1, "max_len": 4, "min_mag": 0.15, "max_mag": 0.30},
    "drop": {"min_len": 1, "max_len": 8, "min_mag": 0.20, "max_mag": 0.40},
    "level_shift": {"min_len": 8, "max_len": 48, "min_mag": 0.08, "max_mag": 0.15},
    "flatline": {"min_len": 8, "max_len": 32},
}


@pytest.fixture
def load() -> pd.Series:
    idx = pd.date_range("2025-07-01", periods=96 * 60, freq="15min", tz="UTC")
    rng = np.random.default_rng(0)
    return pd.Series(6000 + rng.normal(0, 50, len(idx)), index=idx)


def test_injection_is_reproducible_and_labelled(load: pd.Series) -> None:
    a, labels_a, events_a = inject_anomalies(load, SPEC, 3, seed=7)
    b, _, events_b = inject_anomalies(load, SPEC, 3, seed=7)
    pd.testing.assert_series_equal(a, b)
    pd.testing.assert_frame_equal(events_a, events_b)
    assert len(events_a) == 12
    assert set(labels_a[labels_a != ""]) == {"spike", "drop", "level_shift", "flatline"}
    assert ((a != load) == (labels_a != "")).sum() >= (labels_a != "").sum() - 1
    assert (labels_a != "").sum() == events_a["intervals"].sum()


def test_flatline_rule_flags_injected_flatlines(load: pd.Series) -> None:
    corrupted, labels, _ = inject_anomalies(load, SPEC, 3, seed=1)
    flags = flatline_flags(corrupted, 4)
    assert flags[labels == "flatline"].all()
    before_flatline = (labels.shift(-1) == "flatline") & (labels == "")
    assert not flags[(labels == "") & ~before_flatline].any()


def test_flag_runs_merges_close_flags_only() -> None:
    idx = pd.date_range("2025-01-01", periods=48, freq="h", tz="UTC")
    flags = pd.Series(False, index=idx)
    flags.iloc[[2, 3, 5, 20]] = True
    runs = flag_runs(flags, pd.Timedelta(hours=2), pd.Timedelta(hours=1))
    assert len(runs) == 2
    assert runs.iloc[0]["start"] == idx[2]
    assert runs.iloc[0]["end"] == idx[6]


def test_detection_metrics_perfect_detector(load: pd.Series) -> None:
    _, labels, events = inject_anomalies(load, SPEC, 2, seed=3)
    m = detection_metrics(labels != "", labels, events, pd.Timedelta(hours=2))
    assert m["point_precision"] == pytest.approx(1.0)
    assert m["point_recall"] == pytest.approx(1.0)
    assert m["event_recall"] == pytest.approx(1.0)
    assert m["event_precision"] == pytest.approx(1.0)


def test_residual_score_is_zero_inside_interval() -> None:
    y = pd.Series([5.0, 10.0, 0.0])
    lo = pd.Series([4.0, 4.0, 4.0])
    hi = pd.Series([6.0, 6.0, 6.0])
    assert list(residual_scores(y, lo, hi)) == [0.0, 2.0, 2.0]
