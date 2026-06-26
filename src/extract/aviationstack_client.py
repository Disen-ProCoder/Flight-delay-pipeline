"""
src/extract/aviationstack_client.py

AviationStack API client for airport and airline enrichment data.
Free tier: 100 requests/month — use sparingly.
Sign up: https://aviationstack.com/signup/free

Strategy: use AviationStack ONCE to build the dim_airports and
dim_carriers reference tables, then cache locally. Don't call it
in the nightly pipeline — you'll exhaust the free tier in a week.
"""

import json
import time
from pathlib import Path
from typing import Optional
import requests
from loguru import logger

from config.settings import APIConfig, PathConfig


CACHE_DIR = PathConfig.RAW_DATA_DIR / "aviationstack_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class AviationStackClient:
    """
    Thin wrapper around the AviationStack REST API.
    Results are cached to JSON files to preserve free-tier quota.
    """

    BASE_URL = APIConfig.AVIATIONSTACK_BASE_URL

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or APIConfig.AVIATIONSTACK_KEY
        if not self.api_key:
            raise ValueError(
                "AviationStack API key not set. "
                "Add AVIATIONSTACK_API_KEY to your .env file."
            )
        self.session = requests.Session()
        self.request_count = 0  # Track usage against free tier limit

    def _get(self, endpoint: str, params: dict, cache_key: str) -> dict:
        """
        Make a GET request with local caching.
        Uses cache if file exists — won't burn API quota on re-runs.
        """
        cache_file = CACHE_DIR / f"{cache_key}.json"

        if cache_file.exists():
            logger.debug(f"Cache hit: {cache_key}")
            with open(cache_file) as f:
                return json.load(f)

        params["access_key"] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}"

        logger.info(f"API call #{self.request_count + 1}: {endpoint}")
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise RuntimeError(f"AviationStack error: {data['error']}")

        # Cache the response
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)

        self.request_count += 1
        time.sleep(0.5)  # Rate limiting — be polite
        return data

    def get_airports(self, country_iso2: str = "US", limit: int = 100) -> list[dict]:
        """
        Fetch airport data. Returns list of airport dicts.
        Free tier: limited to first 100 results per call.

        NOTE: For a complete US airport list, use the BTS airport lookup
        table instead (it's free with no limits). Use this for lat/lon enrichment.
        """
        all_airports = []
        offset = 0

        while True:
            cache_key = f"airports_{country_iso2}_{offset}"
            data = self._get(
                "airports",
                {"country_iso2": country_iso2, "limit": limit, "offset": offset},
                cache_key,
            )

            airports = data.get("data", [])
            if not airports:
                break

            all_airports.extend(airports)
            logger.info(f"Fetched {len(all_airports)} airports so far...")

            if len(airports) < limit:
                break
            offset += limit

        logger.success(f"Total airports fetched: {len(all_airports)}")
        return all_airports

    def get_airlines(self, limit: int = 100) -> list[dict]:
        """Fetch airline/carrier reference data."""
        all_airlines = []
        offset = 0

        while True:
            cache_key = f"airlines_{offset}"
            data = self._get(
                "airlines",
                {"limit": limit, "offset": offset},
                cache_key,
            )

            airlines = data.get("data", [])
            if not airlines:
                break

            all_airlines.extend(airlines)
            if len(airlines) < limit:
                break
            offset += limit

        logger.success(f"Total airlines fetched: {len(all_airlines)}")
        return all_airlines

    @staticmethod
    def parse_airport(raw: dict) -> dict:
        """Normalise a raw AviationStack airport record into our schema."""
        return {
            "iata_code": raw.get("iata_code", ""),
            "airport_name": raw.get("airport_name", ""),
            "city": raw.get("city_iata_code", ""),
            "country_code": raw.get("country_iso2", "US"),
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "utc_offset_hrs": raw.get("gmt"),
        }

    @staticmethod
    def parse_airline(raw: dict) -> dict:
        """Normalise a raw AviationStack airline record into our schema."""
        return {
            "carrier_code": raw.get("iata_code", ""),
            "carrier_name": raw.get("airline_name", ""),
            "country_code": raw.get("country_iso2", ""),
            "is_active": raw.get("status", "").lower() == "active",
        }


def fetch_and_save_reference_data():
    """
    One-time setup: fetch airports and airlines from AviationStack
    and save to local JSON for loading into dim tables.
    
    Call this ONCE during initial setup, not in the nightly pipeline.
    """
    client = AviationStackClient()

    # Fetch airports
    airports = client.get_airports(country_iso2="US")
    parsed_airports = [client.parse_airport(a) for a in airports]
    out_file = CACHE_DIR / "airports_reference.json"
    with open(out_file, "w") as f:
        json.dump(parsed_airports, f, indent=2)
    logger.success(f"Saved {len(parsed_airports)} airports to {out_file}")

    # Fetch airlines
    airlines = client.get_airlines()
    parsed_airlines = [client.parse_airline(a) for a in airlines]
    out_file = CACHE_DIR / "airlines_reference.json"
    with open(out_file, "w") as f:
        json.dump(parsed_airlines, f, indent=2)
    logger.success(f"Saved {len(parsed_airlines)} airlines to {out_file}")

    logger.info(f"Total API requests used: {client.request_count}/100 (free tier limit)")


if __name__ == "__main__":
    fetch_and_save_reference_data()
