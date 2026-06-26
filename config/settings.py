"""
config/settings.py
Central configuration loader. Import this everywhere instead of
reading os.environ directly — keeps credential handling in one place.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the config/ directory
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "config" / ".env")


class DatabaseConfig:
    HOST = os.getenv("DB_HOST", "localhost")
    PORT = int(os.getenv("DB_PORT", 5432))
    NAME = os.getenv("DB_NAME", "flight_warehouse")
    USER = os.getenv("DB_USER", "pipeline_user")
    PASSWORD = os.getenv("DB_PASSWORD", "")

    @classmethod
    def connection_string(cls) -> str:
        return (
            f"postgresql://{cls.USER}:{cls.PASSWORD}"
            f"@{cls.HOST}:{cls.PORT}/{cls.NAME}"
        )


class PathConfig:
    BASE_DIR = BASE_DIR
    RAW_DATA_DIR = BASE_DIR / os.getenv("BTS_DATA_DIR", "data/raw/bts")
    PROCESSED_DATA_DIR = BASE_DIR / os.getenv("PROCESSED_DATA_DIR", "data/processed")
    LOG_DIR = BASE_DIR / os.getenv("LOG_DIR", "logs")
    SQL_DIR = BASE_DIR / "sql"

    @classmethod
    def ensure_dirs(cls):
        """Create all required directories if they don't exist."""
        for d in [cls.RAW_DATA_DIR, cls.PROCESSED_DATA_DIR, cls.LOG_DIR]:
            d.mkdir(parents=True, exist_ok=True)


class APIConfig:
    AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_API_KEY", "")
    AVIATIONSTACK_BASE_URL = "http://api.aviationstack.com/v1"


class PipelineConfig:
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # BTS column mappings (the raw CSV has verbose column names)
    BTS_COLUMN_MAP = {
        "FL_DATE": "flight_date",
        "OP_UNIQUE_CARRIER": "carrier_code",
        "OP_CARRIER_FL_NUM": "flight_number",
        "ORIGIN": "origin_airport",
        "DEST": "dest_airport",
        "CRS_DEP_TIME": "scheduled_departure",
        "DEP_TIME": "actual_departure",
        "DEP_DELAY": "departure_delay_min",
        "CRS_ARR_TIME": "scheduled_arrival",
        "ARR_TIME": "actual_arrival",
        "ARR_DELAY": "arrival_delay_min",
        "CANCELLED": "is_cancelled",
        "CANCELLATION_CODE": "cancellation_code",
        "DIVERTED": "is_diverted",
        "CRS_ELAPSED_TIME": "scheduled_duration_min",
        "ACTUAL_ELAPSED_TIME": "actual_duration_min",
        "AIR_TIME": "air_time_min",
        "DISTANCE": "distance_miles",
        "CARRIER_DELAY": "carrier_delay_min",
        "WEATHER_DELAY": "weather_delay_min",
        "NAS_DELAY": "nas_delay_min",
        "SECURITY_DELAY": "security_delay_min",
        "LATE_AIRCRAFT_DELAY": "late_aircraft_delay_min",
        "YEAR": "year",
        "MONTH": "month",
        "DAY_OF_MONTH": "day_of_month",
        "DAY_OF_WEEK": "day_of_week",
    }

    # Delay thresholds (FAA definition: delayed = 15+ minutes)
    DELAY_THRESHOLD_MIN = 15

    # Batch size for database inserts
    DB_BATCH_SIZE = 10_000
