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
        "FlightDate": "flight_date",
        "IATA_CODE_Reporting_Airline": "carrier_code",
        "Flight_Number_Reporting_Airline": "flight_number",
        "Origin": "origin_airport",
        "Dest": "dest_airport",
        "CRSDepTime": "scheduled_departure",
        "DepTime": "actual_departure",
        "DepDelay": "departure_delay_min",
        "CRSArrTime": "scheduled_arrival",
        "ArrTime": "actual_arrival",
        "ArrDelay": "arrival_delay_min",
        "Cancelled": "is_cancelled",
        "CancellationCode": "cancellation_code",
        "Diverted": "is_diverted",
        "CRSElapsedTime": "scheduled_duration_min",
        "ActualElapsedTime": "actual_duration_min",
        "AirTime": "air_time_min",
        "Distance": "distance_miles",
        "CarrierDelay": "carrier_delay_min",
        "WeatherDelay": "weather_delay_min",
        "NASDelay": "nas_delay_min",
        "SecurityDelay": "security_delay_min",
        "LateAircraftDelay": "late_aircraft_delay_min",
        "Year": "year",
        "Month": "month",
        "DayofMonth": "day_of_month",
        "DayOfWeek": "day_of_week",
    }

    # Delay thresholds (FAA definition: delayed = 15+ minutes)
    DELAY_THRESHOLD_MIN = 15

    # Batch size for database inserts
    DB_BATCH_SIZE = 10_000
