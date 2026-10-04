TZ_DEFAULT <- "Europe/Zurich"

load_config <- function(path = "config.yaml", root = NULL) {
  cfg <- yaml::read_yaml(path)
  if (is.null(root)) root <- dirname(normalizePath(path))
  cfg$root <- root
  cfg$r_paths <- list(
    raw = file.path(root, cfg$paths$raw),
    interim = file.path(root, "data", "r", "interim"),
    processed = file.path(root, "data", "r", "processed"),
    models = file.path(root, "models", "r"),
    reports = file.path(root, "reports", "r"),
    figures = file.path(root, "reports", "r", "figures")
  )
  cfg
}

ensure_dirs <- function(cfg) {
  for (p in cfg$r_paths) dir.create(p, recursive = TRUE, showWarnings = FALSE)
  invisible(cfg)
}

canton_population <- function(cfg) {
  p <- unlist(cfg$canton_population_thousands)
  stats::setNames(as.numeric(p), names(p))
}

canton_weights <- function(cfg) {
  p <- canton_population(cfg)
  p / sum(p)
}

location_weights <- function(cfg) {
  p <- canton_population(cfg)
  w <- vapply(
    cfg$weather$locations,
    function(l) sum(p[names(l$cantons)] * unlist(l$cantons)),
    numeric(1)
  )
  stats::setNames(w / sum(p), vapply(cfg$weather$locations, function(l) l$name, ""))
}

cfg_time <- function(cfg, value) {
  as.POSIXct(paste(value, "00:00:00"), tz = cfg$timezone)
}
