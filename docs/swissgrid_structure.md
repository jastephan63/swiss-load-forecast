# Structure of the Swissgrid "Energieübersicht Schweiz" workbooks

Inspected on 2026-09-29 for the years 2021 to 2025 (and the partial 2026 file for comparison).

## Source

| Year | URL | Size |
|------|-----|------|
| 2021 | https://www.swissgrid.ch/dam/dataimport/energy-statistic/EnergieUebersichtCH-2021.xlsx | 24.5 MB |
| 2022 | https://www.swissgrid.ch/dam/dataimport/energy-statistic/EnergieUebersichtCH-2022.xlsx | 24.7 MB |
| 2023 | https://www.swissgrid.ch/dam/dataimport/energy-statistic/EnergieUebersichtCH-2023.xlsx | 24.2 MB |
| 2024 | https://www.swissgrid.ch/dam/dataimport/energy-statistic/EnergieUebersichtCH-2024.xlsx | 24.4 MB |
| 2025 | https://www.swissgrid.ch/dam/dataimport/energy-statistic/EnergieUebersichtCH-2025.xlsx | 26.4 MB |

Landing page: https://www.swissgrid.ch/en/home/operation/grid-data/generation.html

`make data` records the SHA-256 of every downloaded file in `data/raw/manifest.json`.

## Sheets

`Einstellungen`, `Datetime`, `Uebersicht`, `Zeitreihen0h15` in every year. 2021 and 2022 also contain `Zeitreihen1h00`.
Only `Zeitreihen0h15` is used.

## Layout of `Zeitreihen0h15`

* Row 1: bilingual column headers (German, line break, English).
* Row 2: units. Column A is `Zeitstempel`; energy columns are `kWh`, price columns `Euro/MWh`.
* Row 3 onwards: one row per 15-minute interval.
* 65 columns: timestamp, national sums (end-user consumption, production, total consumption, net outflow, grid feed-in), control energy, cross-border exchanges, control energy prices, and production and consumption per canton or canton group.

The target used here is column B:

> Summe endverbrauchte Energie Regelblock Schweiz / Total energy consumed by end users in the Swiss controlblock [kWh per 15 min]

It is converted to average power in MW as `kWh * 4 / 1000`.

## Observations per year

| Year | Data rows | First label | Last label | Duplicate labels | Days with != 96 rows | Annual end-user energy |
|------|-----------|-------------|------------|------------------|----------------------|------------------------|
| 2021 | 35,040 | 01.01.2021 00:15 | 01.01.2022 00:00 | 4 | 2021-03-28 (92), 2021-10-31 (100) | 56.79 TWh |
| 2022 | 35,040 | 01.01.2022 00:15 | 01.01.2023 00:00 | 4 | 2022-03-27 (92), 2022-10-30 (100) | 55.45 TWh |
| 2023 | 35,040 | 01.01.2023 00:15 | 01.01.2024 00:00 | 4 | 2023-03-26 (92), 2023-10-29 (100) | 53.48 TWh |
| 2024 | 35,136 | 01.01.2024 00:15 | 01.01.2025 00:00 | 4 | 2024-03-31 (92), 2024-10-27 (100) | 53.37 TWh |
| 2025 | 35,040 | 01.01.2025 00:00 | 31.12.2025 23:45 | 4 | 2025-03-30 (92), 2025-10-26 (100) | 53.50 TWh |

End-user load ranges from about 3,600 MW to 9,800 MW, median about 6,000 to 6,450 MW. There are no empty or non-numeric target cells and no zeros.

## Timestamps

* Timestamps are text in the format `dd.mm.yyyy HH:MM` in local Swiss time (CET/CEST).
* Daylight-saving transitions appear in local time: the spring day has 92 intervals, the autumn day has 100, with the four `02:xx` labels repeated. These repeated labels are the 4 "duplicate labels" per year and are not real duplicates.
* **The labelling convention changes in 2025.** Files for 2021 to 2024 label each interval by its **end** (the year runs from `00:15` on 1 January to `00:00` on 1 January of the next year). The 2025 file labels each interval by its **start** (`00:00` to `23:45`). The partial 2026 file also starts at `00:00` and stores native Excel datetimes instead of text. The first 2025 value (1,659,415 kWh) differs from the last 2024 value (1,634,796 kWh), so the 2025 file does not repeat the last interval of 2024.
* The pipeline detects the convention from the first label of each file (`00:15` means end-labelled, `00:00` means start-labelled), converts every interval to its UTC start time and then checks for a gap-free, duplicate-free 15-minute grid across all years.
