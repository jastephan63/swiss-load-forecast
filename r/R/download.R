swissgrid_url <- function(cfg, year) {
  sub("{year}", year, cfg$swissgrid$url_template, fixed = TRUE)
}

swissgrid_path <- function(cfg, year) {
  file.path(cfg$r_paths$raw, "swissgrid", sprintf("EnergieUebersichtCH-%s.xlsx", year))
}

weather_path <- function(cfg, name) {
  file.path(cfg$r_paths$raw, "weather", sprintf("open_meteo_%s.csv", name))
}

is_valid_xlsx <- function(path) {
  if (!file.exists(path) || file.size(path) < 1e6) return(FALSE)
  con <- file(path, "rb")
  on.exit(close(con))
  identical(readBin(con, "raw", 4), as.raw(c(0x50, 0x4b, 0x03, 0x04)))
}

download_swissgrid <- function(cfg, force = FALSE) {
  failures <- character(0)
  records <- list()
  for (year in cfg$swissgrid$years) {
    url <- swissgrid_url(cfg, year)
    target <- swissgrid_path(cfg, year)
    dir.create(dirname(target), recursive = TRUE, showWarnings = FALSE)
    if (force || !is_valid_xlsx(target)) {
      message("Downloading ", url)
      tmp <- paste0(target, ".part")
      ok <- tryCatch(
        utils::download.file(url, tmp, mode = "wb", quiet = TRUE) == 0,
        error = function(e) FALSE
      )
      if (!ok || !is_valid_xlsx(tmp)) {
        unlink(tmp)
        failures <- c(failures, sprintf("  %s\n    -> %s", url, target))
        next
      }
      file.rename(tmp, target)
    }
    records[[length(records) + 1]] <- list(
      name = paste0("swissgrid_", year), url = url, path = target,
      sha256 = digest::digest(file = target, algo = "sha256"), bytes = file.size(target)
    )
  }
  if (length(failures)) {
    stop(paste(c(
      "Automatic download of the Swissgrid files failed.",
      "Please download these files by hand and place them at the paths shown:",
      failures,
      paste("Landing page:", cfg$swissgrid$landing_page)
    ), collapse = "\n"), call. = FALSE)
  }
  records
}

download_weather <- function(cfg, force = FALSE) {
  w <- cfg$weather
  records <- list()
  for (loc in w$locations) {
    target <- weather_path(cfg, loc$name)
    dir.create(dirname(target), recursive = TRUE, showWarnings = FALSE)
    url <- sprintf(
      "%s?latitude=%s&longitude=%s&start_date=%s&end_date=%s&hourly=%s&timezone=GMT",
      w$api_url, loc$latitude, loc$longitude, w$start, w$end,
      paste(unlist(w$variables), collapse = "%2C")
    )
    if (force || !file.exists(target)) {
      message("Downloading weather for ", loc$name)
      payload <- tryCatch(jsonlite::fromJSON(url), error = function(e) {
        stop("Open-Meteo request failed for ", loc$name, ": ", conditionMessage(e), call. = FALSE)
      })
      hourly <- as.data.frame(payload$hourly)
      missing <- setdiff(c("time", unlist(w$variables)), names(hourly))
      if (length(missing)) stop("Open-Meteo did not return ", paste(missing, collapse = ", "))
      data.table::fwrite(hourly, target)
    }
    records[[length(records) + 1]] <- list(
      name = paste0("weather_", loc$name), url = url, path = target,
      sha256 = digest::digest(file = target, algo = "sha256"), bytes = file.size(target)
    )
  }
  records
}

download_all <- function(cfg, force = FALSE) {
  records <- c(download_swissgrid(cfg, force), download_weather(cfg, force))
  path <- file.path(cfg$r_paths$interim, "manifest.json")
  jsonlite::write_json(records, path, auto_unbox = TRUE, pretty = TRUE)
  path
}
