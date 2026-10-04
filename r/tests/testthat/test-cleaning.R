local_labels <- function(day, convention) {
  utc <- seq(hourly_index(day, format(as.Date(day) + 1))[1], by = 900,
             length.out = length(target_day(day)) * 4)
  stamps <- if (convention == "end") utc + 900 else utc
  format(stamps, "%d.%m.%Y %H:%M", tz = TZ)
}

for (convention in c("end", "start")) {
  for (day in c("2024-03-31", "2024-10-27")) {
    test_that(sprintf("DST day %s maps to a regular UTC grid (%s labels)", day, convention), {
      utc <- labels_to_utc_start(local_labels(day, convention), convention, TZ)
      expect_false(anyDuplicated(utc) > 0)
      expect_true(all(diff(as.numeric(utc)) == 900))
      expect_equal(length(utc), if (day == "2024-03-31") 92 else 100)
      expect_equal(utc[1], hourly_index(day, format(as.Date(day) + 1))[1])
    })
  }
}

test_that("convention detection", {
  expect_equal(detect_convention("01.01.2024 00:15", 2024), "end")
  expect_equal(detect_convention("01.01.2025 00:00", 2025), "start")
  expect_error(detect_convention("02.01.2025 00:00", 2025))
})

test_that("both conventions give the same interval", {
  a <- labels_to_utc_start("01.07.2024 12:15", "end", TZ)
  b <- labels_to_utc_start("01.07.2024 12:00", "start", TZ)
  expect_equal(as.numeric(a), as.numeric(b))
  expect_equal(format(a, "%Y-%m-%d %H:%M", tz = "UTC"), "2024-07-01 10:00")
})

test_that("parse_year checks unit and header", {
  prefix <- "Summe endverbrauchte Energie Regelblock Schweiz"
  sheet <- list(header = paste0(prefix, "\nTotal"), unit = "MWh",
                labels = c("01.01.2024 00:15", "01.01.2024 00:30"), values = c("1", "2"))
  expect_error(parse_year(sheet, 2024, prefix, "kWh"), "unit")
  sheet$unit <- "kWh"
  sheet$header <- "Something else"
  expect_error(parse_year(sheet, 2024, prefix, "kWh"), "column B")
  sheet$header <- prefix
  sheet$values <- c("1", "n/a")
  parsed <- parse_year(sheet, 2024, prefix, "kWh")
  expect_equal(parsed$report$convention, "end")
  expect_equal(parsed$report$non_numeric, 1)
})

test_that("hourly aggregation requires four quarter hours", {
  utc <- seq(as.POSIXct("2024-01-01 00:00", tz = "UTC"), by = 900, length.out = 8)
  q <- data.table::data.table(utc = utc, load_mw = c(1, 2, 3, 4, 5, NA, 7, 8))
  h <- to_hourly(q)
  expect_equal(h$load_mw[1], 2.5)
  expect_true(is.na(h$load_mw[2]))
})

test_that("short gaps are interpolated, long gaps are kept", {
  x <- c(1, NA, 3, NA, NA, NA, NA, NA, 9)
  out <- interpolate_short_gaps(x, 4)
  expect_equal(out[2], 2)
  expect_true(all(is.na(out[4:8])))
})
