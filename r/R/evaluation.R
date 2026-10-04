rolling_origin_folds <- function(first_start, n_folds, months, tz, limit) {
  bounds <- seq(as.Date(first_start), by = sprintf("%d months", months), length.out = n_folds + 1)
  lim <- as.Date(limit)
  to_utc <- function(d) {
    t <- as.POSIXct(paste(format(d), "00:00:00"), tz = tz)
    attr(t, "tzone") <- "UTC"
    t
  }
  folds <- list()
  for (i in seq_len(n_folds)) {
    if (bounds[i] >= lim) break
    folds[[i]] <- list(fold = i, start = to_utc(bounds[i]), end = to_utc(min(bounds[i + 1], lim)))
  }
  folds
}

regression_metrics <- function(y, yhat) {
  ok <- !is.na(y) & !is.na(yhat)
  err <- yhat[ok] - y[ok]
  list(MAE_MW = mean(abs(err)), RMSE_MW = sqrt(mean(err^2)),
       MAPE_pct = 100 * mean(abs(err) / abs(y[ok])), n_hours = sum(ok))
}

fit_predict <- function(models, train, test) {
  out <- data.table::data.table(utc = test$utc, target = test$target)
  fitted <- list()
  for (m in models) {
    message(sprintf("Fitting %s on %d rows", m$name, nrow(train)))
    m <- fit_model(m, train)
    data.table::set(out, j = m$name, value = predict_model(m, test))
    q <- predict_quantiles(m, test)
    if (!is.null(q)) out <- cbind(out, q)
    fitted[[m$name]] <- m
  }
  list(preds = out, models = fitted)
}

run_cv <- function(frame, make_models, folds) {
  parts <- lapply(folds, function(f) {
    train <- frame[utc < f$start]
    test <- frame[utc >= f$start & utc < f$end]
    p <- fit_predict(make_models(), train, test)$preds
    p[, fold := f$fold]
    p
  })
  data.table::rbindlist(parts, use.names = TRUE)
}

model_columns <- function(preds) {
  setdiff(names(preds)[!grepl("_q[0-9.]+$", names(preds))], c("utc", "target", "fold"))
}

metrics_table <- function(preds, by_fold) {
  groups <- if (by_fold) split(preds, by = "fold", keep.by = TRUE) else list(test = preds)
  data.table::rbindlist(lapply(names(groups), function(g) {
    d <- groups[[g]]
    data.table::rbindlist(lapply(model_columns(preds), function(m) {
      data.table::as.data.table(c(list(fold = if (by_fold) d$fold[1] else "test", model = m),
                                  regression_metrics(d$target, d[[m]])))
    }))
  }))
}

cv_summary <- function(per_fold) {
  out <- per_fold[, .(MAE_MW_mean = mean(MAE_MW), MAE_MW_sd = stats::sd(MAE_MW),
                      RMSE_MW_mean = mean(RMSE_MW), RMSE_MW_sd = stats::sd(RMSE_MW),
                      MAPE_pct_mean = mean(MAPE_pct), MAPE_pct_sd = stats::sd(MAPE_pct)),
                  by = model]
  out[order(MAE_MW_mean)]
}

conformal_margin <- function(y, lo, hi, nominal) {
  ok <- !is.na(y) & !is.na(lo) & !is.na(hi)
  scores <- sort(pmax(lo[ok] - y[ok], y[ok] - hi[ok]))
  n <- length(scores)
  scores[min(n, ceiling((n + 1) * nominal))]
}

interval_coverage <- function(preds, model, pairs, margins = NULL) {
  y <- preds$target
  data.table::rbindlist(lapply(pairs, function(p) {
    key <- sprintf("%s-%s", format_q(p[1]), format_q(p[2]))
    lo <- preds[[sprintf("%s_q%s", model, format_q(p[1]))]]
    hi <- preds[[sprintf("%s_q%s", model, format_q(p[2]))]]
    variants <- list(raw = 0)
    if (!is.null(margins)) variants$conformal <- margins[[key]]
    data.table::rbindlist(lapply(names(variants), function(v) {
      m <- variants[[v]]
      inside <- y >= lo - m & y <= hi + m
      data.table::data.table(model = model, interval = key, nominal = p[2] - p[1], variant = v,
                             margin_MW = m, coverage = mean(inside[!is.na(y)]),
                             mean_width_MW = mean(hi - lo + 2 * m))
    }))
  }))
}

breakdown <- function(preds, frame, by, models) {
  key <- frame[[by]][match(as.numeric(preds$utc), as.numeric(frame$utc))]
  data.table::rbindlist(lapply(sort(unique(key)), function(k) {
    sel <- key == k
    data.table::rbindlist(lapply(models, function(m) {
      data.table::as.data.table(c(stats::setNames(list(k), by), list(model = m),
                                  regression_metrics(preds$target[sel], preds[[m]][sel])))
    }))
  }))
}

day_category <- function(frame) {
  data.table::fifelse(frame$is_holiday == 1, "holiday",
    data.table::fifelse(frame$bridge_day == 1, "bridge day",
      data.table::fifelse(frame$is_weekend == 1, "weekend", "normal workday")))
}
