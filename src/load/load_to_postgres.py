"""
src/load/load_to_postgres.py

Loads transformed flight DataFrames into the PostgreSQL warehouse.

Strategy:
  1. Write to staging.raw_flights first (fast, no constraints)
  2. Run data quality checks
  3. Upsert to warehouse.fact_flights (handles re-runs safely)
  4. Update audit.pipeline_runs

Uses SQLAlchemy + psycopg2 for connection management.
Batch inserts for performance (10K rows per batch = ~8 min for 600K rows).
"""

from __future__ import annotations
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from loguru import logger

from config.settings import DatabaseConfig, PipelineConfig


# Columns to select from the DataFrame for warehouse.fact_flights
FACT_COLUMNS = [
    "flight_date", "date_id", "carrier_code", "flight_number",
    "origin_airport", "dest_airport",
    "scheduled_departure", "actual_departure",
    "scheduled_arrival", "actual_arrival",
    "departure_delay_min", "arrival_delay_min",
    "carrier_delay_min", "weather_delay_min",
    "nas_delay_min", "security_delay_min", "late_aircraft_delay_min",
    "is_cancelled", "cancellation_code", "is_diverted",
    "scheduled_duration_min", "actual_duration_min",
    "air_time_min", "distance_miles",
    "is_delayed", "delay_category", "route",
    "year", "month", "source_file",
]


def get_engine(echo: bool = False) -> Engine:
    """
    Create a SQLAlchemy engine.
    Called once per pipeline run — engines are thread-safe and reusable.
    """
    conn_str = DatabaseConfig.connection_string()
    engine = create_engine(
        conn_str,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,   # Checks connection health before using
        echo=echo,
    )
    logger.debug("Database engine created")
    return engine


