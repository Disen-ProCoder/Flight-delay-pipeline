"""
src/pipeline_runner.py

Main pipeline orchestrator. Connects Extract → Transform → Quality → Load.
Can be called directly (CLI) or imported by the Airflow DAG.

Usage:
    python src/pipeline_runner.py --year 2023 --month 1
    python src/pipeline_runner.py --year 2023 --month 6 --overwrite
"""

import time
import sys
from datetime import datetime
from pathlib import Path

import click
from loguru import logger

from config.settings import PathConfig, PipelineConfig
from src.extract.download_bts import download_month
from src.transform.clean_flights import transform_flights
from src.quality.data_quality_checks import run_all_checks, print_quality_report
from src.load.load_to_postgres import load_pipeline


def setup_logging(year: int, month: int) -> None:
    """Configure Loguru logging for this pipeline run."""
    PathConfig.ensure_dirs()
    log_file = PathConfig.LOG_DIR / f"pipeline_{year}_{month:02d}_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
        level=PipelineConfig.LOG_LEVEL,
        colorize=True,
    )
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {module}:{line} | {message}",
        level="DEBUG",
        rotation="100 MB",
    )
    logger.info(f"Log file: {log_file}")


def run_pipeline(
    year: int,
    month: int,
    skip_download: bool = False,
    skip_quality: bool = False,
    overwrite: bool = False,
    fail_on_quality: bool = True,
) -> dict:
    """
    Run the full ETL pipeline for one year/month.

    Args:
        year: Year to process (e.g. 2023)
        month: Month to process (1-12)
        skip_download: Use existing file if already downloaded
        skip_quality: Skip data quality checks (not recommended for production)
        overwrite: Overwrite existing database records
        fail_on_quality: Abort pipeline if quality checks fail

    Returns:
        stats dict with pipeline run metadata
    """
    setup_logging(year, month)
    pipeline_start = time.time()

    logger.info(f"=" * 50)
    logger.info(f"PIPELINE START: {year}-{month:02d}")
    logger.info(f"=" * 50)

    stats = {
        "year": year,
        "month": month,
        "status": "failed",
        "steps_completed": [],
    }

    try:
        # ── STEP 1: EXTRACT ──────────────────────────────────
        logger.info("STEP 1/4: Extract — downloading BTS data")
        step_start = time.time()

        csv_path = download_month(year, month, force=not skip_download)
        if not csv_path:
            raise RuntimeError(f"Failed to download BTS data for {year}-{month:02d}")

        stats["steps_completed"].append("extract")
        stats["source_file"] = str(csv_path)
        logger.info(f"Extract complete in {time.time() - step_start:.1f}s")

        # ── STEP 2: TRANSFORM ────────────────────────────────
        logger.info("STEP 2/4: Transform — cleaning and enriching data")
        step_start = time.time()

        df, transform_stats = transform_flights(csv_path)
        stats.update(transform_stats)
        stats["steps_completed"].append("transform")
        logger.info(f"Transform complete in {time.time() - step_start:.1f}s")

        # ── STEP 3: DATA QUALITY ─────────────────────────────
        if not skip_quality:
            logger.info("STEP 3/4: Quality — running data quality checks")
            step_start = time.time()

            quality_results, all_passed = run_all_checks(df)
            print_quality_report(quality_results)
            stats["quality_results"] = quality_results
            stats["quality_passed"] = all_passed
            stats["steps_completed"].append("quality")

            if not all_passed and fail_on_quality:
                raise RuntimeError(
                    "Data quality checks failed. Set fail_on_quality=False to override."
                )

            logger.info(f"Quality checks complete in {time.time() - step_start:.1f}s")
        else:
            logger.warning("Skipping quality checks (skip_quality=True)")

        # ── STEP 4: LOAD ──────────────────────────────────────
        logger.info("STEP 4/4: Load — writing to PostgreSQL")
        step_start = time.time()

        load_stats = load_pipeline(
            df=df,
            source_file=str(csv_path),
            year=year,
            month=month,
            overwrite=overwrite,
        )
        stats.update(load_stats)
        stats["steps_completed"].append("load")
        logger.info(f"Load complete in {time.time() - step_start:.1f}s")

        # ── DONE ──────────────────────────────────────────────
        total_time = time.time() - pipeline_start
        stats["status"] = "success"
        stats["total_duration_sec"] = round(total_time, 2)

        logger.info("=" * 50)
        logger.success(
            f"PIPELINE COMPLETE: {year}-{month:02d} | "
            f"{stats.get('rows_loaded', 0):,} rows loaded | "
            f"{total_time:.1f}s total"
        )
        logger.info("=" * 50)

    except Exception as e:
        stats["status"] = "failed"
        stats["error"] = str(e)
        logger.error(f"PIPELINE FAILED: {e}")
        raise

    return stats


# ─────────────────────────────────────────
# CLI Interface
# ─────────────────────────────────────────

@click.command()
@click.option("--year",  required=True,  type=int)
@click.option("--month", required=True,  type=int, help="Month 1-12")
@click.option("--skip-download", is_flag=True, help="Skip download if file exists")
@click.option("--skip-quality",  is_flag=True, help="Skip data quality checks")
@click.option("--overwrite",     is_flag=True, help="Overwrite existing DB records")
@click.option("--no-fail-on-quality", is_flag=True, help="Continue even if quality fails")
def main(year, month, skip_download, skip_quality, overwrite, no_fail_on_quality):
    """Run the flight delay ETL pipeline for a specific year/month."""
    run_pipeline(
        year=year,
        month=month,
        skip_download=skip_download,
        skip_quality=skip_quality,
        overwrite=overwrite,
        fail_on_quality=not no_fail_on_quality,
    )


if __name__ == "__main__":
    main()
