"""
tests/test_transform.py

Unit tests for the transformation pipeline.
Run with: pytest tests/ -v --cov=src

These tests use synthetic data — no database or BTS download needed.
They verify the business logic of our transformation code.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime

# Adjust path if running from project root
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.transform.clean_flights import (
    rename_columns,
    cast_data_types,
    derive_columns,
    remove_duplicates,
    filter_valid_airports,
    handle_nulls,
)
from src.quality.data_quality_checks import (
    check_not_null,
    check_value_range,
    check_unique,
    check_no_future_dates,
)


# ─────────────────────────────────────────
# Fixtures — reusable sample DataFrames
# ─────────────────────────────────────────

@pytest.fixture
def sample_bts_raw():
    """Raw BTS-style DataFrame using 2023 column names (before any transformations)."""
    return pd.DataFrame({
        "FlightDate":                    ["2023-01-15", "2023-01-15", "2023-01-16"],
        "IATA_CODE_Reporting_Airline":   ["AA",          "DL",         "UA"],
        "Flight_Number_Reporting_Airline":["100",        "200",        "300"],
        "Origin":                        ["JFK",         "LAX",        "ORD"],
        "Dest":                          ["LAX",         "JFK",        "SFO"],
        "CRSDepTime":                    ["0800",        "1200",       "1600"],
        "DepTime":                       ["0815",        "1155",       "1630"],
        "DepDelay":                      ["15.0",        "-5.0",       "30.0"],
        "CRSArrTime":                    ["1100",        "2000",       "1900"],
        "ArrTime":                       ["1120",        "1950",       "1945"],
        "ArrDelay":                      ["20.0",        "-10.0",      "45.0"],
        "Cancelled":                     ["0.0",         "0.0",        "0.0"],
        "CancellationCode":              [None,          None,         None],
        "Diverted":                      ["0.0",         "0.0",        "0.0"],
        "CRSElapsedTime":                ["180.0",       "300.0",      "180.0"],
        "ActualElapsedTime":             ["185.0",       "295.0",      "195.0"],
        "AirTime":                       ["160.0",       "275.0",      "170.0"],
        "Distance":                      ["2475.0",      "2475.0",     "1846.0"],
        "CarrierDelay":                  [None,          None,         "45.0"],
        "WeatherDelay":                  [None,          None,         "0.0"],
        "NASDelay":                      [None,          None,         "0.0"],
        "SecurityDelay":                 [None,          None,         "0.0"],
        "LateAircraftDelay":             [None,          None,         "0.0"],
        "Year":                          ["2023",        "2023",       "2023"],
        "Month":                         ["1",           "1",          "1"],
        "DayofMonth":                    ["15",          "15",         "16"],
        "DayOfWeek":                     ["7",           "7",          "1"],
    })


@pytest.fixture
def sample_clean_df():
    """Already-renamed and cast DataFrame (after transform steps 1-4)."""
    return pd.DataFrame({
        "flight_date":          pd.to_datetime(["2023-01-15", "2023-01-15", "2023-01-16"]),
        "carrier_code":         ["AA",  "DL",  "UA"],
        "flight_number":        ["100", "200", "300"],
        "origin_airport":       ["JFK", "LAX", "ORD"],
        "dest_airport":         ["LAX", "JFK", "SFO"],
        "departure_delay_min":  [15.0,  -5.0,  30.0],
        "arrival_delay_min":    [20.0,  -10.0, 45.0],
        "is_cancelled":         [False, False, False],
        "is_diverted":          [False, False, False],
        "distance_miles":       [2475.0, 2475.0, 1846.0],
        "year":                 pd.array([2023, 2023, 2023], dtype="Int16"),
        "month":                pd.array([1, 1, 1], dtype="Int16"),
    })


# ─────────────────────────────────────────
# Transform tests
# ─────────────────────────────────────────

class TestRenameColumns:
    def test_renames_bts_columns(self, sample_bts_raw):
        result = rename_columns(sample_bts_raw)
        assert "flight_date" in result.columns
        assert "carrier_code" in result.columns
        assert "origin_airport" in result.columns
        assert "FL_DATE" not in result.columns

    def test_preserves_row_count(self, sample_bts_raw):
        result = rename_columns(sample_bts_raw)
        assert len(result) == len(sample_bts_raw)


class TestCastDataTypes:
    def test_flight_date_is_datetime(self, sample_bts_raw):
        df = rename_columns(sample_bts_raw)
        df = cast_data_types(df)
        assert pd.api.types.is_datetime64_any_dtype(df["flight_date"])

    def test_delay_columns_are_numeric(self, sample_bts_raw):
        df = rename_columns(sample_bts_raw)
        df = cast_data_types(df)
        assert pd.api.types.is_float_dtype(df["departure_delay_min"])
        assert pd.api.types.is_float_dtype(df["arrival_delay_min"])

    def test_is_cancelled_is_bool(self, sample_bts_raw):
        df = rename_columns(sample_bts_raw)
        df = cast_data_types(df)
        assert pd.api.types.is_bool_dtype(df["is_cancelled"])

    def test_invalid_dates_become_nat(self):
        df = pd.DataFrame({
            "FlightDate": ["2023-01-15", "not-a-date", "2023-13-01"],
        })
        df = rename_columns(df)
        df = cast_data_types(df)
        assert df["flight_date"].isna().sum() == 2


class TestDeriveColumns:
    def test_is_delayed_true_when_arrival_delay_gte_15(self, sample_clean_df):
        df = derive_columns(sample_clean_df)
        # AA: 20 min late → delayed
        assert df.loc[df["carrier_code"] == "AA", "is_delayed"].values[0] == True

    def test_is_delayed_false_when_early(self, sample_clean_df):
        df = derive_columns(sample_clean_df)
        # DL: -10 min (early) → not delayed
        assert df.loc[df["carrier_code"] == "DL", "is_delayed"].values[0] == False

    def test_route_format(self, sample_clean_df):
        df = derive_columns(sample_clean_df)
        assert "JFK-LAX" in df["route"].values

    def test_delay_category_on_time(self, sample_clean_df):
        df = derive_columns(sample_clean_df)
        # DL: -10 min → 'Early'
        assert df.loc[df["carrier_code"] == "DL", "delay_category"].values[0] == "Early"

    def test_delay_category_minor_delay(self, sample_clean_df):
        df = derive_columns(sample_clean_df)
        # AA: 20 min → 'Minor Delay'
        assert df.loc[df["carrier_code"] == "AA", "delay_category"].values[0] == "Minor Delay"

    def test_delay_category_major_delay(self, sample_clean_df):
        df = derive_columns(sample_clean_df)
        # UA: 45 min → 'Minor Delay' (45 < 60)
        assert df.loc[df["carrier_code"] == "UA", "delay_category"].values[0] == "Minor Delay"

    def test_date_id_format(self, sample_clean_df):
        df = derive_columns(sample_clean_df)
        assert df["date_id"].iloc[0] == 20230115


class TestRemoveDuplicates:
    def test_removes_exact_duplicates(self, sample_clean_df):
        # Add a duplicate row
        doubled = pd.concat([sample_clean_df, sample_clean_df.iloc[[0]]], ignore_index=True)
        result = remove_duplicates(doubled)
        assert len(result) == len(sample_clean_df)

    def test_keeps_all_unique_rows(self, sample_clean_df):
        result = remove_duplicates(sample_clean_df)
        assert len(result) == len(sample_clean_df)


class TestFilterValidAirports:
    def test_removes_invalid_codes(self):
        df = pd.DataFrame({
            "origin_airport": ["JFK", "LAX", "123", ""],
            "dest_airport":   ["LAX", "JFK", "SFO", "ORD"],
        })
        result = filter_valid_airports(df)
        assert len(result) == 2

    def test_keeps_valid_codes(self, sample_clean_df):
        result = filter_valid_airports(sample_clean_df)
        assert len(result) == len(sample_clean_df)


# ─────────────────────────────────────────
# Data quality check tests
# ─────────────────────────────────────────

class TestQualityChecks:
    def test_not_null_passes_when_all_present(self, sample_clean_df):
        result = check_not_null(sample_clean_df, "carrier_code", threshold=1.0)
        assert result["passed"] == True
        assert result["rows_failed"] == 0

    def test_not_null_fails_below_threshold(self):
        df = pd.DataFrame({"col": [1, None, None, None]})
        result = check_not_null(df, "col", threshold=0.99)
        assert result["passed"] == False
        assert result["pass_rate"] == 0.25

    def test_value_range_passes_within_bounds(self, sample_clean_df):
        result = check_value_range(
            sample_clean_df, "distance_miles", min_val=0, max_val=10000
        )
        assert result["passed"] == True

    def test_value_range_fails_with_outliers(self):
        df = pd.DataFrame({"distance": [100, 200, 99999, 300]})
        result = check_value_range(df, "distance", min_val=0, max_val=6000, threshold=0.99)
        assert result["passed"] == False

    def test_unique_passes_on_unique_data(self, sample_clean_df):
        result = check_unique(
            sample_clean_df,
            ["carrier_code", "origin_airport", "dest_airport"],
        )
        assert result["passed"] == True

    def test_no_future_dates_passes_on_historical(self, sample_clean_df):
        result = check_no_future_dates(sample_clean_df, "flight_date")
        assert result["passed"] == True

    def test_no_future_dates_fails_on_future(self):
        df = pd.DataFrame({"flight_date": pd.to_datetime(["2099-01-01"])})
        result = check_no_future_dates(df, "flight_date")
        assert result["passed"] == False
