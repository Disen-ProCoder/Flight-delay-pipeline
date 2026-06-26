"""
src/transform/clean_flights.py

Transforms raw BTS CSV data into clean, warehouse-ready DataFrames.

Steps:
  1. Load CSV and rename columns to our schema names
  2. Cast data types (strings → int/float/date)
  3. Handle nulls and out-of-range values
  4. Derive calculated columns (is_delayed, delay_category, route)
  5. Return clean DataFrame ready for loading

This module is pure Pandas — no database connections.
It's designed to be testable in isolation.
"""

from pathlib import Path
import pandas as pd
import numpy as np
from loguru import logger
from typing import Optional

from config.settings import PipelineConfig


# ─────────────────────────────────────────
# Column definitions
# ─────────────────────────────────────────

REQUIRED_COLUMNS = [
    "FL_DATE", "OP_UNIQUE_CARRIER", "OP_CARRIER_FL_NUM",
    "ORIGIN", "DEST", "DEP_DELAY", "ARR_DELAY",
    "CANCELLED", "DISTANCE",
]

NUMERIC_COLUMNS = [
    "departure_delay_min", "arrival_delay_min",
    "carrier_delay_min", "weather_delay_min",
    "nas_delay_min", "security_delay_min",
    "late_aircraft_delay_min", "scheduled_duration_min",
    "actual_duration_min", "air_time_min", "distance_miles",
    "scheduled_departure", "actual_departure",
    "scheduled_arrival", "actual_arrival",
]


def load_raw_csv(file_path: Path) -> pd.DataFrame:
    """
    Load a BTS CSV file into a DataFrame.
    BTS files can be 300-500MB — use chunked reading if memory is tight.
    """
    logger.info(f"Loading: {file_path} ({file_path.stat().st_size / 1e6:.1f} MB)")

    # BTS CSVs have a blank trailing column — drop it
    df = pd.read_csv(
        file_path,
        low_memory=False,       # Prevents dtype guessing warnings
        na_values=["", " ", "NA", "N/A", "."],
        encoding="utf-8",
    )

    # BTS adds an empty last column
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]

    logger.info(f"Loaded {len(df):,} rows, {len(df.columns)} columns")
    return df


