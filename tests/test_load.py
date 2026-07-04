"""
tests/test_load.py

Unit tests for the PostgreSQL load pipeline.
These tests use monkeypatching so they do not require a live database.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Adjust path if running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import src.load.load_to_postgres as load_mod
from config.settings import PipelineConfig


@pytest.fixture
def sample_fact_df():
    return pd.DataFrame(
        {
            "flight_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "date_id": pd.array([20260101, 20260102, 20260103], dtype="Int32"),
            "carrier_code": ["AA", "AA", "DL"],
            "flight_number": [1, 2, 3],
            "origin_airport": ["JFK", "JFK", "LAX"],
            "dest_airport": ["LAX", "SFO", "JFK"],
            "scheduled_departure": [700, 815, 930],
            "actual_departure": [657, 830, 945],
            "scheduled_arrival": [1021, 1045, 1200],
            "actual_arrival": [1104, 1058, 1215],
            "departure_delay_min": [-3.0, 15.0, 15.0],
            "arrival_delay_min": [43.0, 13.0, 15.0],
            "carrier_delay_min": [0.0, None, 0.0],
            "weather_delay_min": [0.0, None, 0.0],
            "nas_delay_min": [43.0, None, 15.0],
            "security_delay_min": [0.0, None, 0.0],
            "late_aircraft_delay_min": [0.0, None, 0.0],
            "is_cancelled": [False, False, False],
            "cancellation_code": [None, None, None],
            "is_diverted": [False, False, False],
            "scheduled_duration_min": [381.0, 150.0, 160.0],
            "actual_duration_min": [427.0, 143.0, 175.0],
            "air_time_min": [349.0, 120.0, 150.0],
            "distance_miles": [2475.0, 2475.0, 2475.0],
            "is_delayed": [True, False, True],
            "delay_category": ["Minor Delay", "Early", "Minor Delay"],
            "route": ["JFK-LAX", "JFK-SFO", "LAX-JFK"],
            "year": pd.array([2026, 2026, 2026], dtype="Int16"),
            "month": pd.array([1, 1, 1], dtype="Int16"),
            "source_file": ["source.csv", "source.csv", "source.csv"],
            "unexpected_col": ["ignored", "ignored", "ignored"],
        }
    )


def test_load_to_warehouse_batches_and_filters_columns(monkeypatch, sample_fact_df):
    calls = []

    def fake_to_sql(self, name, engine, schema=None, if_exists=None, index=None, method=None, chunksize=None):
        calls.append(
            {
                "name": name,
                "schema": schema,
                "rows": len(self),
                "columns": list(self.columns),
                "engine": engine,
            }
        )

    monkeypatch.setattr(pd.DataFrame, "to_sql", fake_to_sql)
    monkeypatch.setattr(PipelineConfig, "DB_BATCH_SIZE", 2, raising=False)

    rows_loaded = load_mod.load_to_warehouse(sample_fact_df, engine=object())

    assert rows_loaded == 3
    assert len(calls) == 2
    assert calls[0]["schema"] == "warehouse"
    assert calls[0]["name"] == "fact_flights"
    assert calls[0]["rows"] == 2
    assert calls[1]["rows"] == 1
    assert "unexpected_col" not in calls[0]["columns"]


def test_load_pipeline_skips_when_data_exists(monkeypatch, sample_fact_df):
    monkeypatch.setattr(load_mod, "get_engine", lambda echo=False: object())
    monkeypatch.setattr(load_mod, "test_connection", lambda engine: True)
    monkeypatch.setattr(load_mod, "check_for_duplicates", lambda engine, year, month: 12)

    load_called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        load_called["count"] += 1
        raise AssertionError("load_to_warehouse should not be called when data already exists")

    monkeypatch.setattr(load_mod, "upsert_carriers", fail_if_called)
    monkeypatch.setattr(load_mod, "upsert_airports", fail_if_called)
    monkeypatch.setattr(load_mod, "load_to_warehouse", fail_if_called)

    stats = load_mod.load_pipeline(
        df=sample_fact_df,
        source_file="source.csv",
        year=2026,
        month=1,
        overwrite=False,
    )

    assert stats == {"skipped": True, "existing_rows": 12}
    assert load_called["count"] == 0


def test_load_pipeline_runs_full_flow(monkeypatch, sample_fact_df):
    events = []

    monkeypatch.setattr(load_mod, "get_engine", lambda echo=False: object())
    monkeypatch.setattr(load_mod, "test_connection", lambda engine: True)
    monkeypatch.setattr(load_mod, "check_for_duplicates", lambda engine, year, month: 0)
    monkeypatch.setattr(load_mod, "upsert_carriers", lambda df, engine: events.append("carriers") or 3)
    monkeypatch.setattr(load_mod, "upsert_airports", lambda df, engine: events.append("airports") or 4)
    monkeypatch.setattr(load_mod, "load_to_warehouse", lambda df, engine: events.append("fact") or len(df))
    monkeypatch.setattr(load_mod, "log_pipeline_run", lambda engine, run_data: events.append(run_data["status"]) or 17)

    stats = load_mod.load_pipeline(
        df=sample_fact_df,
        source_file="source.csv",
        year=2026,
        month=1,
        overwrite=False,
    )

    assert stats["status"] == "success"
    assert stats["rows_loaded"] == len(sample_fact_df)
    assert stats["year"] == 2026
    assert stats["month"] == 1
    assert events == ["carriers", "airports", "fact", "success"]
