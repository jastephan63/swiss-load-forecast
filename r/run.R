args <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", args[grep("^--file=", args)])
here <- normalizePath(dirname(script))
source(file.path(here, "load.R"))
load_project(here)

cmd <- commandArgs(trailingOnly = TRUE)
usage <- "Usage: Rscript r/run.R <data|train|evaluate|anomalies|all> [--config path] [--skip-download]"
if (!length(cmd)) stop(usage, call. = FALSE)
config_path <- if ("--config" %in% cmd) cmd[which(cmd == "--config") + 1] else
  file.path(dirname(here), "config.yaml")
cfg <- load_config(config_path)
step <- cmd[1]

do_data <- function() {
  path <- run_data(cfg, download = !("--skip-download" %in% cmd))
  message("Data ready. Validation report: ", path)
}
do_train <- function() {
  run_train(cfg)
  message("Training and cross-validation finished.")
}
do_evaluate <- function() print(run_evaluate(cfg)$test, digits = 4)
do_anomalies <- function() print(run_anomalies(cfg)$injection, digits = 2)

switch(step,
  data = do_data(),
  train = do_train(),
  evaluate = do_evaluate(),
  anomalies = do_anomalies(),
  all = {
    do_data()
    do_train()
    do_evaluate()
    do_anomalies()
  },
  stop(usage, call. = FALSE)
)
