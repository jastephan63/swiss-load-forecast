FROM rocker/r-ver:4.3.2

ENV RENV_CONFIG_PAK_ENABLED=FALSE \
    RENV_CONFIG_REPOS_OVERRIDE=https://p3m.dev/cran/__linux__/jammy/latest \
    RENV_PATHS_LIBRARY=/opt/renv/library

RUN apt-get update \
    && apt-get install -y --no-install-recommends make zlib1g-dev libcurl4-openssl-dev libssl-dev libxml2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/r
COPY r/renv.lock r/.Rprofile r/DESCRIPTION ./
COPY r/renv/activate.R r/renv/settings.json ./renv/
RUN Rscript -e 'renv::restore(prompt = FALSE)'

COPY r/ ./
COPY config.yaml Makefile /app/

WORKDIR /app
CMD ["make", "r-all"]
