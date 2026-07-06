import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.model.train_delay_model import FEATURE_COLUMNS, TARGET_COLUMN, build_training_frame


def test_build_training_frame_uses_only_preflight_features():
    raw = pd.DataFrame(
        {
            "FlightDate": ["2023-01-01", "2023-01-02"],
            "IATA_CODE_Reporting_Airline": ["AA", "DL"],
            "Origin": ["JFK", "ATL"],
            "Dest": ["LAX", "ORD"],
            "CRSDepTime": ["0830", "1745"],
            "CRSArrTime": ["1140", "1910"],
            "ArrDelay": ["20", "-5"],
            "Cancelled": ["0", "0"],
            "Diverted": ["0", "0"],
            "Distance": ["2475", "606"],
            "Year": ["2023", "2023"],
            "Month": ["1", "1"],
            "DayofMonth": ["1", "2"],
            "DayOfWeek": ["7", "1"],
        }
    )

    result = build_training_frame(raw)

    assert result.columns.tolist() == FEATURE_COLUMNS + [TARGET_COLUMN]
    assert result["scheduled_departure_hour"].tolist() == [8, 17]
    assert result[TARGET_COLUMN].tolist() == [1, 0]
    assert "arrival_delay_min" not in result.columns


def test_build_training_frame_excludes_cancelled_and_diverted_flights():
    raw = pd.DataFrame(
        {
            "FlightDate": ["2023-01-01", "2023-01-02", "2023-01-03"],
            "IATA_CODE_Reporting_Airline": ["AA", "DL", "UA"],
            "Origin": ["JFK", "ATL", "ORD"],
            "Dest": ["LAX", "ORD", "SFO"],
            "CRSDepTime": ["0830", "1745", "1200"],
            "CRSArrTime": ["1140", "1910", "1500"],
            "ArrDelay": ["20", "30", "45"],
            "Cancelled": ["0", "1", "0"],
            "Diverted": ["0", "0", "1"],
            "Distance": ["2475", "606", "1846"],
            "Year": ["2023", "2023", "2023"],
            "Month": ["1", "1", "1"],
            "DayofMonth": ["1", "2", "3"],
            "DayOfWeek": ["7", "1", "2"],
        }
    )

    result = build_training_frame(raw)

    assert len(result) == 1
    assert result.iloc[0]["carrier_code"] == "AA"
