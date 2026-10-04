idx_all <- hourly_index("2024-02-01", "2024-11-30")
set.seed(0)
load_vals <- 6000 + stats::rnorm(length(idx_all), 0, 300)
temp_vals <- stats::rnorm(length(idx_all), 10, 5)
rad_vals <- stats::runif(length(idx_all), 0, 800)

corrupt_after_issue <- function(values, day) {
  issue <- issue_time_utc(as.Date(day), SETUP)
  values[idx_all >= issue] <- 1e9
  values
}

for (day in c("2024-03-31", "2024-04-01", "2024-07-15", "2024-10-27")) {
  test_that(sprintf("load features ignore data after the issue time (%s)", day), {
    idx <- target_day(day)
    clean <- load_lag_features(idx_all, load_vals, idx, SETUP)
    leaked <- load_lag_features(idx_all, corrupt_after_issue(load_vals, day), idx, SETUP)
    expect_equal(clean, leaked)
    expect_false(anyNA(clean))
  })
  test_that(sprintf("lagged weather ignores data after the issue time (%s)", day), {
    idx <- target_day(day)
    clean <- lagged_weather_features(idx_all, temp_vals, rad_vals, idx, SETUP, 16, 22)
    leaked <- lagged_weather_features(idx_all, corrupt_after_issue(temp_vals, day),
                                      corrupt_after_issue(rad_vals, day), idx, SETUP, 16, 22)
    expect_equal(clean, leaked)
  })
}

test_that("corrupting data before the issue time changes features", {
  day <- "2024-07-15"
  idx <- target_day(day)
  issue <- issue_time_utc(as.Date(day), SETUP)
  changed <- load_vals
  changed[idx_all == issue - 3600] <- changed[idx_all == issue - 3600] + 5000
  a <- load_lag_features(idx_all, load_vals, idx, SETUP)
  b <- load_lag_features(idx_all, changed, idx, SETUP)
  expect_false(isTRUE(all.equal(a$load_dm1_last, b$load_dm1_last)))
})

test_that("lag features match manual values", {
  idx <- target_day("2024-07-15")
  f <- load_lag_features(idx_all, load_vals, idx, SETUP)
  t <- idx[6]
  expect_equal(f$load_lag168h[6], load_vals[idx_all == t - 168 * 3600])
  manual <- mean(vapply(1:4, function(w) load_vals[idx_all == t - 168 * 3600 * w], 0))
  expect_equal(f$load_same_hour_mean_4w[6], manual)
  d2 <- hourly_index("2024-07-13", "2024-07-14")
  expect_equal(f$load_dm2_mean[6], mean(load_vals[match(as.numeric(d2), as.numeric(idx_all))]))
})

test_that("issue time respects daylight saving", {
  issue <- issue_time_utc(as.Date(c("2024-03-31", "2024-04-01", "2024-10-27", "2024-10-28")), SETUP)
  expect_equal(format(issue, "%Y-%m-%d %H:%M", tz = "UTC"),
               c("2024-03-30 09:00", "2024-03-31 08:00", "2024-10-26 08:00", "2024-10-27 09:00"))
})

test_that("short lags are rejected", {
  expect_error(forecast_setup(TZ, 10, c(24, 168), 4), "leak")
})
