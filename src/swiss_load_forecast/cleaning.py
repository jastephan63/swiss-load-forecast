from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from python_calamine import CalamineWorkbook

from swiss_load_forecast.config import Config
from swiss_load_forecast.download import swissgrid_path

log = logging.getLogger(__name__)

LabelConvention = Literal["end", "start"]
FREQ_15 = pd.Timedelta(minutes=15)
LABEL_FORMAT = "%d.%m.%Y %H:%M"


class DataValidationError(ValueError):
    pass


@dataclass
class YearReport:
    year: int
    rows: int
    first_label: str
    last_label: str
    convention: LabelConvention
    header: str
    unit: str
    non_numeric: int
    repeated_local_labels: int
    dst_days: dict[str, int] = field(default_factory=dict)


@dataclass
class ValidationReport:
    years: list[YearReport] = field(default_factory=list)
    utc_start: str = ""
    utc_end: str = ""
    expected_intervals: int = 0
    observed_intervals: int = 0
    duplicate_utc_intervals: int = 0
    missing_intervals: int = 0
    out_of_range_values: int = 0
    interpolated_intervals: int = 0
    remaining_missing_intervals: int = 0
    longest_identical_run: int = 0
    hourly_rows: int = 0
    hourly_incomplete: int = 0
    weather: dict[str, Any] = field(default_factory=dict)


