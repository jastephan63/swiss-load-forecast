LABEL_FORMAT <- "%d.%m.%Y %H:%M"

read_swissgrid_sheet <- function(path, sheet) {
  head <- readxl::read_excel(path, sheet = sheet, range = readxl::cell_limits(c(1, 1), c(2, 2)),
                             col_names = FALSE, col_types = "text", .name_repair = "minimal")
  body <- readxl::read_excel(path, sheet = sheet, range = readxl::cell_cols("A:B"),
                             col_names = FALSE, col_types = c("text", "text"),
                             .name_repair = "minimal")
  body <- body[-(1:2), ]
  list(header = as.character(head[[2]][1]), unit = as.character(head[[2]][2]),
       labels = as.character(body[[1]]), values = body[[2]])
}

detect_convention <- function(first_label, year) {
  if (identical(first_label, sprintf("01.01.%s 00:15", year))) return("end")
  if (identical(first_label, sprintf("01.01.%s 00:00", year))) return("start")
  stop(sprintf("%s: cannot infer timestamp convention from '%s'", year, first_label), call. = FALSE)
}

labels_to_utc_start <- function(labels, convention, tz = TZ_DEFAULT) {
  naive <- as.POSIXct(labels, format = LABEL_FORMAT, tz = "UTC")
  if (anyNA(naive)) stop("Unparseable timestamp labels", call. = FALSE)
  cest <- naive - 7200
  cet <- naive - 3600
  ok_cest <- format(cest, LABEL_FORMAT, tz = tz) == labels
  ok_cet <- format(cet, LABEL_FORMAT, tz = tz) == labels
  repeated <- duplicated(labels)
  secs <- ifelse(ok_cest & ok_cet,
                 ifelse(repeated, as.numeric(cet), as.numeric(cest)),
                 ifelse(ok_cest, as.numeric(cest), ifelse(ok_cet, as.numeric(cet), NA_real_)))
  if (anyNA(secs)) stop("Labels that do not exist in local time", call. = FALSE)
  utc <- as.POSIXct(secs, origin = "1970-01-01", tz = "UTC")
  if (convention == "end") utc <- utc - 900
  utc
}

parse_year <- function(sheet, year, header_prefix, expected_unit) {
  head <- trimws(strsplit(sheet$header, "\n", fixed = TRUE)[[1]][1])
  if (!startsWith(head, header_prefix)) {
    stop(sprintf("%s: column B is '%s', expected '%s'", year, head, header_prefix), call. = FALSE)
  }
  if (!identical(trimws(sheet$unit), expected_unit)) {
    stop(sprintf("%s: column B unit is '%s', expected '%s'", year, sheet$unit, expected_unit),
         call. = FALSE)
  }
  labels <- trimws(sheet$labels)
  values <- suppressWarnings(as.numeric(sheet$values))
  convention <- detect_convention(labels[1], year)
  local <- as.POSIXct(labels, format = LABEL_FORMAT, tz = "UTC")
  day <- as.Date(local)
  if (convention == "end") day[format(local, "%H:%M") == "00:00"] <- day[format(local, "%H:%M") == "00:00"] - 1
  counts <- table(day)
  dst <- counts[counts != 96]
  report <- list(
    year = year, rows = length(labels), first_label = labels[1], last_label = labels[length(labels)],
    convention = convention, header = head, unit = sheet$unit, non_numeric = sum(is.na(values)),
    repeated_local_labels = sum(duplicated(labels)),
    dst_days = as.list(stats::setNames(as.integer(dst), names(dst)))
  )
  list(frame = data.table::data.table(label = labels, energy_kwh = values), report = report)
}

longest_identical_run <- function(x) {
  x <- x[!is.na(x)]
  if (!length(x)) return(0L)
  max(rle(x)$lengths)
}

interpolate_short_gaps <- function(x, limit) {
  na <- is.na(x)
  if (!any(na) || all(na)) return(x)
  r <- rle(na)
  ends <- cumsum(r$lengths)
  starts <- ends - r$lengths + 1
  idx <- seq_along(x)
  filled <- stats::approx(idx[!na], x[!na], xout = idx, rule = 1)$y
  keep_na <- rep(FALSE, length(x))
  for (i in which(r$values)) {
    inside <- starts[i] > 1 && ends[i] < length(x)
    if (!inside || r$lengths[i] > limit) keep_na[starts[i]:ends[i]] <- TRUE
  }
  filled[keep_na] <- NA_real_
  filled
}

to_hourly <- function(q15) {
  dt <- data.table::copy(q15)
  dt[, hour := as.POSIXct(floor(as.numeric(utc) / 3600) * 3600, origin = "1970-01-01", tz = "UTC")]
  out <- dt[, .(load_mw = mean(load_mw), n = sum(!is.na(load_mw))), by = .(utc = hour)]
  out[n < 4, load_mw := NA_real_]
  out[, n := NULL]
  out[]
}

