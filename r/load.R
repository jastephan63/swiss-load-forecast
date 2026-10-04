suppressPackageStartupMessages(library(data.table))
load_project <- function(dir) {
  for (f in sort(list.files(file.path(dir, "R"), pattern = "\\.R$", full.names = TRUE))) {
    sys.source(f, envir = globalenv())
  }
  invisible(TRUE)
}
