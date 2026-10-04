PER_DAY <- 96L
PER_WEEK <- 7L * PER_DAY
ANOMALY_TYPES <- c("spike", "drop", "level_shift", "flatline")
IF_FEATURES <- c("load_mw", "diff_1", "abs_diff_1", "roll_std_1h", "identical_run",
                 "dev_ref_weeks", "dev_local_median", "hour_sin", "hour_cos", "is_weekend")

residual_scores <- function(y, lo, hi, min_width = 1) {
  width <- pmax(hi - lo, min_width)
  pmax(pmax(lo - y, y - hi), 0) / width
}

threshold_from_scores <- function(scores, rate) {
  stats::quantile(scores, 1 - rate, na.rm = TRUE, names = FALSE)
}

run_lengths <- function(x) {
  r <- rle(x)
  rep(r$lengths, r$lengths)
}

flatline_flags <- function(load, min_run) {
  key <- ifelse(is.na(load), NA_character_, format(load, digits = 15))
  run_lengths(key) >= min_run & !is.na(load)
}

if_features <- function(utc, load, tz) {
  n <- length(load)
  shift_by <- function(k) c(rep(NA_real_, k), load[seq_len(n - k)])
  ref <- apply(cbind(shift_by(PER_WEEK), shift_by(2 * PER_WEEK), shift_by(3 * PER_WEEK)), 1,
               stats::median, na.rm = TRUE)
  local_med <- stats::runmed(load, 9, endrule = "keep")
  lp <- local_parts(utc, tz)
  frac <- (lp$hour + lp$minute / 60) / 24
  diff1 <- c(NA_real_, diff(load))
  data.table::data.table(
    load_mw = load,
    diff_1 = diff1,
    abs_diff_1 = abs(diff1),
    roll_std_1h = sqrt(pmax(data.table::frollmean(load^2, 4) - data.table::frollmean(load, 4)^2, 0) * 4 / 3),
    identical_run = as.numeric(run_lengths(format(load, digits = 15))),
    dev_ref_weeks = load / ref - 1,
    dev_local_median = (load - local_med) / load,
    hour_sin = sin(2 * pi * frac),
    hour_cos = cos(2 * pi * frac),
    is_weekend = as.numeric(lp$wday >= 5)
  )
}

fill_medians <- function(x, medians) {
  for (col in names(medians)) {
    v <- x[[col]]
    v[is.na(v)] <- medians[[col]]
    data.table::set(x, j = col, value = v)
  }
  x
}

fit_isolation_forest <- function(feats, n_estimators, max_samples, rate, seed) {
  x <- data.table::copy(feats[, IF_FEATURES, with = FALSE])
  medians <- lapply(x, stats::median, na.rm = TRUE)
  x <- fill_medians(x, medians)
  model <- isotree::isolation.forest(x, ntrees = n_estimators, sample_size = max_samples,
                                     seed = seed, nthreads = 1)
  scores <- stats::predict(model, x, type = "score")
  list(model = model, medians = medians, threshold = threshold_from_scores(scores, rate))
}

score_isolation_forest <- function(det, feats) {
  x <- fill_medians(data.table::copy(feats[, IF_FEATURES, with = FALSE]), det$medians)
  stats::predict(det$model, x, type = "score")
}

inject_anomalies <- function(utc, load, spec, per_type, seed) {
  set.seed(seed)
  y <- load
  n <- length(y)
  labels <- rep("", n)
  taken <- rep(FALSE, n)
  plan <- sample(rep(ANOMALY_TYPES, each = per_type))
  events <- list()
  for (kind in plan) {
    s <- spec[[kind]]
    len <- sample(s$min_len:s$max_len, 1)
    placed <- FALSE
    for (attempt in 1:1000) {
      start <- sample(PER_DAY:(n - len - PER_DAY), 1)
      if (!any(taken[(start - PER_DAY):(start + len + PER_DAY - 1)])) {
        placed <- TRUE
        break
      }
    }
    if (!placed) stop("Could not place anomaly without overlap")
    idx <- start:(start + len - 1)
    mag <- 0
    if (kind == "flatline") {
      y[idx] <- y[start - 1]
    } else {
      mag <- stats::runif(1, s$min_mag, s$max_mag)
      sign <- switch(kind, spike = 1, drop = -1, sample(c(-1, 1), 1))
      mag <- mag * sign
      y[idx] <- y[idx] * (1 + mag)
    }
    labels[idx] <- kind
    taken[idx] <- TRUE
    events[[length(events) + 1]] <- data.table::data.table(
      type = kind, start = utc[start], end = utc[start + len - 1] + 900, intervals = len,
      relative_magnitude = mag
    )
  }
  list(load = y, labels = labels, events = data.table::rbindlist(events))
}

