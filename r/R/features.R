CALENDAR_FEATURES <- c("hour", "weekday", "month", "day_of_year", "doy_sin", "doy_cos",
                       "is_weekend", "holiday_share", "is_holiday", "bridge_day",
                       "day_before_holiday", "day_after_holiday", "holiday_share_prev",
                       "holiday_share_next", "school_holiday_proxy", "daytype")

LAGGED_WEATHER_FEATURES <- c("temp_lag48h", "radiation_lag48h", "temp_dm2_mean", "hdd_dm2",
                             "cdd_dm2", "temp_dm1_morning_mean", "temp_dm1_last")

ORACLE_WEATHER_FEATURES <- c("temperature_c", "radiation_wm2", "temp_d_mean", "hdd_d", "cdd_d",
                             "temp_mean_24h")

forecast_setup <- function(tz, issue_hour, lag_hours, weekly_mean_weeks) {
  setup <- list(tz = tz, issue_hour = as.integer(issue_hour), lag_hours = as.integer(lag_hours),
                weekly_mean_weeks = as.integer(weekly_mean_weeks))
  validate_setup(setup)
  setup
}

max_horizon_hours <- function(setup) 24L + (24L - setup$issue_hour) + 1L

validate_setup <- function(setup) {
  if (setup$issue_hour < 1 || setup$issue_hour > 23) stop("issue_hour must be between 1 and 23")
  short <- setup$lag_hours[setup$lag_hours <= max_horizon_hours(setup)]
  if (length(short)) {
    stop(sprintf("Lags %s h would leak: the longest horizon is %d h after the issue time",
                 paste(short, collapse = ", "), max_horizon_hours(setup)), call. = FALSE)
  }
  invisible(TRUE)
}

setup_from_config <- function(cfg) {
  f <- cfg$forecast
  forecast_setup(cfg$timezone, f$issue_hour_local, unlist(f$lag_hours), f$weekly_mean_weeks)
}

lag_feature_names <- function(setup) {
  c(sprintf("load_lag%dh", setup$lag_hours),
    sprintf("load_same_hour_mean_%dw", setup$weekly_mean_weeks),
    "load_dm2_mean", "load_dm1_morning_mean", "load_dm1_last", "load_dm1_morning_ratio_w")
}

issue_time_utc <- function(local_dates, setup) {
  stamp <- sprintf("%s %02d:00:00", format(local_dates - 1), setup$issue_hour)
  t <- as.POSIXct(stamp, tz = setup$tz)
  attr(t, "tzone") <- "UTC"
  t
}

lookup <- function(times, values, at) values[match(as.numeric(at), as.numeric(times))]

daily_reference <- function(utc, value, setup) {
  lp <- local_parts(utc, setup$tz)
  dt <- data.table::data.table(local_date = lp$date, hour = lp$hour, value = value)
  day_mean <- dt[, .(v = mean(value)), by = local_date]
  morning <- dt[hour < setup$issue_hour, .(v = mean(value)), by = local_date]
  last <- dt[hour == setup$issue_hour - 1L, .(v = value[.N]), by = local_date]
  list(day_mean = day_mean, morning = morning, last = last)
}

shifted <- function(table, dates, days) table$v[match(dates - days, table$local_date)]

load_lag_features <- function(load_utc, load_mw, index, setup) {
  out <- data.table::data.table(utc = index)
  for (k in setup$lag_hours) {
    data.table::set(out, j = sprintf("load_lag%dh", k),
                    value = lookup(load_utc, load_mw, index - 3600 * k))
  }
  weekly <- sapply(seq_len(setup$weekly_mean_weeks), function(w) {
    lookup(load_utc, load_mw, index - 3600 * 168 * w)
  })
  weekly <- matrix(weekly, nrow = length(index))
  data.table::set(out, j = sprintf("load_same_hour_mean_%dw", setup$weekly_mean_weeks),
                  value = ifelse(rowSums(!is.na(weekly)) > 0, rowMeans(weekly, na.rm = TRUE),
                                 NA_real_))
  ref <- daily_reference(load_utc, load_mw, setup)
  dates <- local_parts(index, setup$tz)$date
  out[, load_dm2_mean := shifted(ref$day_mean, dates, 2)]
  out[, load_dm1_morning_mean := shifted(ref$morning, dates, 1)]
  out[, load_dm1_last := shifted(ref$last, dates, 1)]
  out[, load_dm1_morning_ratio_w := load_dm1_morning_mean / shifted(ref$morning, dates, 8)]
  out[]
}

