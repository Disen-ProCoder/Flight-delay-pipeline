"""
src/quality/data_quality_checks.py

Data quality checks using Great Expectations (GE) concepts,
implemented in plain Pandas for simplicity and portability.

Why not use GE directly? For a portfolio project, pure-Pandas checks
are easier to run without the full GE setup. The concepts (expectations,
thresholds, pass/fail) are identical to what Great Expectations does.

Each check returns a dict:
    {
        "check_name": str,
        "passed": bool,
        "pass_rate": float,  # 0.0 to 1.0
        "threshold": float,
        "rows_checked": int,
        "rows_failed": int,
        "details": dict,
    }
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from loguru import logger
from typing import Callable


# ─────────────────────────────────────────
# Individual check functions
# ─────────────────────────────────────────

def check_not_null(
    df: pd.DataFrame, column: str, threshold: float = 0.99
) -> dict:
    """
    Expect column to be non-null for at least `threshold` fraction of rows.
    Example: arrival_delay should be non-null for 95%+ of non-cancelled flights.
    """
    total = len(df)
    not_null = df[column].notna().sum()
    pass_rate = not_null / total if total > 0 else 0.0
    passed = pass_rate >= threshold

    return {
        "check_name": f"not_null::{column}",
        "check_type": "completeness",
        "column_name": column,
        "rows_checked": total,
        "rows_failed": total - int(not_null),
        "pass_rate": round(pass_rate, 4),
        "threshold": threshold,
        "passed": passed,
        "details": {"not_null_count": int(not_null), "null_count": total - int(not_null)},
    }


def check_values_in_set(
    df: pd.DataFrame, column: str, valid_values: set, threshold: float = 0.99
) -> dict:
    """Expect column values to be within a known set."""
    total = len(df)
    in_set = df[column].isin(valid_values).sum()
    pass_rate = in_set / total if total > 0 else 0.0
    passed = pass_rate >= threshold

    invalid = df.loc[~df[column].isin(valid_values), column].value_counts().head(10).to_dict()

    return {
        "check_name": f"values_in_set::{column}",
        "check_type": "validity",
        "column_name": column,
        "rows_checked": total,
        "rows_failed": total - int(in_set),
        "pass_rate": round(pass_rate, 4),
        "threshold": threshold,
        "passed": passed,
        "details": {"invalid_top10": invalid},
    }


def check_value_range(
    df: pd.DataFrame,
    column: str,
    min_val: float,
    max_val: float,
    threshold: float = 0.99,
) -> dict:
    """Expect numeric column values to fall within [min_val, max_val]."""
    col = pd.to_numeric(df[column], errors="coerce")
    total = col.notna().sum()  # Only check non-null values
    in_range = ((col >= min_val) & (col <= max_val)).sum()
    pass_rate = in_range / total if total > 0 else 0.0
    passed = pass_rate >= threshold

    out_of_range = col[(col < min_val) | (col > max_val)]

    return {
        "check_name": f"value_range::{column}",
        "check_type": "validity",
        "column_name": column,
        "rows_checked": int(total),
        "rows_failed": int(total - in_range),
        "pass_rate": round(pass_rate, 4),
        "threshold": threshold,
        "passed": passed,
        "details": {
            "min_val": min_val,
            "max_val": max_val,
            "actual_min": float(col.min()) if not col.empty else None,
            "actual_max": float(col.max()) if not col.empty else None,
            "outlier_count": int(len(out_of_range)),
        },
    }


def check_unique(
    df: pd.DataFrame, columns: list[str], threshold: float = 0.999
) -> dict:
    """Expect combination of columns to be unique."""
    total = len(df)
    unique_count = df[columns].drop_duplicates().shape[0]
    pass_rate = unique_count / total if total > 0 else 0.0
    passed = pass_rate >= threshold
    dup_count = total - unique_count

    return {
        "check_name": f"unique::{'+'.join(columns)}",
        "check_type": "uniqueness",
        "column_name": "+".join(columns),
        "rows_checked": total,
        "rows_failed": dup_count,
        "pass_rate": round(pass_rate, 4),
        "threshold": threshold,
        "passed": passed,
        "details": {"duplicate_count": dup_count},
    }


def check_referential_integrity(
    df: pd.DataFrame,
    column: str,
    valid_set: set,
    threshold: float = 0.99,
) -> dict:
    """Expect column values to exist in a reference set (like a FK check)."""
    total = len(df)
    mask = df[column].isin(valid_set)
    valid_count = mask.sum()
    pass_rate = valid_count / total if total > 0 else 0.0
    passed = pass_rate >= threshold

    invalid_values = df.loc[~mask, column].unique()[:20].tolist()

    return {
        "check_name": f"referential_integrity::{column}",
        "check_type": "consistency",
        "column_name": column,
        "rows_checked": total,
        "rows_failed": total - int(valid_count),
        "pass_rate": round(pass_rate, 4),
        "threshold": threshold,
        "passed": passed,
        "details": {"invalid_values_sample": invalid_values},
    }


def check_no_future_dates(
    df: pd.DataFrame, date_column: str = "flight_date", threshold: float = 1.0
) -> dict:
    """Expect all flight dates to be in the past (no future flights in historical data)."""
    import pandas as pd
    today = pd.Timestamp.today().normalize()
    dates = pd.to_datetime(df[date_column], errors="coerce")
    total = dates.notna().sum()
    valid = (dates <= today).sum()
    pass_rate = valid / total if total > 0 else 0.0
    passed = pass_rate >= threshold

    return {
        "check_name": f"no_future_dates::{date_column}",
        "check_type": "validity",
        "column_name": date_column,
        "rows_checked": int(total),
        "rows_failed": int(total - valid),
        "pass_rate": round(pass_rate, 4),
        "threshold": threshold,
        "passed": passed,
        "details": {
            "min_date": str(dates.min().date()) if not dates.empty else None,
            "max_date": str(dates.max().date()) if not dates.empty else None,
        },
    }


def check_delay_consistency(df: pd.DataFrame, threshold: float = 0.95) -> dict:
    """
    Business rule: sum of delay components should be close to total arrival delay.
    BTS note: this isn't always exact (they acknowledge rounding), so we use 95%.
    """
    delay_cols = [
        "carrier_delay_min", "weather_delay_min",
        "nas_delay_min", "security_delay_min", "late_aircraft_delay_min",
    ]

    available = [c for c in delay_cols if c in df.columns]
    if len(available) < 3 or "arrival_delay_min" not in df.columns:
        return {
            "check_name": "delay_consistency",
            "check_type": "consistency",
            "column_name": "delay_components",
            "rows_checked": 0,
            "rows_failed": 0,
            "pass_rate": 1.0,
            "threshold": threshold,
            "passed": True,
            "details": {"note": "Insufficient columns for check"},
        }

    # Only check rows where all components are available
    mask = df[available].notna().all(axis=1) & df["arrival_delay_min"].notna()
    subset = df[mask].copy()

    if len(subset) == 0:
        return {
            "check_name": "delay_consistency",
            "check_type": "consistency",
            "column_name": "delay_components",
            "rows_checked": 0,
            "rows_failed": 0,
            "pass_rate": 1.0,
            "threshold": threshold,
            "passed": True,
            "details": {"note": "No rows with complete delay breakdown"},
        }

    subset["component_sum"] = subset[available].sum(axis=1)
    subset["difference"] = (subset["component_sum"] - subset["arrival_delay_min"]).abs()

    # Allow 5-minute tolerance
    consistent = (subset["difference"] <= 5).sum()
    total = len(subset)
    pass_rate = consistent / total
    passed = pass_rate >= threshold

    return {
        "check_name": "delay_consistency",
        "check_type": "consistency",
        "column_name": "delay_components",
        "rows_checked": total,
        "rows_failed": total - int(consistent),
        "pass_rate": round(pass_rate, 4),
        "threshold": threshold,
        "passed": passed,
        "details": {
            "mean_difference_min": round(float(subset["difference"].mean()), 2),
            "max_difference_min": round(float(subset["difference"].max()), 2),
        },
    }


# ─────────────────────────────────────────
# Main quality check runner
# ─────────────────────────────────────────

VALID_CANCELLATION_CODES = {"A", "B", "C", "D", None}
VALID_DAY_OF_WEEK = {1, 2, 3, 4, 5, 6, 7}

KNOWN_MAJOR_CARRIERS = {
    "AA", "DL", "UA", "WN", "AS", "B6", "F9", "NK",
    "G4", "SY", "HA", "VX", "OO", "YX", "MQ",
}


def run_all_checks(df: pd.DataFrame) -> tuple[list[dict], bool]:
    """
    Run the full quality check suite against a DataFrame.

    Returns:
        (results, all_passed): list of check results and overall pass flag
    """
    logger.info(f"Running data quality checks on {len(df):,} rows...")
    results = []

    # ── Completeness checks ──────────────────────────────
    results.append(check_not_null(df, "flight_date", threshold=1.0))
    results.append(check_not_null(df, "carrier_code", threshold=1.0))
    results.append(check_not_null(df, "origin_airport", threshold=1.0))
    results.append(check_not_null(df, "dest_airport", threshold=1.0))
    results.append(check_not_null(df, "distance_miles", threshold=0.99))

    # Arrival delay can be null for cancelled/diverted flights
    results.append(check_not_null(df, "arrival_delay_min", threshold=0.80))

    # ── Validity checks ──────────────────────────────────
    results.append(check_value_range(df, "distance_miles", 1, 6000, threshold=0.99))
    results.append(check_value_range(df, "departure_delay_min", -120, 1500, threshold=0.99))
    results.append(check_value_range(df, "arrival_delay_min", -120, 1500, threshold=0.99))
    results.append(check_no_future_dates(df, "flight_date", threshold=1.0))

    # ── Uniqueness checks ────────────────────────────────
    key_cols = ["flight_date", "carrier_code", "flight_number", "origin_airport", "dest_airport"]
    existing_keys = [c for c in key_cols if c in df.columns]
    if len(existing_keys) >= 4:
        results.append(check_unique(df, existing_keys, threshold=0.999))

    # ── Consistency checks ───────────────────────────────
    results.append(check_delay_consistency(df, threshold=0.90))

    # ── Summary ─────────────────────────────────────────
    failed = [r for r in results if not r["passed"]]
    all_passed = len(failed) == 0

    logger.info(
        f"Quality checks: {len(results) - len(failed)}/{len(results)} passed"
        + (f" — FAILED: {[r['check_name'] for r in failed]}" if failed else "")
    )

    if not all_passed:
        logger.warning(f"{len(failed)} quality check(s) failed!")

    return results, all_passed


def print_quality_report(results: list[dict]) -> None:
    """Print a human-readable quality report to the console."""
    print("\n" + "=" * 60)
    print("DATA QUALITY REPORT")
    print("=" * 60)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"[{status}] {r['check_name']:<45} "
            f"{r['pass_rate']*100:.1f}% "
            f"(threshold: {r['threshold']*100:.0f}%)"
        )
    print("=" * 60)
    passed = sum(1 for r in results if r["passed"])
    print(f"Result: {passed}/{len(results)} checks passed\n")
