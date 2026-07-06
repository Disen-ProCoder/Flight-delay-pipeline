"""
Predict delay risk from a saved flight delay model.

Usage:
    python src/model/predict_delay.py --carrier AA --origin JFK --dest LAX --month 7 --day-of-week 5 --dep-hour 18 --arr-hour 21 --distance 2475
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model.train_delay_model import FEATURE_COLUMNS


@click.command()
@click.option("--model-path", type=click.Path(path_type=Path), default=PROJECT_ROOT / "models" / "flight_delay_model.pkl")
@click.option("--carrier", required=True, help="Carrier code, e.g. AA")
@click.option("--origin", required=True, help="Origin airport, e.g. JFK")
@click.option("--dest", required=True, help="Destination airport, e.g. LAX")
@click.option("--month", required=True, type=int)
@click.option("--day-of-week", required=True, type=int, help="BTS day of week: 1=Monday, 7=Sunday")
@click.option("--dep-hour", required=True, type=int, help="Scheduled departure hour, 0-23")
@click.option("--arr-hour", required=True, type=int, help="Scheduled arrival hour, 0-23")
@click.option("--distance", required=True, type=float, help="Distance in miles")
def main(
    model_path: Path,
    carrier: str,
    origin: str,
    dest: str,
    month: int,
    day_of_week: int,
    dep_hour: int,
    arr_hour: int,
    distance: float,
) -> None:
    try:
        import joblib
    except ModuleNotFoundError as exc:
        raise click.ClickException("Missing ML dependency. Run: pip install -r requirements.txt") from exc

    if not model_path.exists():
        raise click.ClickException(f"Model not found: {model_path}")

    model = joblib.load(model_path)
    row = pd.DataFrame(
        [
            {
                "carrier_code": carrier.upper(),
                "origin_airport": origin.upper(),
                "dest_airport": dest.upper(),
                "month": month,
                "day_of_week": day_of_week,
                "scheduled_departure_hour": dep_hour,
                "scheduled_arrival_hour": arr_hour,
                "distance_miles": distance,
            }
        ],
        columns=FEATURE_COLUMNS,
    )

    delay_probability = model.predict_proba(row)[0, 1]
    prediction = model.predict(row)[0]

    click.echo(f"Delay prediction: {'Delayed' if prediction else 'Not delayed'}")
    click.echo(f"Delay risk: {delay_probability:.1%}")


if __name__ == "__main__":
    main()
