synthetic_load <- function(utc) {
  lp <- local_parts(utc, TZ)
  h <- lp$hour + lp$minute / 60
  set.seed(3)
  6500 + 900 * sin(2 * pi * (h - 6) / 24) + ifelse(lp$wday >= 5, -700, 0) +
    stats::rnorm(length(utc), 0, 60)
}

write_small_project <- function(dir) {
  root_cfg <- yaml::read_yaml(file.path(testthat::test_path(), "..", "..", "..", "config.yaml"))
  cfg <- root_cfg
  cfg$swissgrid$years <- list(2024)
  cfg$split <- list(start = "2024-01-01", test_start = "2024-03-18", end = "2024-04-15",
                    cv_first_fold_start = "2024-02-19", cv_fold_months = 1, cv_n_folds = 1)
  cfg$weather$locations <- list(
    list(name = "Zurich", latitude = 47.4, longitude = 8.5, cantons = list(ZH = 1)),
    list(name = "Geneva", latitude = 46.2, longitude = 6.1, cantons = list(GE = 1))
  )
  cfg$canton_population_thousands <- list(ZH = 1605, GE = 523)
  cfg$models$lightgbm$n_estimators <- 20
  cfg$models$lightgbm$num_leaves <- 15
  cfg$anomaly$isolation_forest$n_estimators <- 50
  cfg$anomaly$isolation_forest$max_samples <- 256
  cfg$anomaly$injection$seeds <- list(0)
  cfg$anomaly$injection$per_type <- 1
  cfg$anomaly$top_n_real <- 3
  yaml::write_yaml(cfg, file.path(dir, "config.yaml"))
  start <- as.POSIXct("2024-01-01 00:00:00", tz = TZ)
  end <- as.POSIXct("2024-04-15 00:00:00", tz = TZ)
  attr(start, "tzone") <- "UTC"
  attr(end, "tzone") <- "UTC"
  utc <- seq(start, end - 900, by = 900)
  labels <- format(utc + 900, "%d.%m.%Y %H:%M", tz = TZ)
  kwh <- synthetic_load(utc) * 1000 / 4
  sheet <- data.frame(
    A = c("", "Zeitstempel", labels),
    B = c("Summe endverbrauchte Energie Regelblock Schweiz\nTotal", "kWh", format(kwh, digits = 12))
  )
  dir.create(file.path(dir, "data", "raw", "swissgrid"), recursive = TRUE)
  writexl::write_xlsx(list(Zeitreihen0h15 = sheet),
                      file.path(dir, "data", "raw", "swissgrid", "EnergieUebersichtCH-2024.xlsx"),
                      col_names = FALSE)
  dir.create(file.path(dir, "data", "raw", "weather"), recursive = TRUE)
  times <- seq(as.POSIXct("2023-12-01", tz = "UTC"), as.POSIXct("2024-04-20", tz = "UTC"), by = 3600)
  hr <- as.integer(format(times, "%H"))
  set.seed(5)
  for (name in c("Zurich", "Geneva")) {
    data.table::fwrite(data.table::data.table(
      time = format(times, "%Y-%m-%dT%H:%M"),
      temperature_2m = 5 + 5 * sin(2 * pi * hr / 24) + stats::rnorm(length(times)),
      shortwave_radiation = pmax(400 * sin(pi * (hr - 6) / 12), 0)
    ), file.path(dir, "data", "raw", "weather", sprintf("open_meteo_%s.csv", name)))
  }
  file.path(dir, "config.yaml")
}

test_that("the R pipeline runs end to end on a small synthetic sample", {
  dir <- withr_tempdir()
  cfg <- load_config(write_small_project(dir))
  report <- run_data(cfg, download = FALSE)
  expect_true(any(grepl("Missing intervals before cleaning: 0", readLines(report))))
  run_train(cfg)
  res <- run_evaluate(cfg)
  expect_true(all(c("seasonal_naive", "linear_calendar", "lgbm_lagged_weather") %in% res$test$model))
  expect_true(all(res$test$MAPE_pct < 50))
  an <- run_anomalies(cfg)
  expect_setequal(an$injection$method, c("residual", "isolation_forest", "flatline_rule",
                                         "residual_or_isolation_forest", "all_three_combined"))
  for (f in c("01_forecast_week.png", "02_error_by_hour.png", "03_feature_importance.png",
              "04_interval_coverage.png", "05_anomalies.png")) {
    expect_gt(file.size(file.path(cfg$r_paths$figures, f)), 10000)
  }
})