def validate_required_columns(df: pd.DataFrame) -> None:
    """Raise ValueError if any required columns are missing."""
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required BTS columns: {missing}")


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map verbose BTS column names to our clean schema names."""
    col_map = PipelineConfig.BTS_COLUMN_MAP
    # Only rename columns that exist in the DataFrame
    existing_map = {k: v for k, v in col_map.items() if k in df.columns}
    df = df.rename(columns=existing_map)
    logger.debug(f"Renamed {len(existing_map)} columns")
    return df


def cast_data_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cast columns to correct types.
    BTS stores everything as strings/objects — we need numeric and date types.
    """
    # Flight date → datetime
    if "flight_date" in df.columns:
        df["flight_date"] = pd.to_datetime(df["flight_date"], errors="coerce")

    # Numeric delay/distance columns
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Boolean flags (BTS stores as 0.0/1.0)
    for col in ["is_cancelled", "is_diverted"]:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(bool)

    # Integer time columns (HHMM format)
    for col in ["year", "month", "day_of_month", "day_of_week"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int16")

    logger.debug("Data types cast successfully")
    return df


def handle_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """
    Business rules for null handling:
    - Cancelled flights have null delays by definition (not data errors)
    - Delay breakdowns may not sum to total delay — this is a BTS known issue
    - Diverted flights have unreliable arrival times
    """
    # For cancelled flights, delay columns are expected to be null
    # Flag them so we don't count them as data quality failures
    cancelled_mask = df["is_cancelled"] == True

    delay_cols = [
        "departure_delay_min", "arrival_delay_min",
        "carrier_delay_min", "weather_delay_min",
        "nas_delay_min", "security_delay_min",
        "late_aircraft_delay_min",
    ]

    null_counts = df[delay_cols].isnull().sum()
    for col in delay_cols:
        non_cancelled_nulls = df.loc[~cancelled_mask, col].isnull().sum()
        if non_cancelled_nulls > 0:
            logger.warning(
                f"{col}: {non_cancelled_nulls:,} nulls in non-cancelled flights"
            )

    return df


def derive_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add calculated columns that make analysis queries simpler.
    These are derived entirely from existing data — no external lookups.
    """
    # is_delayed: FAA official definition = arrival delay >= 15 minutes
    df["is_delayed"] = (
        df["arrival_delay_min"].notna() &
        (df["arrival_delay_min"] >= PipelineConfig.DELAY_THRESHOLD_MIN)
    )

    # delay_category: bucketed delay severity
    def categorise_delay(delay: Optional[float], cancelled: bool) -> str:
        if cancelled:
            return "Cancelled"
        if pd.isna(delay):
            return "Unknown"
        if delay < 0:
            return "Early"
        if delay < 15:
            return "On Time"
        if delay < 60:
            return "Minor Delay"
        if delay < 180:
            return "Major Delay"
        return "Severe Delay"

    df["delay_category"] = df.apply(
        lambda r: categorise_delay(r.get("arrival_delay_min"), r.get("is_cancelled", False)),
        axis=1,
    )

    # route: standard IATA route format (e.g. 'JFK-LAX')
    if "origin_airport" in df.columns and "dest_airport" in df.columns:
        df["route"] = df["origin_airport"].str.strip() + "-" + df["dest_airport"].str.strip()

    # date_id: integer key for joining to dim_date
    if "flight_date" in df.columns:
        df["date_id"] = df["flight_date"].dt.strftime("%Y%m%d").astype("Int32")

    logger.debug("Derived columns added: is_delayed, delay_category, route, date_id")
    return df


def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove duplicate rows.
    BTS data occasionally has duplicates from data corrections.
    """
    key_cols = ["flight_date", "carrier_code", "flight_number", "origin_airport", "dest_airport"]
    existing_keys = [c for c in key_cols if c in df.columns]

    original_len = len(df)
    df = df.drop_duplicates(subset=existing_keys, keep="last")
    dropped = original_len - len(df)

    if dropped > 0:
        logger.warning(f"Removed {dropped:,} duplicate rows")

    return df


def filter_valid_airports(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop rows with invalid airport codes.
    IATA codes are exactly 3 uppercase letters.
    """
    if "origin_airport" not in df.columns or "dest_airport" not in df.columns:
        return df

    iata_pattern = r"^[A-Z]{3}$"
    valid_mask = (
        df["origin_airport"].str.match(iata_pattern, na=False) &
        df["dest_airport"].str.match(iata_pattern, na=False)
    )

    invalid_count = (~valid_mask).sum()
    if invalid_count > 0:
        logger.warning(f"Dropping {invalid_count:,} rows with invalid airport codes")
        df = df[valid_mask].copy()

    return df


def add_source_metadata(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """Tag each row with its source file for audit purposes."""
    df["source_file"] = source_file
    return df


def transform_flights(file_path: Path) -> tuple[pd.DataFrame, dict]:
    """
    Main transformation pipeline. Returns (clean_df, stats_dict).
    
    Call this from the load step or the Airflow DAG.
    
    Returns:
        clean_df: transformed DataFrame ready for database loading
        stats: dict with row counts and quality metrics
    """
    stats = {
        "source_file": str(file_path),
        "rows_raw": 0,
        "rows_after_dedup": 0,
        "rows_valid": 0,
        "rows_rejected": 0,
        "cancelled_flights": 0,
        "diverted_flights": 0,
        "null_arrival_delay": 0,
    }

    # Step 1: Load
    df = load_raw_csv(file_path)
    stats["rows_raw"] = len(df)

    # Step 2: Validate columns exist
    validate_required_columns(df)

    # Step 3: Rename
    df = rename_columns(df)

    # Step 4: Cast types
    df = cast_data_types(df)

    # Step 5: Handle nulls
    df = handle_nulls(df)

    # Step 6: Remove duplicates
    df = remove_duplicates(df)
    stats["rows_after_dedup"] = len(df)

    # Step 7: Filter invalid airport codes
    df = filter_valid_airports(df)

    # Step 8: Derive calculated columns
    df = derive_columns(df)

    # Step 9: Add audit metadata
    df = add_source_metadata(df, str(file_path))

    # Collect stats
    stats["rows_valid"] = len(df)
    stats["rows_rejected"] = stats["rows_raw"] - stats["rows_valid"]
    stats["cancelled_flights"] = int(df["is_cancelled"].sum()) if "is_cancelled" in df.columns else 0
    stats["null_arrival_delay"] = int(df["arrival_delay_min"].isnull().sum())

    logger.success(
        f"Transform complete: {stats['rows_valid']:,} valid rows "
        f"({stats['rows_rejected']:,} rejected, "
        f"{stats['cancelled_flights']:,} cancelled)"
    )

    return df, stats