flag_runs <- function(utc, flags, max_gap_s, step_s) {
  t <- as.numeric(utc[flags])
  if (!length(t)) return(data.table::data.table(start = utc[0], end = utc[0]))
  run <- cumsum(c(TRUE, diff(t) > max_gap_s + step_s))
  out <- data.table::data.table(t = t, run = run)[, .(start = min(t), end = max(t) + step_s), by = run]
  data.table::data.table(start = as.POSIXct(out$start, origin = "1970-01-01", tz = "UTC"),
                         end = as.POSIXct(out$end, origin = "1970-01-01", tz = "UTC"))
}

detection_metrics <- function(utc, flags, labels, events, max_gap_s) {
  anom <- labels != ""
  tp <- sum(flags & anom)
  fp <- sum(flags & !anom)
  fn <- sum(!flags & anom)
  tnum <- as.numeric(utc)
  hit <- vapply(seq_len(nrow(events)), function(i) {
    any(flags[tnum >= as.numeric(events$start[i]) & tnum < as.numeric(events$end[i])])
  }, logical(1))
  out <- list(point_precision = if (tp + fp) tp / (tp + fp) else NA_real_,
              point_recall = if (tp + fn) tp / (tp + fn) else NA_real_,
              event_recall = mean(hit))
  for (k in ANOMALY_TYPES) out[[paste0("event_recall_", k)]] <- mean(hit[events$type == k])
  runs <- flag_runs(utc, flags, max_gap_s, 900)
  out$event_precision <- if (nrow(runs)) mean(vapply(seq_len(nrow(runs)), function(i) {
    any(anom[tnum >= as.numeric(runs$start[i]) & tnum < as.numeric(runs$end[i])])
  }, logical(1))) else NA_real_
  out$flagged_events <- nrow(runs)
  out
}

summarise_events <- function(utc, flags, score, actual, expected, calendar, tz, max_gap_s, step_s) {
  runs <- flag_runs(utc, flags, max_gap_s, step_s)
  if (!nrow(runs)) return(data.table::data.table())
  tnum <- as.numeric(utc)
  data.table::rbindlist(lapply(seq_len(nrow(runs)), function(i) {
    sel <- tnum >= as.numeric(runs$start[i]) & tnum < as.numeric(runs$end[i])
    a <- actual[sel]
    row <- list(
      start_local = format(runs$start[i], "%Y-%m-%d %H:%M", tz = tz),
      end_local = format(runs$end[i], "%Y-%m-%d %H:%M", tz = tz),
      weekday = format(runs$start[i], "%A", tz = tz),
      duration_h = (as.numeric(runs$end[i]) - as.numeric(runs$start[i])) / 3600,
      max_score = max(score[sel], na.rm = TRUE),
      mean_actual_MW = mean(a)
    )
    if (!is.null(expected)) {
      e <- expected[sel]
      row$mean_expected_MW <- mean(e)
      row$mean_deviation_MW <- mean(a - e)
      row$mean_deviation_pct <- 100 * mean((a - e) / e)
      row$abs_deviation_MWh <- sum(abs(a - e)) * step_s / 3600
    }
    days <- unique(as.Date(format(utc[sel], "%Y-%m-%d", tz = tz)))
    names <- calendar$holiday_name[match(days, calendar$local_date)]
    row$holidays <- paste(sort(unique(names[!is.na(names) & names != ""])), collapse = "; ")
    data.table::as.data.table(row)
  }))
}