def test_connection(engine: Engine) -> bool:
    """Verify the database connection is working."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            logger.info(f"Connected to PostgreSQL: {version[:50]}")
            return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def upsert_carriers(df: pd.DataFrame, engine: Engine) -> int:
    """
    Upsert carrier codes from the flight data into dim_carriers.
    Uses ON CONFLICT DO UPDATE to handle re-runs safely.
    """
    if "carrier_code" not in df.columns:
        return 0

    carriers = df[["carrier_code"]].drop_duplicates()
    upsert_sql = text("""
        INSERT INTO warehouse.dim_carriers (carrier_code)
        VALUES (:carrier_code)
        ON CONFLICT (carrier_code) DO NOTHING
    """)

    with engine.connect() as conn:
        with conn.begin():
            result = conn.execute(upsert_sql, carriers.to_dict("records"))

    logger.info(f"Upserted {len(carriers)} carriers into dim_carriers")
    return len(carriers)


def upsert_airports(df: pd.DataFrame, engine: Engine) -> int:
    """
    Upsert airport codes from the flight data into dim_airports.
    Note: this only inserts the IATA code — lat/lon enrichment
    happens separately via the AviationStack loader.
    """
    if "origin_airport" not in df.columns:
        return 0

    origins = df[["origin_airport"]].rename(columns={"origin_airport": "iata_code"})
    dests = df[["dest_airport"]].rename(columns={"dest_airport": "iata_code"})
    airports = pd.concat([origins, dests]).drop_duplicates()

    upsert_sql = text("""
        INSERT INTO warehouse.dim_airports (iata_code)
        VALUES (:iata_code)
        ON CONFLICT (iata_code) DO NOTHING
    """)

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(upsert_sql, airports.to_dict("records"))

    logger.info(f"Upserted {len(airports)} airports into dim_airports")
    return len(airports)


def load_to_staging(df: pd.DataFrame, engine: Engine, source_file: str) -> int:
    """
    Load raw data to staging table. Fast — minimal constraints.
    Returns number of rows loaded.
    """
    staging_df = df.copy()

    # Only keep columns that exist in the staging schema
    staging_cols = [
        "carrier_code", "flight_number", "origin_airport", "dest_airport",
        "departure_delay_min", "arrival_delay_min", "is_cancelled",
        "distance_miles",
    ]
    available_cols = [c for c in staging_cols if c in staging_df.columns]
    staging_df = staging_df[available_cols].copy()

    staging_df["source_file"] = source_file
    staging_df["flight_date"] = df["flight_date"].astype(str) if "flight_date" in df.columns else None
    staging_df["is_processed"] = False

    staging_df.to_sql(
        "raw_flights",
        engine,
        schema="staging",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=PipelineConfig.DB_BATCH_SIZE,
    )

    logger.info(f"Loaded {len(staging_df):,} rows to staging.raw_flights")
    return len(staging_df)


def load_to_warehouse(df: pd.DataFrame, engine: Engine) -> int:
    """
    Load cleaned data to warehouse.fact_flights.
    Uses batch inserts for performance.
    Returns number of rows loaded.
    """
    # Select only the columns we need, in order
    cols = [c for c in FACT_COLUMNS if c in df.columns]
    fact_df = df[cols].copy()

    # Convert pandas NA to Python None for PostgreSQL compatibility
    fact_df = fact_df.where(pd.notnull(fact_df), None)

    # Convert Int16/Int32 to regular int (SQLAlchemy compatibility)
    for col in fact_df.select_dtypes(include=["Int8", "Int16", "Int32", "Int64"]).columns:
        fact_df[col] = fact_df[col].astype(object).where(fact_df[col].notna(), None)

    total_loaded = 0
    batch_size = PipelineConfig.DB_BATCH_SIZE
    n_batches = (len(fact_df) + batch_size - 1) // batch_size

    logger.info(f"Loading {len(fact_df):,} rows in {n_batches} batches of {batch_size:,}")

    start_time = time.time()

    for i, batch_start in enumerate(range(0, len(fact_df), batch_size)):
        batch = fact_df.iloc[batch_start : batch_start + batch_size]

        batch.to_sql(
            "fact_flights",
            engine,
            schema="warehouse",
            if_exists="append",
            index=False,
            method="multi",
        )

        total_loaded += len(batch)
        elapsed = time.time() - start_time
        rate = total_loaded / elapsed if elapsed > 0 else 0
        logger.info(
            f"Batch {i+1}/{n_batches}: {total_loaded:,}/{len(fact_df):,} rows "
            f"({rate:.0f} rows/sec)"
        )

    logger.success(f"Loaded {total_loaded:,} rows to warehouse.fact_flights in {elapsed:.1f}s")
    return total_loaded


def check_for_duplicates(engine: Engine, year: int, month: int) -> int:
    """
    Check if data for this year/month already exists.
    Returns the row count (0 = safe to load, >0 = already loaded).
    """
    sql = text("""
        SELECT COUNT(*) FROM warehouse.fact_flights
        WHERE year = :year AND month = :month
    """)
    with engine.connect() as conn:
        count = conn.execute(sql, {"year": year, "month": month}).scalar()
    return count


def delete_existing_partition(engine: Engine, year: int, month: int) -> None:
    """
    Delete existing data for a year/month before re-loading.
    Handles idempotent pipeline re-runs safely.
    """
    sql = text("""
        DELETE FROM warehouse.fact_flights
        WHERE year = :year AND month = :month
    """)
    with engine.connect() as conn:
        with conn.begin():
            result = conn.execute(sql, {"year": year, "month": month})
            logger.info(f"Deleted {result.rowcount:,} existing rows for {year}-{month:02d}")


def log_pipeline_run(
    engine: Engine,
    run_data: dict,
) -> int:
    """
    Insert a row into audit.pipeline_runs.
    Returns the run_id for linking data quality results.
    """
    sql = text("""
        INSERT INTO audit.pipeline_runs
            (dag_id, run_type, year, month, source_file, status,
             rows_extracted, rows_validated, rows_loaded, rows_rejected,
             started_at, completed_at, duration_sec, error_message)
        VALUES
            (:dag_id, :run_type, :year, :month, :source_file, :status,
             :rows_extracted, :rows_validated, :rows_loaded, :rows_rejected,
             :started_at, :completed_at, :duration_sec, :error_message)
        RETURNING run_id
    """)

    with engine.connect() as conn:
        with conn.begin():
            result = conn.execute(sql, run_data)
            run_id = result.scalar()

    logger.info(f"Pipeline run logged: run_id={run_id}, status={run_data['status']}")
    return run_id


def load_pipeline(
    df: pd.DataFrame,
    source_file: str,
    year: int,
    month: int,
    overwrite: bool = False,
) -> dict:
    """
    End-to-end load pipeline. Orchestrates all load steps.
    Returns stats dict with row counts and run metadata.
    """
    engine = get_engine()
    started_at = datetime.now()

    if not test_connection(engine):
        raise RuntimeError("Cannot connect to database")

    # Check for existing data
    existing_count = check_for_duplicates(engine, year, month)
    if existing_count > 0:
        if overwrite:
            logger.warning(f"Overwriting {existing_count:,} existing rows for {year}-{month:02d}")
            delete_existing_partition(engine, year, month)
        else:
            logger.warning(
                f"Data already exists for {year}-{month:02d} ({existing_count:,} rows). "
                "Use overwrite=True to replace. Skipping load."
            )
            return {"skipped": True, "existing_rows": existing_count}

    stats = {
        "dag_id": "flight_delay_pipeline",
        "run_type": "manual",
        "year": year,
        "month": month,
        "source_file": source_file,
        "status": "running",
        "rows_extracted": len(df),
        "rows_validated": len(df),
        "rows_loaded": 0,
        "rows_rejected": 0,
        "started_at": started_at,
        "completed_at": None,
        "duration_sec": None,
        "error_message": None,
    }

    try:
        # Update dimension tables
        upsert_carriers(df, engine)
        upsert_airports(df, engine)

        # Load fact table
        rows_loaded = load_to_warehouse(df, engine)
        stats["rows_loaded"] = rows_loaded

        completed_at = datetime.now()
        stats["completed_at"] = completed_at
        stats["duration_sec"] = (completed_at - started_at).total_seconds()
        stats["status"] = "success"

    except Exception as e:
        logger.error(f"Load failed: {e}")
        stats["status"] = "failed"
        stats["error_message"] = str(e)
        raise
    finally:
        log_pipeline_run(engine, stats)

    return stats
