UV ?= uv
RUN = $(UV) run slf --verbose

.PHONY: install data train evaluate anomalies all test lint format typecheck clean docker

install:
	$(UV) sync --frozen

data:
	$(RUN) data

train:
	$(RUN) train

evaluate:
	$(RUN) evaluate

anomalies:
	$(RUN) anomalies

all: data train evaluate anomalies

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

format:
	$(UV) run ruff format src tests
	$(UV) run ruff check --fix src tests

typecheck:
	$(UV) run mypy src

clean:
	rm -rf data/interim data/processed models

docker:
	docker build -t swiss-load-forecast .
	docker run --rm -v "$(CURDIR)/data:/app/data" -v "$(CURDIR)/reports:/app/reports" swiss-load-forecast

RSCRIPT = cd r && Rscript run.R

.PHONY: r-install r-data r-train r-evaluate r-anomalies r-all r-test r-docker

r-install:
	cd r && Rscript -e 'renv::restore(prompt = FALSE)'

r-data:
	$(RSCRIPT) data

r-train:
	$(RSCRIPT) train

r-evaluate:
	$(RSCRIPT) evaluate

r-anomalies:
	$(RSCRIPT) anomalies

r-all: r-data r-train r-evaluate r-anomalies

r-test:
	cd r && Rscript tests/run_tests.R

r-docker:
	docker build -f r/Dockerfile -t swiss-load-forecast-r .
	docker run --rm -v "$(CURDIR)/data:/app/data" -v "$(CURDIR)/reports:/app/reports" swiss-load-forecast-r
