# Model card: Swiss day-ahead load forecaster

## Model details

* **Author:** Jake Stephan
* **Version:** 0.1.0, trained on data downloaded 29 September 2026
* **Type:** LightGBM gradient-boosted trees (point forecast with squared-error loss; separate quantile models at 5, 10, 90 and 95%) with a split-conformal interval correction
* **Main variant:** "LightGBM, weather at issue time". A variant with observed weather on the target day ("oracle") exists for benchmarking and for after-the-fact anomaly detection only.
* **Code and configuration:** this repository; all parameters in `config.yaml`

## Intended use

* **Primary:** demonstrate and benchmark day-ahead forecasting of hourly national end-user load in Switzerland, issued at 10:00 local time on the previous day, with calibrated uncertainty.
* **Secondary:** screen historical consumption data for unusual periods and data-quality problems, as a starting point for human review.
* **Users:** data scientists and analysts at utilities, grid operators and energy traders evaluating methods.
* **Out of scope:** operational procurement, balancing or grid-security decisions without further validation; forecasting for single customers, substations or other countries; any use of the oracle variant as if it were a real forecast.

## Data

* **Target:** Swissgrid "Summe endverbrauchte Energie Regelblock Schweiz", 15-minute energy converted to hourly average power (MW), 1 January 2021 to 31 December 2025.
* **Inputs:** load lags available at the issue time, calendar and population-weighted cantonal holidays, bridge days, a school-holiday proxy, and population-weighted temperature and radiation from the Open-Meteo archive (8 locations).
* **Preprocessing:** timestamp conventions detected per file (end-labelled up to 2024, start-labelled from 2025), daylight-saving transitions converted explicitly to UTC, validation of units, duplicates, gaps and range. No gaps or implausible values were found. See `reports/data_validation.md`.
* **Splits:** development data January 2021 to June 2025 (rolling-origin CV with 8 quarterly folds from July 2023); test data July to December 2025, used once.

## Evaluation

Test period July to December 2025, 4,417 hours:

| Model | MAE (MW) | RMSE (MW) | MAPE |
|---|---:|---:|---:|
| Seasonal naive (baseline) | 320 | 453 | 5.2% |
| Linear, calendar only (baseline) | 315 | 404 | 5.3% |
| Linear, lags + weather at issue time | 225 | 290 | 3.7% |
| **LightGBM, weather at issue time** | **184** | **251** | **3.0%** |
| LightGBM, oracle weather (upper bound, not deployable) | 134 | 183 | 2.2% |

* Cross-validation MAPE of the main model: 3.5 ± 0.5% over 8 folds; it beats the linear model in every fold.
* By day type (test MAPE): 2.9% normal working days, 3.2% weekends, 3.9% on the 3 holidays in the test period.
* Errors are highest around midday and lowest at night.
* **Intervals:** raw 90% quantile intervals cover 83% of test hours; after conformal widening by 109 MW (estimated on CV only) coverage is 92.3%, with a mean width of about 1,000 MW. Coverage is lowest around midday (85% at 13:00).
* Detailed tables: `reports/results.md`, `reports/metrics_*.csv`, `reports/test_error_by_*.csv`, `reports/interval_coverage.csv`.

## Anomaly detection components

* Residual method on the oracle-weather model's 5 to 95% interval, threshold set to flag 1% of CV hours.
* Isolation Forest on 15-minute features, threshold set to flag 0.2% of training quarter hours.
* Flatline rule, four or more identical consecutive quarter hours.
* In a synthetic injection study (40 anomalies, 5 seeds) the combination found 100% of injected events with 61% event precision; individually, event recall was 55% (residual), 75% (Isolation Forest) and 25% (flatline rule, which covers flatlines only). See `reports/anomalies.md`.

## Limitations

* National aggregate: much smoother than the loads a distribution utility forecasts. Accuracy will not transfer directly to smaller areas.
* Uses no numerical weather forecasts. Sudden cold spells and heatwaves produce the largest errors.
* Rare conditions (bridge days, extreme heat, holidays) have few training examples, so errors there are larger and less certain.
* Population weights, location mapping and the school-holiday proxy are approximations.
* Single test period of six months with three holidays.
* The measured quantity is net grid consumption; growing behind-the-meter solar, heat pumps and electric vehicles change load patterns over time, so the model needs regular retraining and monitoring.

## Responsible use

* Always present forecasts with their intervals, and treat hours outside normal operating conditions (holidays, extreme weather) with extra caution.
* Anomaly flags are prompts for review, not conclusions. The explanations in the README are hypotheses consistent with the data and have not been verified with the data owner.
* The oracle-weather variant must never be reported as achievable forecast accuracy.
* The model uses only aggregate, public data and contains no personal data. Applying the same methods to smart meter data would require data-protection review under the Swiss Federal Act on Data Protection (FADP), aggregation or pseudonymisation, and clear purpose limitation, because household load profiles can reveal personal behaviour.
* Monitor rolling error and interval coverage by hour and day type after deployment, and retrain when they drift.
