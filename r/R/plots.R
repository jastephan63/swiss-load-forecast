PAL <- list(surface = "#fcfcfb", ink = "#0b0b0b", ink2 = "#52514e", grid = "#e4e3df",
            blue = "#2a78d6", blue_light = "#b7d3f6", orange = "#eb6834", aqua = "#1baf7a",
            yellow = "#eda100", violet = "#4a3aa7", red = "#e34948")

MODEL_LABELS <- c(
  seasonal_naive = "Seasonal naive (same hour last week)",
  linear_calendar = "Linear, calendar only",
  linear_lags_weather = "Linear, lags + weather at issue time",
  lgbm_no_weather = "LightGBM, no weather",
  lgbm_lagged_weather = "LightGBM, weather at issue time",
  lgbm_oracle_weather = "LightGBM, oracle weather"
)
MODEL_COLORS <- c(seasonal_naive = PAL$orange, linear_lags_weather = PAL$aqua,
                  lgbm_lagged_weather = PAL$blue, lgbm_oracle_weather = PAL$violet,
                  linear_calendar = PAL$yellow, lgbm_no_weather = PAL$red)

PRETTY_FEATURES <- c(
  load_dm1_last = "Load D-1, 09:00 to 10:00", load_dm1_morning_mean = "Mean load D-1 morning",
  load_dm2_mean = "Mean load D-2", load_lag168h = "Load same hour last week",
  load_same_hour_mean_4w = "Load same hour, 4-week mean", load_lag48h = "Load 48 h earlier",
  load_lag72h = "Load 72 h earlier", load_lag336h = "Load 2 weeks earlier",
  load_dm1_morning_ratio_w = "D-1 morning vs. week before",
  holiday_share = "Population share on holiday", holiday_share_prev = "Holiday share previous day",
  holiday_share_next = "Holiday share next day", school_holiday_proxy = "School holiday proxy",
  day_of_year = "Day of year", doy_sin = "Season (sine)", doy_cos = "Season (cosine)",
  temp_dm2_mean = "Mean temperature D-2", temp_dm1_morning_mean = "Temperature D-1 morning",
  temp_dm1_last = "Temperature D-1 at 10:00", temp_lag48h = "Temperature 48 h earlier",
  radiation_lag48h = "Radiation 48 h earlier", hdd_dm2 = "Heating degrees D-2",
  cdd_dm2 = "Cooling degrees D-2", daytype = "Day type", is_holiday = "Holiday flag",
  bridge_day = "Bridge day", is_weekend = "Weekend", hour = "Hour", weekday = "Weekday",
  month = "Month"
)

pretty_feature <- function(x) ifelse(x %in% names(PRETTY_FEATURES), PRETTY_FEATURES[x], x)

theme_report <- function() {
  ggplot2::theme_minimal(base_size = 11) +
    ggplot2::theme(
      plot.background = ggplot2::element_rect(fill = PAL$surface, colour = NA),
      panel.background = ggplot2::element_rect(fill = PAL$surface, colour = NA),
      panel.grid.major = ggplot2::element_line(colour = PAL$grid, linewidth = 0.4),
      panel.grid.minor = ggplot2::element_blank(),
      plot.title = ggplot2::element_text(face = "bold", colour = PAL$ink, size = 12),
      plot.title.position = "plot",
      axis.text = ggplot2::element_text(colour = PAL$ink2),
      axis.title = ggplot2::element_text(colour = PAL$ink2),
      legend.position = "bottom", legend.title = ggplot2::element_blank(),
      legend.text = ggplot2::element_text(colour = PAL$ink)
    )
}

save_plot <- function(p, path, width = 11, height = 4.4) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  ggplot2::ggsave(path, p, width = width, height = height, dpi = 150, bg = PAL$surface)
}

local_time <- function(utc, tz) as.POSIXct(format(utc, "%Y-%m-%d %H:%M:%S", tz = tz), tz = "UTC")

