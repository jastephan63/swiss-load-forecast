from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from swiss_load_forecast.features import CALENDAR_FEATURES

LINEAR_CATEGORICAL = ["hour_daytype", "month"]
LINEAR_CALENDAR_NUMERIC = [
    "holiday_share",
    "bridge_day",
    "day_before_holiday",
    "day_after_holiday",
    "school_holiday_proxy",
    "doy_sin",
    "doy_cos",
]


class Forecaster(Protocol):
    name: str
    features: list[str]

    def fit(self, frame: pd.DataFrame) -> Forecaster: ...

    def predict(self, frame: pd.DataFrame) -> pd.Series: ...


@dataclass
class SeasonalNaive:
    name: str = "seasonal_naive"
    lag_column: str = "load_lag168h"
    features: list[str] = field(default_factory=lambda: ["load_lag168h"])

    def fit(self, frame: pd.DataFrame) -> SeasonalNaive:
        return self

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        return frame[self.lag_column].rename(self.name)


@dataclass
class LinearModel:
    name: str
    numeric: list[str]
    alpha: float = 1.0
    categorical: list[str] = field(default_factory=lambda: list(LINEAR_CATEGORICAL))
    pipeline: Pipeline | None = None

    @property
    def features(self) -> list[str]:
        return self.categorical + self.numeric

    def fit(self, frame: pd.DataFrame) -> LinearModel:
        data = frame.dropna(subset=[*self.features, "target"])
        pre = ColumnTransformer(
            [
                ("cat", OneHotEncoder(handle_unknown="ignore"), self.categorical),
                ("num", StandardScaler(), self.numeric),
            ]
        )
        self.pipeline = Pipeline([("pre", pre), ("ridge", Ridge(alpha=self.alpha))])
        self.pipeline.fit(data[self.features], data["target"])
        return self

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        if self.pipeline is None:
            raise RuntimeError("Model is not fitted")
        x = frame[self.features]
        ok = x.notna().all(axis=1)
        pred = pd.Series(np.nan, index=frame.index, name=self.name)
        if ok.any():
            pred[ok] = self.pipeline.predict(x[ok])
        return pred


@dataclass
class LightGBMModel:
    name: str
    features: list[str]
    params: dict[str, Any]
    quantiles: list[float] = field(default_factory=list)
    seed: int = 42
    point: lgb.LGBMRegressor | None = None
    quantile_models: dict[float, lgb.LGBMRegressor] = field(default_factory=dict)

    def _regressor(self, **extra: Any) -> lgb.LGBMRegressor:
        return lgb.LGBMRegressor(random_state=self.seed, **{**self.params, **extra})

    def fit(self, frame: pd.DataFrame) -> LightGBMModel:
        data = frame.dropna(subset=["target"])
        x, y = data[self.features], data["target"]
        self.point = self._regressor(objective="regression").fit(x, y)
        self.quantile_models = {
            q: self._regressor(objective="quantile", alpha=q).fit(x, y) for q in self.quantiles
        }
        return self

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        if self.point is None:
            raise RuntimeError("Model is not fitted")
        return pd.Series(
            self.point.predict(frame[self.features]), index=frame.index, name=self.name
        )

    def predict_quantiles(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self.quantile_models:
            return pd.DataFrame(index=frame.index)
        qs = sorted(self.quantile_models)
        raw = np.column_stack([self.quantile_models[q].predict(frame[self.features]) for q in qs])
        raw.sort(axis=1)
        return pd.DataFrame(raw, index=frame.index, columns=[f"{self.name}_q{q:g}" for q in qs])

    def feature_importance(self) -> pd.Series:
        if self.point is None:
            raise RuntimeError("Model is not fitted")
        booster = self.point.booster_
        gain = booster.feature_importance(importance_type="gain")
        return pd.Series(gain, index=booster.feature_name(), name=self.name).sort_values(
            ascending=False
        )


def build_models(
    sets: dict[str, list[str]],
    params: dict[str, Any],
    quantiles: list[float],
    alpha: float,
    seed: int,
) -> list[Forecaster]:
    lagged_numeric = LINEAR_CALENDAR_NUMERIC + [
        c for c in sets["lagged_weather"] if c not in CALENDAR_FEATURES
    ]
    return [
        SeasonalNaive(),
        LinearModel("linear_calendar", numeric=list(LINEAR_CALENDAR_NUMERIC), alpha=alpha),
        LinearModel("linear_lags_weather", numeric=lagged_numeric, alpha=alpha),
        LightGBMModel("lgbm_no_weather", sets["no_weather"], params, [], seed),
        LightGBMModel("lgbm_lagged_weather", sets["lagged_weather"], params, quantiles, seed),
        LightGBMModel("lgbm_oracle_weather", sets["oracle_weather"], params, quantiles, seed),
    ]
