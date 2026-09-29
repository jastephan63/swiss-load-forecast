from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swiss_load_forecast.cleaning import (
    DataValidationError,
    detect_convention,
    labels_to_utc_start,
    longest_identical_run,
    parse_year,
    to_hourly,
)

TZ = "Europe/Zurich"
PREFIX = "Summe endverbrauchte Energie Regelblock Schweiz"


def local_labels(start: str, end: str, convention: str) -> pd.Series:
    utc = pd.date_range(
        pd.Timestamp(start, tz=TZ).tz_convert("UTC"),
        pd.Timestamp(end, tz=TZ).tz_convert("UTC"),
        freq="15min",
        inclusive="left",
    )
    stamps = utc + pd.Timedelta(minutes=15) if convention == "end" else utc
    return pd.Series(stamps.tz_convert(TZ).strftime("%d.%m.%Y %H:%M"))


@pytest.mark.parametrize("convention", ["end", "start"])
@pytest.mark.parametrize("day", ["2024-03-31", "2024-10-27"])
def test_dst_days_map_to_regular_utc_grid(convention: str, day: str) -> None:
    nxt = str((pd.Timestamp(day) + pd.Timedelta(days=1)).date())
    labels = local_labels(day, nxt, convention)
    utc = labels_to_utc_start(labels, convention, TZ)
    assert utc.is_unique
    assert (utc[1:] - utc[:-1] == pd.Timedelta(minutes=15)).all()
    assert utc[0] == pd.Timestamp(day, tz=TZ).tz_convert("UTC")
    assert len(utc) == (92 if day.endswith("03-31") else 100)


def test_convention_detection() -> None:
    assert detect_convention("01.01.2024 00:15", 2024) == "end"
    assert detect_convention("01.01.2025 00:00", 2025) == "start"
    with pytest.raises(DataValidationError):
        detect_convention("02.01.2025 00:00", 2025)


def test_both_conventions_give_the_same_interval() -> None:
    end = labels_to_utc_start(pd.Series(["01.07.2024 12:15"]), "end", TZ)
    start = labels_to_utc_start(pd.Series(["01.07.2024 12:00"]), "start", TZ)
    assert end[0] == start[0] == pd.Timestamp("2024-07-01 10:00", tz="UTC")


def _rows(labels: list[str], values: list[object]) -> list[list[object]]:
    return [[lab, v] for lab, v in zip(labels, values, strict=True)]


def test_parse_year_checks_unit_and_header() -> None:
    labels = ["01.01.2024 00:15", "01.01.2024 00:30"]
    data = _rows(labels, [1.0, 2.0])
    with pytest.raises(DataValidationError, match="unit"):
        parse_year(["", f"{PREFIX}\nTotal"], ["Zeitstempel", "MWh"], data, 2024, PREFIX, "kWh")
    with pytest.raises(DataValidationError, match="column B"):
        parse_year(["", "Something else"], ["Zeitstempel", "kWh"], data, 2024, PREFIX, "kWh")
    frame, report = parse_year(
        ["", f"{PREFIX}\nTotal"], ["Zeitstempel", "kWh"], data, 2024, PREFIX, "kWh"
    )
    assert report.convention == "end"
    assert list(frame["energy_kwh"]) == [1.0, 2.0]


def test_parse_year_counts_non_numeric_values() -> None:
    data = _rows(["01.01.2024 00:15", "01.01.2024 00:30"], [1.0, "n/a"])
    _, report = parse_year(["", PREFIX], ["Zeitstempel", "kWh"], data, 2024, PREFIX, "kWh")
    assert report.non_numeric == 1


def test_to_hourly_requires_four_quarters() -> None:
    idx = pd.date_range("2024-01-01", periods=8, freq="15min", tz="UTC")
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, np.nan, 7.0, 8.0], index=idx)
    hourly = to_hourly(s)
    assert hourly["load_mw"].iloc[0] == pytest.approx(2.5)
    assert np.isnan(hourly["load_mw"].iloc[1])


def test_longest_identical_run() -> None:
    assert longest_identical_run(pd.Series([1.0, 1.0, 2.0, 2.0, 2.0, 3.0])) == 3
    assert longest_identical_run(pd.Series([], dtype=float)) == 0
