test_that("cantonal holiday rules match the Python holidays package for 2020 to 2026", {
  py <- data.table::fread(testthat::test_path("fixtures", "holidays_python_2020_2026.csv"))
  py[, date := as.Date(date)]
  r <- unique(holiday_long(2020:2026)[, .(date, canton)])
  expect_equal(nrow(data.table::fsetdiff(py, r)), 0)
  expect_equal(nrow(data.table::fsetdiff(r, py)), 0)
})

test_that("holiday share and bridge days", {
  w <- c(ZH = 0.5, GE = 0.3, TI = 0.2)
  cal <- daily_calendar(2024, w, 0.5, list(list(name = "summer", start = "07-05", end = "08-15")))
  get <- function(d, col) cal[[col]][cal$local_date == as.Date(d)]
  expect_equal(get("2024-08-01", "holiday_share"), 1)
  expect_equal(get("2024-12-26", "holiday_share"), 0.7)
  expect_equal(get("2024-06-29", "holiday_share"), 0.2)
  expect_equal(get("2024-05-10", "bridge_day"), 1L)
  expect_equal(get("2024-05-13", "bridge_day"), 0L)
  expect_equal(get("2024-12-25", "daytype"), 2L)
  expect_equal(get("2024-07-20", "school_holiday_proxy"), 1L)
  expect_equal(get("2024-09-20", "school_holiday_proxy"), 0L)
})

test_that("hourly calendar handles DST days", {
  cal <- daily_calendar(2024, c(ZH = 1), 0.5, list())
  spring <- hourly_calendar(target_day("2024-03-31"), TZ, cal)
  autumn <- hourly_calendar(target_day("2024-10-27"), TZ, cal)
  expect_equal(nrow(spring), 23)
  expect_false(2 %in% spring$hour)
  expect_equal(nrow(autumn), 25)
  expect_equal(sum(autumn$hour == 2), 2)
})

test_that("easter dates", {
  expect_equal(easter_sunday(c(2021, 2024, 2025)), as.Date(c("2021-04-04", "2024-03-31", "2025-04-20")))
})