typical_week_start <- function(test, model, tz) {
  lt <- local_time(test$utc, tz)
  monday <- as.Date(lt) - (as.integer(format(lt, "%u")) - 1)
  err <- abs(test[[model]] - test$target)
  wk <- data.table::data.table(monday, err)[, .(m = mean(err), n = .N), by = monday][n >= 167]
  wk$monday[which.min(abs(wk$m - stats::median(wk$m)))]
}

plot_forecast_week <- function(test, tz, path) {
  model <- "lgbm_lagged_weather"
  start <- typical_week_start(test, model, tz)
  d <- data.table::copy(test)
  d[, lt := local_time(utc, tz)]
  d <- d[as.Date(lt) >= start & as.Date(lt) < start + 7]
  d[, `:=`(lo = get(paste0(model, "_q0.05")), hi = get(paste0(model, "_q0.95")))]
  mae <- mean(abs(d[[model]] - d$target))
  long <- data.table::rbindlist(list(
    d[, .(lt, value = target, series = "Actual")],
    d[, .(lt, value = get(model), series = MODEL_LABELS[[model]])],
    d[, .(lt, value = seasonal_naive, series = MODEL_LABELS[["seasonal_naive"]])]
  ))
  cols <- stats::setNames(c(PAL$ink, PAL$blue, PAL$orange),
                          c("Actual", MODEL_LABELS[[model]], MODEL_LABELS[["seasonal_naive"]]))
  p <- ggplot2::ggplot() +
    ggplot2::geom_ribbon(data = d, ggplot2::aes(lt, ymin = lo, ymax = hi, fill = "90% prediction interval")) +
    ggplot2::geom_line(data = long, ggplot2::aes(lt, value, colour = series, linetype = series),
                       linewidth = 0.8) +
    ggplot2::scale_fill_manual(values = c("90% prediction interval" = PAL$blue_light)) +
    ggplot2::scale_colour_manual(values = cols) +
    ggplot2::scale_linetype_manual(values = stats::setNames(c("solid", "solid", "dashed"), names(cols))) +
    ggplot2::scale_x_datetime(date_breaks = "1 day", date_labels = "%a %d %b") +
    ggplot2::labs(title = sprintf("Day-ahead forecast vs. actual, week of %s (median-error test week, MAE %.0f MW)",
                                  format(start, "%d %b %Y"), mae),
                  x = NULL, y = "Swiss end-user load (MW)") +
    theme_report()
  save_plot(p, path)
}

plot_error_by_hour <- function(by_hour, path) {
  models <- c("seasonal_naive", "linear_lags_weather", "lgbm_lagged_weather", "lgbm_oracle_weather")
  d <- by_hour[model %in% models]
  d[, label := factor(MODEL_LABELS[model], levels = MODEL_LABELS[models])]
  p <- ggplot2::ggplot(d, ggplot2::aes(hour, MAE_MW, colour = label)) +
    ggplot2::geom_line(linewidth = 0.8) + ggplot2::geom_point(size = 1.6) +
    ggplot2::scale_colour_manual(values = stats::setNames(MODEL_COLORS[models], MODEL_LABELS[models])) +
    ggplot2::scale_x_continuous(breaks = seq(0, 22, 2)) +
    ggplot2::expand_limits(y = 0) +
    ggplot2::labs(title = "Test-period error by hour of day", x = "Hour of day (local time)",
                  y = "MAE (MW)") +
    ggplot2::guides(colour = ggplot2::guide_legend(nrow = 2)) +
    theme_report()
  save_plot(p, path, width = 9)
}

