from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = Path("config.yaml")


@dataclass(frozen=True)
class Paths:
    raw: Path
    interim: Path
    processed: Path
    models: Path
    reports: Path
    figures: Path

    def ensure(self) -> None:
        for p in (self.raw, self.interim, self.processed, self.models, self.reports, self.figures):
            p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    paths: Paths

    @property
    def timezone(self) -> str:
        return str(self.raw["timezone"])

    @property
    def seed(self) -> int:
        return int(self.raw["seed"])

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw[name]
        if not isinstance(value, dict):
            raise TypeError(f"Config section {name!r} must be a mapping")
        return value

    def location_weights(self) -> dict[str, float]:
        population: dict[str, float] = {
            k: float(v) for k, v in self.raw["canton_population_thousands"].items()
        }
        total = sum(population.values())
        weights: dict[str, float] = {}
        for loc in self.raw["weather"]["locations"]:
            share = sum(population[c] * float(f) for c, f in loc["cantons"].items())
            weights[str(loc["name"])] = share / total
        return weights

    def canton_weights(self) -> dict[str, float]:
        population = {k: float(v) for k, v in self.raw["canton_population_thousands"].items()}
        total = sum(population.values())
        return {k: v / total for k, v in population.items()}


def load_config(path: Path | str = DEFAULT_CONFIG, root: Path | None = None) -> Config:
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    base = root if root is not None else path.resolve().parent
    p = raw["paths"]
    paths = Paths(
        raw=base / p["raw"],
        interim=base / p["interim"],
        processed=base / p["processed"],
        models=base / p["models"],
        reports=base / p["reports"],
        figures=base / p["figures"],
    )
    return Config(raw=raw, paths=paths)