clean_load <- function(cfg) {
  sg <- cfg$swissgrid
  reports <- list()
  parts <- list()
  for (year in sg$years) {
    path <- swissgrid_path(cfg, year)
    if (!file.exists(path)) stop("Missing raw file ", path, ". Run `make r-data` first.", call. = FALSE)
    parsed <- parse_year(read_swissgrid_sheet(path, sg$sheet), year, sg$target_header_prefix,
                         sg$expected_unit)
    parsed$frame[, utc := labels_to_utc_start(label, parsed$report$convention, cfg$timezone)]
    reports[[length(reports) + 1]] <- parsed$report
    parts[[length(parts) + 1]] <- parsed$frame
    message(sprintf("Parsed %s: %d rows, %s-labelled", year, parsed$report$rows,
                    parsed$report$convention))
  }
  raw <- data.table::rbindlist(parts)
  data.table::setorder(raw, utc)
  dup <- duplicated(raw$utc)
  raw <- raw[!dup]
  t0 <- utc_from_local(cfg, cfg$split$start)
  t1 <- utc_from_local(cfg, cfg$split$end)
  grid <- seq(t0, t1 - 900, by = 900)
  raw <- raw[utc >= t0 & utc < t1]
  load <- raw$energy_kwh[match(as.numeric(grid), as.numeric(raw$utc))] * 4 / 1000
  rng <- unlist(sg$plausible_mw_range)
  out_of_range <- !is.na(load) & (load < rng[1] | load > rng[2])
  load[out_of_range] <- NA_real_
  was_missing <- is.na(load)
  filled <- interpolate_short_gaps(load, sg$max_interpolation_intervals)
  q15 <- data.table::data.table(utc = grid, load_mw = filled,
                                interpolated = was_missing & !is.na(filled))
  hourly <- to_hourly(q15)
  report <- list(
    years = reports,
    utc_start = format(grid[1], "%Y-%m-%d %H:%M UTC"),
    utc_end = format(t1, "%Y-%m-%d %H:%M UTC"),
    expected_intervals = length(grid), observed_intervals = nrow(raw),
    duplicate_utc_intervals = sum(dup), missing_intervals = sum(was_missing) - sum(out_of_range),
    out_of_range_values = sum(out_of_range),
    interpolated_intervals = sum(q15$interpolated),
    remaining_missing_intervals = sum(is.na(filled)),
    longest_identical_run = longest_identical_run(filled),
    hourly_rows = nrow(hourly), hourly_incomplete = sum(is.na(hourly$load_mw))
  )
  list(q15 = q15, hourly = hourly, report = report)
}

utc_from_local <- function(cfg, value) {
  t <- cfg_time(cfg, value)
  attr(t, "tzone") <- "UTC"
  t
}

write_validation_report <- function(report, dir) {
  dir.create(dir, recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(report, file.path(dir, "data_validation.json"), auto_unbox = TRUE,
                       pretty = TRUE)
  rows <- vapply(report$years, function(y) {
    dst <- paste(sprintf("%s (%s)", names(y$dst_days), unlist(y$dst_days)), collapse = ", ")
    sprintf("| %s | %s | %s | %s | interval %s | %s | %s | %s | %s |", y$year,
            format(y$rows, big.mark = ","), y$first_label, y$last_label, y$convention, y$unit,
            y$non_numeric, y$repeated_local_labels, dst)
  }, "")
  lines <- c(
    "# Data validation report (R pipeline)", "",
    "Generated by `make r-data`. Source: Swissgrid Energieübersicht Schweiz, sheet `Zeitreihen0h15`, column B.",
    "", "## Per file", "",
    "| Year | Rows | First label | Last label | Label convention | Unit | Non-numeric | Repeated local labels | DST days (intervals) |",
    "|---|---|---|---|---|---|---|---|---|", rows, "",
    "## Combined 15-minute series (UTC interval start)", "",
    sprintf("* Period: %s to %s", report$utc_start, report$utc_end),
    sprintf("* Expected intervals: %s", format(report$expected_intervals, big.mark = ",")),
    sprintf("* Observed intervals in period: %s", format(report$observed_intervals, big.mark = ",")),
    sprintf("* Duplicate UTC intervals removed: %s", report$duplicate_utc_intervals),
    sprintf("* Missing intervals before cleaning: %s", report$missing_intervals),
    sprintf("* Values outside the plausible range set to missing: %s", report$out_of_range_values),
    sprintf("* Intervals filled by interpolation (gaps up to 1 h): %s", report$interpolated_intervals),
    sprintf("* Intervals still missing after cleaning: %s", report$remaining_missing_intervals),
    sprintf("* Longest run of identical consecutive values: %s", report$longest_identical_run),
    sprintf("* Hourly rows: %s, of which incomplete: %s", format(report$hourly_rows, big.mark = ","),
            report$hourly_incomplete)
  )
  if (!is.null(report$weather)) {
    lines <- c(lines, "", "## Weather (Open-Meteo archive, hourly, UTC)", "",
               sprintf("* %s: %s", names(report$weather), vapply(report$weather, function(v)
                 paste(format(v), collapse = ", "), "")))
  }
  path <- file.path(dir, "data_validation.md")
  writeLines(lines, path, useBytes = TRUE)
  path
}