lagged_weather_features <- function(w_utc, temp, rad, index, setup, heat_base, cool_base) {
  out <- data.table::data.table(utc = index)
  out[, temp_lag48h := lookup(w_utc, temp, index - 3600 * 48)]
  out[, radiation_lag48h := lookup(w_utc, rad, index - 3600 * 48)]
  ref <- daily_reference(w_utc, temp, setup)
  dates <- local_parts(index, setup$tz)$date
  out[, temp_dm2_mean := shifted(ref$day_mean, dates, 2)]
  out[, hdd_dm2 := pmax(heat_base - temp_dm2_mean, 0)]
  out[, cdd_dm2 := pmax(temp_dm2_mean - cool_base, 0)]
  out[, temp_dm1_morning_mean := shifted(ref$morning, dates, 1)]
  out[, temp_dm1_last := shifted(ref$last, dates, 1)]
  out[]
}

oracle_weather_features <- function(w_utc, temp, rad, index, tz, heat_base, cool_base) {
  out <- data.table::data.table(utc = index)
  out[, temperature_c := lookup(w_utc, temp, index)]
  out[, radiation_wm2 := lookup(w_utc, rad, index)]
  lp <- local_parts(w_utc, tz)
  day_mean <- data.table::data.table(local_date = lp$date, v = temp)[, .(v = mean(v)), by = local_date]
  dates <- local_parts(index, tz)$date
  out[, temp_d_mean := shifted(day_mean, dates, 0)]
  out[, hdd_d := pmax(heat_base - temp_d_mean, 0)]
  out[, cdd_d := pmax(temp_d_mean - cool_base, 0)]
  n_ok <- data.table::frollsum(as.numeric(!is.na(temp)), 24)
  roll <- ifelse(n_ok >= 18, data.table::frollmean(temp, 24, na.rm = TRUE), NA_real_)
  out[, temp_mean_24h := lookup(w_utc, roll, index)]
  out[]
}

build_feature_frame <- function(hourly, weather, cfg) {
  setup <- setup_from_config(cfg)
  t0 <- utc_from_local(cfg, cfg$split$start)
  t1 <- utc_from_local(cfg, cfg$split$end)
  index <- seq(t0, t1 - 3600, by = 3600)
  years <- seq(as.integer(format(t0, "%Y")), as.integer(format(t1 - 1, "%Y")))
  daily <- daily_calendar(years, canton_weights(cfg), cfg$calendar$holiday_threshold,
                          cfg$calendar$school_holiday_proxy)
  heat <- cfg$weather$heating_base_c
  cool <- cfg$weather$cooling_base_c
  wgrid <- seq(min(weather$utc), max(weather$utc), by = 3600)
  temp <- lookup(weather$utc, weather$temperature_c, wgrid)
  rad <- lookup(weather$utc, weather$radiation_wm2, wgrid)
  frame <- hourly_calendar(index, setup$tz, daily)
  lags <- load_lag_features(hourly$utc, hourly$load_mw, index, setup)
  lw <- lagged_weather_features(wgrid, temp, rad, index, setup, heat, cool)
  ow <- oracle_weather_features(wgrid, temp, rad, index, setup$tz, heat, cool)
  frame <- cbind(frame, lags[, -1], lw[, -1], ow[, -1])
  frame[, target := lookup(hourly$utc, hourly$load_mw, index)]
  frame[, issue_time_utc := issue_time_utc(local_date, setup)]
  frame[]
}

feature_sets <- function(setup) {
  lags <- lag_feature_names(setup)
  list(
    calendar = CALENDAR_FEATURES,
    no_weather = c(CALENDAR_FEATURES, lags),
    lagged_weather = c(CALENDAR_FEATURES, lags, LAGGED_WEATHER_FEATURES),
    oracle_weather = c(CALENDAR_FEATURES, lags, LAGGED_WEATHER_FEATURES, ORACLE_WEATHER_FEATURES)
  )
}
