"""
Train a baseline flight delay prediction model.

The model predicts whether a flight will arrive 15+ minutes late using only
features that are known before departure. It intentionally avoids leakage
columns such as actual delay minutes and delay categories.

Usage:
    python src/model/train_delay_model.py --year 2023 --month 1
    python src/model/train_delay_model.py --input data/raw/bts/2023/flights_2023_01.csv
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import click
import pandas as pd
from loguru import logger

# Allow running this file directly from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import PathConfig, PipelineConfig
from src.transform.clean_flights import (
    cast_data_types,
    derive_columns,
    filter_valid_airports,
    rename_columns,
)


FEATURE_COLUMNS = [
    "carrier_code",
    "origin_airport",
    "dest_airport",
    "month",
    "day_of_week",
    "scheduled_departure_hour",
    "scheduled_arrival_hour",
    "distance_miles",
]

TARGET_COLUMN = "is_delayed"

RAW_COLUMNS = [
    "FlightDate",
    "IATA_CODE_Reporting_Airline",
    "Origin",
    "Dest",
    "CRSDepTime",
    "CRSArrTime",
    "ArrDelay",
    "Cancelled",
    "Diverted",
    "Distance",
    "Year",
    "Month",
    "DayofMonth",
    "DayOfWeek",
]


def _time_to_hour(series: pd.Series) -> pd.Series:
    """Convert BTS HHMM time values into hour-of-day integers."""
    numeric = pd.to_numeric(series, errors="coerce")
    hour = (numeric // 100).where(numeric.between(0, 2359))
    return hour.clip(lower=0, upper=23)


def load_training_source(input_path: Path, max_rows: int | None = None) -> pd.DataFrame:
    """Load raw CSV or processed parquet data for model training."""
    if input_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(input_path)
        if max_rows:
            df = df.head(max_rows)
        return df

    available_columns = pd.read_csv(input_path, nrows=0).columns.tolist()
    usecols = [col for col in RAW_COLUMNS if col in available_columns]
    if not usecols:
        raise ValueError(f"No expected BTS columns found in {input_path}")

    return pd.read_csv(
        input_path,
        usecols=usecols,
        nrows=max_rows,
        low_memory=False,
        na_values=["", " ", "NA", "N/A", "."],
        encoding="utf-8",
    )


def build_training_frame(source_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert source flight records into a clean ML training frame.

    Only pre-flight features are retained. Actual arrival delay is used only to
    create the target, then excluded from the feature matrix.
    """
    df = source_df.copy()
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]

    if "FlightDate" in df.columns:
        df = rename_columns(df)

    df = cast_data_types(df)
    df = filter_valid_airports(df)

    required = [
        "arrival_delay_min",
        "is_cancelled",
        "is_diverted",
        "scheduled_departure",
        "scheduled_arrival",
        "distance_miles",
        "carrier_code",
        "origin_airport",
        "dest_airport",
        "month",
        "day_of_week",
    ]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required training columns: {missing}")

    df = df[(df["is_cancelled"] == False) & (df["is_diverted"] == False)].copy()
    df = derive_columns(df)
    df["scheduled_departure_hour"] = _time_to_hour(df["scheduled_departure"])
    df["scheduled_arrival_hour"] = _time_to_hour(df["scheduled_arrival"])

    training_df = df[FEATURE_COLUMNS + [TARGET_COLUMN]].copy()
    training_df = training_df.dropna(subset=FEATURE_COLUMNS + [TARGET_COLUMN])
    training_df[TARGET_COLUMN] = training_df[TARGET_COLUMN].astype(int)

    return training_df


def combine_training_frames(paths: Iterable[Path], max_rows_per_file: int | None) -> pd.DataFrame:
    frames = []
    for path in paths:
        logger.info(f"Loading training data: {path}")
        source_df = load_training_source(path, max_rows=max_rows_per_file)
        frame = build_training_frame(source_df)
        logger.info(f"Prepared {len(frame):,} training rows from {path.name}")
        frames.append(frame)

    if not frames:
        raise ValueError("No training files were provided")

    return pd.concat(frames, ignore_index=True)