plot_feature_importance <- function(gain, path, top = 15) {
  share <- sort(100 * gain / sum(gain), decreasing = TRUE)[seq_len(min(top, length(gain)))]
  labels <- unname(pretty_feature(names(share)))
  d <- data.table::data.table(feature = factor(labels, levels = rev(labels)), share = share)
  p <- ggplot2::ggplot(d, ggplot2::aes(share, feature)) +
    ggplot2::geom_col(fill = PAL$blue, width = 0.6) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%", share)), hjust = -0.15, size = 3,
                       colour = PAL$ink2) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = c(0, 0.12))) +
    ggplot2::labs(title = "LightGBM (weather at issue time): top feature importances",
                  x = "Share of total gain (%)", y = NULL) +
    theme_report() + ggplot2::theme(panel.grid.major.y = ggplot2::element_blank())
  save_plot(p, path, width = 8, height = 5.2)
}

plot_interval_coverage <- function(test, frame, margin, path) {
  model <- "lgbm_lagged_weather"
  hour <- frame$hour[match(as.numeric(test$utc), as.numeric(frame$utc))]
  lo <- test[[paste0(model, "_q0.05")]]
  hi <- test[[paste0(model, "_q0.95")]]
  y <- test$target
  raw <- tapply(y >= lo & y <= hi, hour, mean)
  adj <- tapply(y >= lo - margin & y <= hi + margin, hour, mean)
  l_raw <- sprintf("Quantile regression (overall %.1f%%)", 100 * mean(y >= lo & y <= hi))
  l_adj <- sprintf("After conformal widening by %.0f MW (overall %.1f%%)", margin,
                   100 * mean(y >= lo - margin & y <= hi + margin))
  d <- data.table::data.table(hour = as.integer(names(raw)), cov = c(raw, adj),
                              series = rep(c(l_raw, l_adj), each = length(raw)))
  p <- ggplot2::ggplot(d, ggplot2::aes(hour, cov, colour = series)) +
    ggplot2::geom_hline(yintercept = 0.9, linetype = "dashed", colour = PAL$ink2) +
    ggplot2::geom_line(linewidth = 0.8) + ggplot2::geom_point(size = 1.6) +
    ggplot2::scale_colour_manual(values = stats::setNames(c(PAL$orange, PAL$blue), c(l_raw, l_adj))) +
    ggplot2::scale_y_continuous(labels = scales::percent, limits = c(min(0.6, min(d$cov) - 0.05), 1)) +
    ggplot2::scale_x_continuous(breaks = seq(0, 22, 2)) +
    ggplot2::labs(title = "90% prediction interval coverage on the test period (dashed: nominal)",
                  x = "Hour of day (local time)", y = "Empirical coverage") +
    ggplot2::guides(colour = ggplot2::guide_legend(nrow = 2)) +
    theme_report()
  save_plot(p, path, width = 9)
}

plot_anomalies <- function(hourly, res_events, if_events, tz, path) {
  d <- data.table::copy(hourly)
  d[, day := as.Date(format(utc, "%Y-%m-%d", tz = tz))]
  daily <- d[, .(load = mean(load_mw)), by = day]
  pts <- data.table::rbindlist(list(
    data.table::data.table(day = as.Date(substr(res_events$start_local, 1, 10)),
                           method = "Residual method (outside interval)"),
    data.table::data.table(day = as.Date(substr(if_events$start_local, 1, 10)),
                           method = "Isolation Forest")
  ))
  pts[, load := daily$load[match(day, daily$day)]]
  p <- ggplot2::ggplot(daily, ggplot2::aes(day, load)) +
    ggplot2::geom_line(colour = PAL$ink2, linewidth = 0.4) +
    ggplot2::geom_point(data = pts, ggplot2::aes(colour = method), size = 2.6) +
    ggplot2::scale_colour_manual(values = c("Residual method (outside interval)" = PAL$orange,
                                            "Isolation Forest" = PAL$violet)) +
    ggplot2::labs(title = "Top 10 real anomalies per method, shown on daily mean load", x = NULL,
                  y = "MW") +
    theme_report()
  save_plot(p, path, height = 4.6)
}
