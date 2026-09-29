from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from swiss_load_forecast.config import Config

log = logging.getLogger(__name__)

XLSX_MAGIC = b"PK\x03\x04"
TIMEOUT_S = 120


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadRecord:
    name: str
    url: str
    path: str
    sha256: str
    bytes: int
    retrieved_utc: str


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def swissgrid_url(cfg: Config, year: int) -> str:
    return str(cfg.section("swissgrid")["url_template"]).format(year=year)


def swissgrid_path(cfg: Config, year: int) -> Path:
    return cfg.paths.raw / "swissgrid" / f"EnergieUebersichtCH-{year}.xlsx"


def _is_valid_xlsx(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1_000_000:
        return False
    with path.open("rb") as fh:
        return fh.read(4) == XLSX_MAGIC


def download_swissgrid(cfg: Config, force: bool = False) -> list[DownloadRecord]:
    records: list[DownloadRecord] = []
    failures: list[tuple[str, Path, str]] = []
    for year in cfg.section("swissgrid")["years"]:
        url = swissgrid_url(cfg, int(year))
        target = swissgrid_path(cfg, int(year))
        target.parent.mkdir(parents=True, exist_ok=True)
        if force or not _is_valid_xlsx(target):
            log.info("Downloading %s", url)
            try:
                resp = requests.get(url, timeout=TIMEOUT_S)
                resp.raise_for_status()
            except requests.RequestException as exc:
                failures.append((url, target, str(exc)))
                continue
            tmp = target.with_suffix(".part")
            tmp.write_bytes(resp.content)
            if not _is_valid_xlsx(tmp):
                tmp.unlink(missing_ok=True)
                failures.append((url, target, "response is not an xlsx workbook"))
                continue
            tmp.replace(target)
        else:
            log.info("Using cached %s", target)
        records.append(
            DownloadRecord(
                name=f"swissgrid_{year}",
                url=url,
                path=str(target.relative_to(cfg.paths.raw.parent.parent)),
                sha256=sha256_of(target),
                bytes=target.stat().st_size,
                retrieved_utc=datetime.now(UTC).isoformat(timespec="seconds"),
            )
        )
    if failures:
        lines = [
            "Automatic download of the Swissgrid files failed.",
            "Please download these files by hand and place them at the paths shown:",
        ]
        lines += [f"  {url}\n    -> {path}\n    reason: {reason}" for url, path, reason in failures]
        lines.append(f"Landing page: {cfg.section('swissgrid')['landing_page']}")
        raise DownloadError("\n".join(lines))
    return records


def weather_path(cfg: Config, name: str) -> Path:
    return cfg.paths.raw / "weather" / f"open_meteo_{name}.csv"


def download_weather(cfg: Config, force: bool = False) -> list[DownloadRecord]:
    w = cfg.section("weather")
    records: list[DownloadRecord] = []
    for loc in w["locations"]:
        target = weather_path(cfg, str(loc["name"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        params: dict[str, str | float] = {
            "latitude": float(loc["latitude"]),
            "longitude": float(loc["longitude"]),
            "start_date": str(w["start"]),
            "end_date": str(w["end"]),
            "hourly": ",".join(w["variables"]),
            "timezone": "GMT",
        }
        url = requests.Request("GET", str(w["api_url"]), params=params).prepare().url or ""
        if force or not target.exists():
            log.info("Downloading weather for %s", loc["name"])
            try:
                resp = requests.get(url, timeout=TIMEOUT_S)
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                raise DownloadError(f"Open-Meteo request failed for {loc['name']}: {exc}") from exc
            hourly = payload.get("hourly")
            if not hourly or "time" not in hourly:
                raise DownloadError(f"Unexpected Open-Meteo payload for {loc['name']}")
            frame = pd.DataFrame(hourly)
            missing = [v for v in w["variables"] if v not in frame.columns]
            if missing:
                raise DownloadError(f"Open-Meteo did not return {missing} for {loc['name']}")
            frame.to_csv(target, index=False)
        records.append(
            DownloadRecord(
                name=f"weather_{loc['name']}",
                url=url,
                path=str(target.relative_to(cfg.paths.raw.parent.parent)),
                sha256=sha256_of(target),
                bytes=target.stat().st_size,
                retrieved_utc=datetime.now(UTC).isoformat(timespec="seconds"),
            )
        )
    return records


def write_manifest(cfg: Config, records: list[DownloadRecord]) -> Path:
    path = cfg.paths.raw / "manifest.json"
    path.write_text(json.dumps([r.__dict__ for r in records], indent=2), encoding="utf-8")
    return path


def download_all(cfg: Config, force: bool = False) -> Path:
    records = download_swissgrid(cfg, force=force) + download_weather(cfg, force=force)
    return write_manifest(cfg, records)