def train_model(training_df: pd.DataFrame, output_dir: Path, test_size: float, random_state: int) -> dict:
    """Train, evaluate, and save a baseline classifier."""
    try:
        import joblib
        from sklearn.compose import ColumnTransformer
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing ML dependency. Run: pip install -r requirements.txt"
        ) from exc

    X = training_df[FEATURE_COLUMNS]
    y = training_df[TARGET_COLUMN]

    categorical_features = ["carrier_code", "origin_airport", "dest_airport"]
    numeric_features = [
        "month",
        "day_of_week",
        "scheduled_departure_hour",
        "scheduled_arrival_hour",
        "distance_miles",
    ]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
        stratify=y,
    )

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_features,
            ),
            (
                "numeric",
                Pipeline(steps=[("imputer", SimpleImputer(strategy="median"))]),
                numeric_features,
            ),
        ]
    )

    model = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=120,
                    min_samples_leaf=20,
                    class_weight="balanced",
                    n_jobs=-1,
                    random_state=random_state,
                ),
            ),
        ]
    )

    logger.info("Training RandomForestClassifier")
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    probabilities = model.predict_proba(X_test)[:, 1]

    metrics = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "rows_total": int(len(training_df)),
        "rows_train": int(len(X_train)),
        "rows_test": int(len(X_test)),
        "positive_rate": float(y.mean()),
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "confusion_matrix": confusion_matrix(y_test, predictions).tolist(),
        "features": FEATURE_COLUMNS,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "flight_delay_model.pkl"
    metrics_path = output_dir / "flight_delay_model_metrics.json"

    joblib.dump(model, model_path)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    logger.success(f"Saved model: {model_path}")
    logger.success(f"Saved metrics: {metrics_path}")
    logger.info("Classification report:\n" + classification_report(y_test, predictions))

    return metrics


def paths_from_year_month(year: int, month: int | None) -> list[Path]:
    year_dir = PathConfig.RAW_DATA_DIR / str(year)
    if month:
        return [year_dir / f"flights_{year}_{month:02d}.csv"]
    return sorted(year_dir.glob(f"flights_{year}_*.csv"))


@click.command()
@click.option("--input", "input_paths", multiple=True, type=click.Path(path_type=Path))
@click.option("--year", type=int, help="Train from data/raw/bts/<year>/flights_<year>_<month>.csv")
@click.option("--month", type=int, help="Optional month to train on. Omit to use all months for the year.")
@click.option("--max-rows-per-file", type=int, default=None, help="Limit rows per file for a fast first run.")
@click.option("--output-dir", type=click.Path(path_type=Path), default=PROJECT_ROOT / "models")
@click.option("--test-size", type=float, default=0.2)
@click.option("--random-state", type=int, default=42)
def main(
    input_paths: tuple[Path, ...],
    year: int | None,
    month: int | None,
    max_rows_per_file: int | None,
    output_dir: Path,
    test_size: float,
    random_state: int,
) -> None:
    """Train a baseline model that predicts arrival delay risk."""
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}")

    paths = list(input_paths)
    if year:
        paths.extend(paths_from_year_month(year, month))

    missing = [path for path in paths if not path.exists()]
    if missing:
        raise click.ClickException(f"Training file not found: {missing[0]}")

    training_df = combine_training_frames(paths, max_rows_per_file)
    if training_df[TARGET_COLUMN].nunique() < 2:
        raise click.ClickException("Training data must contain both delayed and non-delayed flights.")

    metrics = train_model(training_df, output_dir, test_size, random_state)

    click.echo("\nModel metrics")
    for key in ["rows_total", "positive_rate", "accuracy", "precision", "recall", "f1", "roc_auc"]:
        click.echo(f"{key}: {metrics[key]}")


if __name__ == "__main__":
    main()
