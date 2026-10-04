args <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", args[grep("^--file=", args)])
root <- normalizePath(file.path(dirname(script), ".."))
source(file.path(root, "load.R"))
load_project(root)
res <- testthat::test_dir(file.path(root, "tests", "testthat"), reporter = "summary",
                          stop_on_failure = TRUE, load_package = "none")