def _label_to_str(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime(LABEL_FORMAT)
    if hasattr(value, "strftime"):
        return datetime(value.year, value.month, value.day).strftime(LABEL_FORMAT)
    return str(value).strip()


def read_swissgrid_sheet(path: Path, sheet: str) -> tuple[list[Any], list[Any], list[list[Any]]]:
    wb = CalamineWorkbook.from_path(str(path))
    rows = wb.get_sheet_by_name(sheet).to_python()
    if len(rows) < 3:
        raise DataValidationError(f"{path.name}: sheet {sheet!r} has no data rows")
    return rows[0], rows[1], rows[2:]


def parse_year(
    header: list[Any],
    units: list[Any],
    data: list[list[Any]],
    year: int,
    header_prefix: str,
    expected_unit: str,
) -> tuple[pd.DataFrame, YearReport]:
    head = str(header[1]).split("\n")[0].strip()
    unit = str(units[1]).strip()
    if not head.startswith(header_prefix):
        raise DataValidationError(f"{year}: column B is {head!r}, expected {header_prefix!r}")
    if unit != expected_unit:
        raise DataValidationError(f"{year}: column B unit is {unit!r}, expected {expected_unit!r}")
    labels = pd.Series([_label_to_str(r[0]) for r in data], dtype="string")
    values = pd.to_numeric(pd.Series([r[1] for r in data]), errors="coerce")
    convention = detect_convention(str(labels.iloc[0]), year)
    local = pd.to_datetime(labels, format=LABEL_FORMAT)
    day = local.dt.floor("D")
    if convention == "end":
        day = day.where(local != day, day - pd.Timedelta(days=1))
    counts = day.value_counts()
    dst_days = {str(d.date()): int(n) for d, n in counts[counts != 96].sort_index().items()}
    report = YearReport(
        year=year,
        rows=len(labels),
        first_label=str(labels.iloc[0]),
        last_label=str(labels.iloc[-1]),
        convention=convention,
        header=head,
        unit=unit,
        non_numeric=int(values.isna().sum()),
        repeated_local_labels=int(labels.duplicated().sum()),
        dst_days=dst_days,
    )
    frame = pd.DataFrame({"label": labels, "energy_kwh": values})
    return frame, report


def detect_convention(first_label: str, year: int) -> LabelConvention:
    if first_label == f"01.01.{year} 00:15":
        return "end"
    if first_label == f"01.01.{year} 00:00":
        return "start"
    raise DataValidationError(f"{year}: cannot infer timestamp convention from {first_label!r}")


def labels_to_utc_start(
    labels: pd.Series, convention: LabelConvention, tz: str
) -> pd.DatetimeIndex:
    naive = pd.DatetimeIndex(pd.to_datetime(labels, format=LABEL_FORMAT))
    first_occurrence = ~pd.Series(naive).duplicated(keep="first").to_numpy()
    local = naive.tz_localize(tz, ambiguous=first_occurrence, nonexistent="raise")
    utc = local.tz_convert("UTC")
    if convention == "end":
        utc = utc - FREQ_15
    return pd.DatetimeIndex(utc)


def longest_identical_run(values: pd.Series) -> int:
    v = values.dropna()
    if v.empty:
        return 0
    change = v.ne(v.shift()).cumsum()
    return int(change.value_counts().max())


def clean_load(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, ValidationReport]:
    sg = cfg.section("swissgrid")
    tz = cfg.timezone
    report = ValidationReport()
    parts: list[pd.DataFrame] = []
    for year in sg["years"]:
        path = swissgrid_path(cfg, int(year))
        if not path.exists():
            raise DataValidationError(f"Missing raw file {path}. Run `make data` first.")
        header, units, data = read_swissgrid_sheet(path, str(sg["sheet"]))
        frame, yrep = parse_year(
            header,
            units,
            data,
            int(year),
            str(sg["target_header_prefix"]),
            str(sg["expected_unit"]),
        )
        frame.index = labels_to_utc_start(frame["label"], yrep.convention, tz)
        report.years.append(yrep)
        parts.append(frame)
        log.info("Parsed %s: %d rows, %s-labelled", year, yrep.rows, yrep.convention)
    raw = pd.concat(parts).sort_index()
    raw.index.name = "utc_start"
    dup = raw.index.duplicated(keep="first")
    report.duplicate_utc_intervals = int(dup.sum())
    raw = raw[~dup]
    start = pd.Timestamp(cfg.section("split")["start"], tz=tz).tz_convert("UTC")
    end = pd.Timestamp(cfg.section("split")["end"], tz=tz).tz_convert("UTC")
    grid = pd.date_range(start, end, freq=FREQ_15, inclusive="left", name="utc_start")
    report.utc_start, report.utc_end = str(grid[0]), str(grid[-1] + FREQ_15)
    report.expected_intervals = len(grid)
    raw = raw.loc[(raw.index >= start) & (raw.index < end)]
    report.observed_intervals = len(raw)
    load = raw["energy_kwh"].reindex(grid) * 4.0 / 1000.0
    report.missing_intervals = int(load.isna().sum())
    lo, hi = (float(x) for x in sg["plausible_mw_range"])
    out_of_range = (load < lo) | (load > hi)
    report.out_of_range_values = int(out_of_range.sum())
    load = load.mask(out_of_range)
    report.longest_identical_run = longest_identical_run(load)
    limit = int(sg["max_interpolation_intervals"])
    was_missing = load.isna()
    filled = load.interpolate(method="time", limit=limit, limit_area="inside")
    report.interpolated_intervals = int((was_missing & filled.notna()).sum())
    report.remaining_missing_intervals = int(filled.isna().sum())
    q15 = pd.DataFrame({"load_mw": filled, "interpolated": was_missing & filled.notna()})
    hourly = to_hourly(q15["load_mw"])
    report.hourly_rows = len(hourly)
    report.hourly_incomplete = int(hourly["load_mw"].isna().sum())
    return q15, hourly, report


def to_hourly(load_15: pd.Series) -> pd.DataFrame:
    grouped = load_15.groupby(load_15.index.floor("h"))
    hourly = pd.DataFrame({"load_mw": grouped.mean(), "n_quarters": grouped.count()})
    hourly.loc[hourly["n_quarters"] < 4, "load_mw"] = np.nan
    hourly.index.name = "utc_start"
    return hourly[["load_mw"]]


def write_report(report: ValidationReport, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "data_validation.json").write_text(
        json.dumps(asdict(report), indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Data validation report",
        "",
        "Generated by `make data`. Source: Swissgrid Energieübersicht Schweiz, sheet "
        "`Zeitreihen0h15`, column B (end-user consumption, kWh per 15 min).",
        "",
        "## Per file",
        "",
        "| Year | Rows | First label | Last label | Label convention | Unit | Non-numeric | "
        "Repeated local labels | DST days (intervals) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for y in report.years:
        dst = ", ".join(f"{d} ({n})" for d, n in y.dst_days.items())
        lines.append(
            f"| {y.year} | {y.rows:,} | {y.first_label} | {y.last_label} | interval {y.convention} "
            f"| {y.unit} | {y.non_numeric} | {y.repeated_local_labels} | {dst} |"
        )
    lines += [
        "",
        "Repeated local labels are the four `02:xx` quarter hours of the autumn daylight-saving "
        "change. They map to distinct UTC intervals and are not duplicates.",
        "",
        "## Combined 15-minute series (UTC interval start)",
        "",
        f"* Period: {report.utc_start} to {report.utc_end} (UTC)",
        f"* Expected intervals: {report.expected_intervals:,}",
        f"* Observed intervals in period: {report.observed_intervals:,}",
        f"* Duplicate UTC intervals removed: {report.duplicate_utc_intervals}",
        f"* Missing intervals before cleaning: {report.missing_intervals}",
        f"* Values outside the plausible range set to missing: {report.out_of_range_values}",
        f"* Intervals filled by time interpolation (gaps up to 1 h): "
        f"{report.interpolated_intervals}",
        f"* Intervals still missing after cleaning: {report.remaining_missing_intervals}",
        f"* Longest run of identical consecutive values: {report.longest_identical_run}",
        f"* Hourly rows: {report.hourly_rows:,}, of which incomplete (set to missing): "
        f"{report.hourly_incomplete}",
    ]
    if report.weather:
        lines += ["", "## Weather (Open-Meteo archive, hourly, UTC)", ""]
        lines += [f"* {k}: {v}" for k, v in report.weather.items()]
    path = reports_dir / "data_validation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
