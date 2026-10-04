SPEC <- list(
  spike = list(min_len = 1, max_len = 4, min_mag = 0.15, max_mag = 0.30),
  drop = list(min_len = 1, max_len = 8, min_mag = 0.20, max_mag = 0.40),
  level_shift = list(min_len = 8, max_len = 48, min_mag = 0.08, max_mag = 0.15),
  flatline = list(min_len = 8, max_len = 32)
)
utc15 <- seq(as.POSIXct("2025-07-01", tz = "UTC"), by = 900, length.out = 96 * 60)
set.seed(0)
base15 <- 6000 + stats::rnorm(length(utc15), 0, 50)

test_that("injection is reproducible and labelled", {
  a <- inject_anomalies(utc15, base15, SPEC, 3, 7)
  b <- inject_anomalies(utc15, base15, SPEC, 3, 7)
  expect_equal(a, b)
  expect_equal(nrow(a$events), 12)
  expect_setequal(unique(a$labels[a$labels != ""]), c("spike", "drop", "level_shift", "flatline"))
  expect_equal(sum(a$labels != ""), sum(a$events$intervals))
})

test_that("flatline rule flags injected flatlines", {
  a <- inject_anomalies(utc15, base15, SPEC, 3, 1)
  f <- flatline_flags(a$load, 4)
  expect_true(all(f[a$labels == "flatline"]))
  before <- c(a$labels[-1], "") == "flatline" & a$labels == ""
  expect_false(any(f[a$labels == "" & !before]))
})

test_that("flag runs merge close flags only", {
  utc <- seq(as.POSIXct("2025-01-01", tz = "UTC"), by = 3600, length.out = 48)
  flags <- rep(FALSE, 48)
  flags[c(3, 4, 6, 21)] <- TRUE
  runs <- flag_runs(utc, flags, 7200, 3600)
  expect_equal(nrow(runs), 2)
  expect_equal(runs$start[1], utc[3])
  expect_equal(runs$end[1], utc[7])
})

test_that("a perfect detector scores 1", {
  a <- inject_anomalies(utc15, base15, SPEC, 2, 3)
  m <- detection_metrics(utc15, a$labels != "", a$labels, a$events, 7200)
  expect_equal(m$point_precision, 1)
  expect_equal(m$point_recall, 1)
  expect_equal(m$event_recall, 1)
  expect_equal(m$event_precision, 1)
})

test_that("residual score is zero inside the interval", {
  expect_equal(residual_scores(c(5, 10, 0), c(4, 4, 4), c(6, 6, 6)), c(0, 2, 2))
})
