DAYTYPE_WORKDAY <- 0L
DAYTYPE_SATURDAY <- 1L
DAYTYPE_SUNDAY_OR_HOLIDAY <- 2L

ALL_CANTONS <- c("AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
                 "NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH")

easter_sunday <- function(year) {
  a <- year %% 19
  b <- year %/% 100
  c <- year %% 100
  d <- b %/% 4
  e <- b %% 4
  f <- (b + 8) %/% 25
  g <- (b - f + 1) %/% 3
  h <- (19 * a + b - d - g + 15) %% 30
  i <- c %/% 4
  k <- c %% 4
  l <- (32 + 2 * e + 2 * i - h - k) %% 7
  m <- (a + 11 * h + 22 * l) %/% 451
  month <- (h + l - 7 * m + 114) %/% 31
  day <- ((h + l - 7 * m + 114) %% 31) + 1
  as.Date(sprintf("%04d-%02d-%02d", year, month, day))
}

nth_weekday <- function(year, month, wday, n) {
  first <- as.Date(sprintf("%04d-%02d-01", year, month))
  offset <- (wday - as.integer(format(first, "%u"))) %% 7
  first + offset + 7 * (n - 1)
}

holiday_rules <- function(year) {
  e <- easter_sunday(year)
  d <- function(m, day) as.Date(sprintf("%04d-%02d-%02d", year, m, day))
  naefels <- nth_weekday(year, 4, 4, 1)
  if (naefels == e - 3) naefels <- naefels + 7
  xmas_wday <- as.integer(format(d(12, 25), "%u"))
  stephen <- c("AG", "BE", "BL", "BS", "GL", "GR", "LU", "SG", "SH", "SZ", "TG", "TI", "ZH")
  if (!xmas_wday %in% c(1L, 5L)) stephen <- c(stephen, "AI", "AR", "UR")
  if (xmas_wday == 7L) stephen <- c(stephen, "NE")
  berchtold <- c("AG", "BE", "JU", "LU", "TG", "VD")
  if (format(d(1, 1), "%u") == "7") berchtold <- c(berchtold, "NE")
  list(
    list(name = "New Year's Day", date = d(1, 1), cantons = ALL_CANTONS),
    list(name = "Ascension Day", date = e + 39, cantons = ALL_CANTONS),
    list(name = "National Day", date = d(8, 1), cantons = ALL_CANTONS),
    list(name = "Christmas Day", date = d(12, 25), cantons = ALL_CANTONS),
    list(name = "Good Friday", date = e - 2, cantons = setdiff(ALL_CANTONS, c("GR", "TI", "VS"))),
    list(name = "Easter Monday", date = e + 1, cantons = c("AG", "AI", "AR", "BE", "BL", "BS", "GE",
         "GL", "GR", "JU", "LU", "SG", "SH", "SZ", "TG", "TI", "UR", "VD", "ZH")),
    list(name = "Pentecost Monday", date = e + 50, cantons = c("AG", "AI", "AR", "BE", "BL", "BS",
         "GE", "GL", "GR", "JU", "LU", "SG", "SH", "SZ", "TG", "TI", "UR", "VD", "ZH")),
    list(name = "Saint Stephen's Day", date = d(12, 26), cantons = sort(stephen)),
    list(name = "All Saints' Day", date = d(11, 1), cantons = c("AG", "AI", "GL", "JU", "LU", "NW",
         "OW", "SG", "SZ", "TI", "UR", "VS", "ZG")),
    list(name = "Corpus Christi", date = e + 60, cantons = c("AG", "AI", "JU", "LU", "NE", "NW", "OW",
         "SZ", "TI", "UR", "VS", "ZG")),
    list(name = "Assumption Day", date = d(8, 15), cantons = c("AG", "AI", "JU", "LU", "NW", "OW",
         "SZ", "TI", "UR", "VS", "ZG")),
    list(name = "Immaculate Conception", date = d(12, 8), cantons = c("AG", "AI", "LU", "NW", "OW",
         "SZ", "TI", "UR", "VS", "ZG")),
    list(name = "Labor Day", date = d(5, 1), cantons = c("AG", "BL", "BS", "JU", "NE", "SH", "TG",
         "TI", "ZH")),
    list(name = "Saint Berchtold's Day", date = d(1, 2), cantons = berchtold),
    list(name = "Saint Joseph's Day", date = d(3, 19), cantons = c("NW", "SZ", "TI", "UR", "VS")),
    list(name = "Epiphany", date = d(1, 6), cantons = c("SZ", "TI", "UR")),
    list(name = "Genevan Fast", date = nth_weekday(year, 9, 7, 1) + 4, cantons = "GE"),
    list(name = "Restoration Day", date = d(12, 31), cantons = "GE"),
    list(name = "Battle of Naefels Victory Day", date = naefels, cantons = "GL"),
    list(name = "Independence Day", date = d(6, 23), cantons = "JU"),
    list(name = "Republic Day", date = d(3, 1), cantons = "NE"),
    list(name = "Saint Nicholas of Flüe", date = d(9, 25), cantons = "OW"),
    list(name = "Saints Peter and Paul", date = d(6, 29), cantons = "TI"),
    list(name = "Prayer Monday", date = nth_weekday(year, 9, 7, 3) + 1, cantons = "VD")
  )
}

