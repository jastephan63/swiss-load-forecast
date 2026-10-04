load_location <- function(cfg, name) {
  path <- weather_path(cfg, name)
  if (!file.exists(path)) stop("Missing weather file ", path, ". Run `make r-data` first.", call. = FALSE)
  raw <- data.table::fread(path)
  utc <- as.POSIXct(raw$time, format = "%Y-%m-%dT%H:%M", tz = "UTC")
  temp <- raw$temperature_2m
  rad <- raw$shortwave_radiation
  data.table::data.table(
    utc = utc,
    temperature_c = (temp + data.table::shift(temp, -1)) / 2,
    radiation_wm2 = data.table::shift(rad, -1)
  )
}

national_weather <- function(cfg) {
  weights <- location_weights(cfg)
  frames <- lapply(names(weights), function(n) load_location(cfg, n))
  base <- frames[[1]][, .(utc)]
  temp <- Reduce(`+`, Map(function(f, w) f$temperature_c * w, frames, weights)) / sum(weights)
  rad <- Reduce(`+`, Map(function(f, w) f$radiation_wm2 * w, frames, weights)) / sum(weights)
  out <- data.table::data.table(utc = base$utc, temperature_c = temp, radiation_wm2 = rad)
  out <- out[!(is.na(temperature_c) & is.na(radiation_wm2))]
  bad_t <- !is.na(out$temperature_c) & (out$temperature_c < -35 | out$temperature_c > 45)
  bad_r <- !is.na(out$radiation_wm2) & (out$radiation_wm2 < 0 | out$radiation_wm2 > 1300)
  out[bad_t | bad_r, `:=`(temperature_c = NA_real_, radiation_wm2 = NA_real_)]
  out[, temperature_c := interpolate_short_gaps(temperature_c, 3)]
  out[, radiation_wm2 := interpolate_short_gaps(radiation_wm2, 3)]
  info <- list(
    locations_and_weights = paste(sprintf("%s %.3f", names(weights), weights), collapse = ", "),
    implausible_temperature_values = sum(bad_t),
    implausible_radiation_values = sum(bad_r),
    hours = nrow(out),
    remaining_missing_hours = sum(is.na(out$temperature_c) | is.na(out$radiation_wm2))
  )
  list(weather = out, info = info)
}
