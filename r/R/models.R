LINEAR_CALENDAR_NUMERIC <- c("holiday_share", "bridge_day", "day_before_holiday",
                             "day_after_holiday", "school_holiday_proxy", "doy_sin", "doy_cos")

lgbm_params <- function(p, seed) {
  list(
    learning_rate = p$learning_rate, num_leaves = p$num_leaves,
    min_data_in_leaf = p$min_child_samples, bagging_fraction = p$subsample,
    bagging_freq = p$subsample_freq, feature_fraction = p$colsample_bytree,
    lambda_l2 = p$reg_lambda, num_threads = if (is.null(p$n_jobs)) 0L else p$n_jobs,
    verbose = -1L, seed = seed, deterministic = TRUE, force_row_wise = TRUE
  )
}

new_seasonal_naive <- function() {
  list(name = "seasonal_naive", type = "naive", features = "load_lag168h")
}

new_linear <- function(name, numeric) {
  list(name = name, type = "linear", numeric = numeric,
       features = c("hour_daytype", "month", numeric))
}

new_lgbm <- function(name, features, params, quantiles, seed, quantile_params = list()) {
  list(name = name, type = "lgbm", features = features, params = params, quantiles = quantiles,
       seed = seed, quantile_params = quantile_params)
}

linear_design <- function(m, data) {
  d <- data.frame(
    hour_daytype = factor(data$hour_daytype, levels = 0:71),
    month = factor(data$month, levels = 1:12),
    as.data.frame(data)[, m$numeric, drop = FALSE]
  )
  form <- stats::as.formula(paste("~", paste(c("hour_daytype", "month", m$numeric), collapse = " + ")))
  stats::model.matrix(form, stats::model.frame(form, d, na.action = stats::na.pass))
}

fit_lgbm_once <- function(x, y, params, nrounds, extra = list()) {
  lightgbm::lgb.train(
    params = utils::modifyList(params, extra),
    data = lightgbm::lgb.Dataset(x, label = y),
    nrounds = nrounds, verbose = -1L
  )
}

fit_model <- function(m, train) {
  if (m$type == "naive") return(m)
  if (m$type == "linear") {
    x <- linear_design(m, train)
    ok <- stats::complete.cases(x) & !is.na(train$target)
    coef <- stats::lm.fit(x[ok, , drop = FALSE], train$target[ok])$coefficients
    coef[is.na(coef)] <- 0
    m$coef <- coef
    return(m)
  }
  data <- train[!is.na(target)]
  x <- as.matrix(data[, m$features, with = FALSE])
  base <- lgbm_params(m$params, m$seed)
  m$point <- fit_lgbm_once(x, data$target, base, m$params$n_estimators,
                           list(objective = "regression"))
  qp <- utils::modifyList(m$params, m$quantile_params)
  qbase <- lgbm_params(qp, m$seed)
  m$quantile_models <- lapply(m$quantiles, function(q) {
    fit_lgbm_once(x, data$target, qbase, qp$n_estimators, list(objective = "quantile", alpha = q))
  })
  m
}

predict_model <- function(m, data) {
  if (m$type == "naive") return(data[[m$features]])
  if (m$type == "linear") {
    return(as.numeric(linear_design(m, data) %*% m$coef))
  }
  predict(m$point, as.matrix(data[, m$features, with = FALSE]))
}

predict_quantiles <- function(m, data) {
  if (m$type != "lgbm" || !length(m$quantiles)) return(NULL)
  x <- as.matrix(data[, m$features, with = FALSE])
  raw <- sapply(m$quantile_models, function(b) predict(b, x))
  raw <- matrix(raw, nrow = nrow(x))
  raw <- t(apply(raw, 1, sort))
  if (nrow(x) == 1) raw <- matrix(raw, nrow = 1)
  out <- data.table::as.data.table(raw)
  data.table::setnames(out, sprintf("%s_q%s", m$name, format_q(m$quantiles)))
  out
}

format_q <- function(q) sub("0+$", "", sprintf("%.2f", q))

feature_importance <- function(m) {
  imp <- lightgbm::lgb.importance(m$point)
  stats::setNames(imp$Gain, imp$Feature)
}

build_models <- function(sets, params, quantiles, seed, quantile_params = list()) {
  lagged_numeric <- c(LINEAR_CALENDAR_NUMERIC, setdiff(sets$lagged_weather, CALENDAR_FEATURES))
  list(
    new_seasonal_naive(),
    new_linear("linear_calendar", LINEAR_CALENDAR_NUMERIC),
    new_linear("linear_lags_weather", lagged_numeric),
    new_lgbm("lgbm_no_weather", sets$no_weather, params, numeric(0), seed),
    new_lgbm("lgbm_lagged_weather", sets$lagged_weather, params, quantiles, seed, quantile_params),
    new_lgbm("lgbm_oracle_weather", sets$oracle_weather, params, quantiles, seed, quantile_params)
  )
}
