# R implementation

A complete R implementation of the same pipeline: download, validation, features, models, rolling-origin evaluation, prediction intervals and anomaly detection. It reads the same `config.yaml` and raw files as the Python version and writes its outputs to `reports/r/`.

## Stack

* R 4.3, packages pinned with `renv` (`renv.lock`)
* `data.table` for data handling, `readxl` for the Swissgrid workbooks
* `lightgbm` (point and quantile models), base `lm.fit` for the linear baselines
* `isotree` for the Isolation Forest
* `ggplot2` for figures, `testthat` for tests

Swiss cantonal holidays are implemented directly in `R/calendar.R` (Easter-based and fixed dates, including cantonal special cases such as the Glarus Näfelser Fahrt, the Geneva fast day and the Neuchâtel and Appenzell rules for 26 December). A test checks them day by day against the Python `holidays` package for 2020 to 2026: all 1,799 canton-days match.

## Run

From the repository root:

```bash
make r-install
make r-all
make r-test
```

Or with Docker:

```bash
make r-docker
```

## Agreement with the Python version

Both versions were run on the same downloaded data.

* **Cleaning:** the hourly and 15-minute series and the national weather series agree to within 1e-11 MW and 1e-13 °C (floating-point noise), including daylight-saving handling and the change of the Swissgrid timestamp convention in 2025.
* **Forecasts (test period July to December 2025):**

| Model | MAE Python (MW) | MAE R (MW) | MAPE Python | MAPE R |
|---|---:|---:|---:|---:|
| Seasonal naive | 320.2 | 320.2 | 5.17% | 5.17% |
| Linear, calendar only | 315.4 | 315.5 | 5.31% | 5.31% |
| Linear, lags + weather | 225.1 | 224.9 | 3.74% | 3.73% |
| LightGBM, no weather | 192.3 | 192.3 | 3.14% | 3.14% |
| LightGBM, weather at issue time | 183.5 | 183.5 | 2.99% | 2.99% |
| LightGBM, oracle weather | 134.1 | 134.7 | 2.21% | 2.22% |

  The LightGBM models use the same library core with deterministic settings, so they agree almost exactly. The linear model with lags differs slightly because R uses ordinary least squares and Python uses ridge regression; the oracle model differs slightly in how the 24-hour rolling temperature handles its first hours.
* **Intervals:** identical coverage (90% interval: 83.2% raw, 92.3% after conformal correction on the test period).
* **Anomalies:** the residual method finds the same real events. The synthetic injection study uses R's random number generator, so the injected anomalies differ from the Python run; recall and precision are within a few points of the Python results (see `reports/r/anomalies.md`).

## Layout

```
r/
  run.R            command-line entry point: data, train, evaluate, anomalies, all
  load.R           sources the modules in R/
  R/               config, download, cleaning, weather, calendar, features, models,
                   evaluation, anomaly, plots, pipeline
  tests/           testthat suite and an end-to-end smoke test on a synthetic workbook
  renv.lock        pinned package versions
  Dockerfile       runs the whole R pipeline
```
