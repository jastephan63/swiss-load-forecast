TZ <- "Europe/Zurich"

hourly_index <- function(start, end) {
  s <- as.POSIXct(paste(start, "00:00:00"), tz = TZ)
  e <- as.POSIXct(paste(end, "00:00:00"), tz = TZ)
  attr(s, "tzone") <- "UTC"
  attr(e, "tzone") <- "UTC"
  seq(s, e - 3600, by = 3600)
}

target_day <- function(day) hourly_index(day, format(as.Date(day) + 1))

SETUP <- forecast_setup(TZ, 10, c(48, 72, 168, 336), 4)

withr_tempdir <- function() {
  d <- tempfile("slf-")
  dir.create(d)
  d
}
