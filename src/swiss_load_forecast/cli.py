from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from swiss_load_forecast.config import DEFAULT_CONFIG, load_config
from swiss_load_forecast.download import DownloadError
from swiss_load_forecast.pipeline import run_anomalies, run_data, run_evaluate, run_train

app = typer.Typer(add_completion=False, help="Swiss day-ahead load forecasting pipeline")

ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="Path to config.yaml")]


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def data(
    config: ConfigOption = DEFAULT_CONFIG,
    skip_download: Annotated[bool, typer.Option("--skip-download")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    try:
        path = run_data(load_config(config), download=not skip_download, force=force)
    except DownloadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Data ready. Validation report: {path}")


@app.command()
def train(config: ConfigOption = DEFAULT_CONFIG) -> None:
    run_train(load_config(config))
    typer.echo("Training and cross-validation finished.")


@app.command()
def evaluate(config: ConfigOption = DEFAULT_CONFIG) -> None:
    results = run_evaluate(load_config(config))
    typer.echo(results["test"].to_string(index=False, float_format=lambda v: f"{v:.2f}"))


@app.command()
def anomalies(config: ConfigOption = DEFAULT_CONFIG) -> None:
    results = run_anomalies(load_config(config))
    typer.echo(results["injection"].to_string(float_format=lambda v: f"{v:.2f}"))


@app.command(name="all")
def run_all(config: ConfigOption = DEFAULT_CONFIG) -> None:
    data(config)
    train(config)
    evaluate(config)
    anomalies(config)


if __name__ == "__main__":
    app()