holiday_long <- function(years) {
  rows <- lapply(years, function(y) {
    data.table::rbindlist(lapply(holiday_rules(y), function(r) {
      data.table::data.table(date = r$date, name = r$name, canton = r$cantons)
    }))
  })
  unique(data.table::rbindlist(rows))
}

holiday_table <- function(years, weights) {
  days <- seq(as.Date(sprintf("%d-01-01", min(years))), as.Date(sprintf("%d-12-31", max(years))),
              by = "day")
  long <- holiday_long(years)[canton %in% names(weights)]
  long[, w := weights[canton]]
  per_day <- long[, .(holiday_share = sum(unique(data.table::data.table(canton, w))$w),
                      holiday_name = paste(sort(unique(name)), collapse = "; ")), by = date]
  out <- data.table::data.table(local_date = days)
  out <- merge(out, per_day, by.x = "local_date", by.y = "date", all.x = TRUE)
  out[is.na(holiday_share), `:=`(holiday_share = 0, holiday_name = "")]
  out[, holiday_share := pmin(round(holiday_share, 6), 1)]
  out[]
}

in_window <- function(days, start, end) days >= start & days <= end

school_holiday_proxy <- function(days, periods) {
  flag <- rep(FALSE, length(days))
  for (year in sort(unique(as.integer(format(days, "%Y"))))) {
    for (p in periods) {
      if (!is.null(p$easter_offset_start)) {
        e <- easter_sunday(year)
        flag <- flag | in_window(days, e + p$easter_offset_start, e + p$easter_offset_end)
        next
      }
      s <- as.Date(sprintf("%d-%s", year, p$start))
      t <- as.Date(sprintf("%d-%s", year, p$end))
      if (t < s) {
        flag <- flag | in_window(days, s, as.Date(sprintf("%d-%s", year + 1, p$end)))
        flag <- flag | in_window(days, as.Date(sprintf("%d-01-01", year)), t)
      } else {
        flag <- flag | in_window(days, s, t)
      }
    }
  }
  as.integer(flag)
}

daily_calendar <- function(years, weights, holiday_threshold, school_periods) {
  padded <- seq(min(years) - 1, max(years) + 1)
  cal <- holiday_table(padded, weights)
  wd <- as.integer(format(cal$local_date, "%u"))
  is_hol <- cal$holiday_share >= holiday_threshold
  off <- wd >= 6 | is_hol
  prev_off <- c(FALSE, off[-length(off)])
  next_off <- c(off[-1], FALSE)
  cal[, is_holiday := as.integer(is_hol)]
  cal[, bridge_day := as.integer(!off & prev_off & next_off)]
  cal[, day_before_holiday := as.integer(c(is_hol[-1], FALSE))]
  cal[, day_after_holiday := as.integer(c(FALSE, is_hol[-length(is_hol)]))]
  cal[, holiday_share_prev := c(0, holiday_share[-.N])]
  cal[, holiday_share_next := c(holiday_share[-1], 0)]
  cal[, school_holiday_proxy := school_holiday_proxy(local_date, school_periods)]
  cal[, daytype := ifelse(wd == 7 | is_hol, DAYTYPE_SUNDAY_OR_HOLIDAY,
                          ifelse(wd == 6, DAYTYPE_SATURDAY, DAYTYPE_WORKDAY))]
  cal[]
}

local_parts <- function(utc, tz) {
  list(
    date = as.Date(format(utc, "%Y-%m-%d", tz = tz)),
    hour = as.integer(format(utc, "%H", tz = tz)),
    minute = as.integer(format(utc, "%M", tz = tz)),
    wday = as.integer(format(utc, "%u", tz = tz)) - 1L,
    month = as.integer(format(utc, "%m", tz = tz)),
    doy = as.integer(format(utc, "%j", tz = tz))
  )
}

hourly_calendar <- function(utc, tz, daily) {
  lp <- local_parts(utc, tz)
  out <- data.table::data.table(
    utc = utc, local_date = lp$date, hour = lp$hour, weekday = lp$wday, month = lp$month,
    day_of_year = lp$doy, is_weekend = as.integer(lp$wday >= 5)
  )
  angle <- 2 * pi * (lp$doy - 1) / 365.25
  out[, `:=`(doy_sin = sin(angle), doy_cos = cos(angle))]
  idx <- match(out$local_date, daily$local_date)
  cols <- c("holiday_share", "is_holiday", "bridge_day", "day_before_holiday", "day_after_holiday",
            "holiday_share_prev", "holiday_share_next", "school_holiday_proxy", "daytype",
            "holiday_name")
  for (col in cols) data.table::set(out, j = col, value = daily[[col]][idx])
  out[, hour_daytype := hour + 24L * daytype]
  out[]
}
