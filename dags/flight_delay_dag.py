"""
dags/flight_delay_dag.py

Apache Airflow DAG for the flight delay ETL pipeline.
Runs monthly on the 5th of each month to process the prior month's data
(BTS publishes data ~30 days after month end).

Setup:
  1. Install Airflow: pip install apache-airflow==2.8.0
  2. Copy this file to $AIRFLOW_HOME/dags/
  3. Set environment variables in Airflow UI (Admin > Variables or Connections)
  4. Enable the DAG in Airflow UI

Airflow concepts used:
  - DAG: the workflow definition
  - Task: one step in the workflow (PythonOperator)
  - XCom: passing data between tasks
  - TaskGroup: logical grouping of related tasks
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add project root to Python path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.task_group import TaskGroup
from airflow.models import Variable

# ─────────────────────────────────────────
# Default arguments — applied to all tasks
# ─────────────────────────────────────────

default_args = {
    "owner": "data_engineering",
    "depends_on_past": False,
    "start_date": datetime(2023, 1, 1),
    "email_on_failure": False,       # Set to True + add email in production
    "email_on_retry": False,
    "retries": 2,                    # Retry failed tasks twice
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=2),
}


# ─────────────────────────────────────────
# Task functions
# ─────────────────────────────────────────

def _get_target_year_month(**context) -> tuple[int, int]:
    """
    Determine which year/month to process.
    By default, process the month 35 days before the DAG run date
    (BTS publishes ~30 days after month end).
    """
    # Airflow passes execution_date via context
    execution_date = context["execution_date"]
    target_date = execution_date - timedelta(days=35)
    return target_date.year, target_date.month


def task_check_already_processed(**context) -> str:
    """
    Branch: check if this month's data is already in the warehouse.
    Returns task_id of the next task to run.
    """
    from src.load.load_to_postgres import get_engine, check_for_duplicates

    year, month = _get_target_year_month(**context)
    engine = get_engine()
    count = check_for_duplicates(engine, year, month)

    if count > 0:
        from loguru import logger
        logger.info(f"Data already loaded for {year}-{month:02d} ({count:,} rows). Skipping.")
        return "already_processed"

    return "extract.download_bts_data"


def task_download_bts(**context) -> str:
    """Download BTS CSV for the target month. Returns path to CSV."""
    from src.extract.download_bts import download_month
    from loguru import logger

    year, month = _get_target_year_month(**context)
    logger.info(f"Downloading BTS data: {year}-{month:02d}")

    csv_path = download_month(year, month, force=False)
    if not csv_path:
        raise RuntimeError(f"Failed to download BTS data for {year}-{month:02d}")

    # Push to XCom so downstream tasks can access the path
    context["task_instance"].xcom_push(key="csv_path", value=str(csv_path))
    context["task_instance"].xcom_push(key="year", value=year)
    context["task_instance"].xcom_push(key="month", value=month)

    return str(csv_path)


def task_transform(**context) -> dict:
    """Transform raw CSV into clean DataFrame and save to parquet."""
    from src.transform.clean_flights import transform_flights
    from loguru import logger
    import pandas as pd

    csv_path = context["task_instance"].xcom_pull(
        task_ids="extract.download_bts_data", key="csv_path"
    )
    year = context["task_instance"].xcom_pull(task_ids="extract.download_bts_data", key="year")
    month = context["task_instance"].xcom_pull(task_ids="extract.download_bts_data", key="month")

    df, stats = transform_flights(Path(csv_path))

    # Save transformed data as parquet (faster to reload than CSV)
    from config.settings import PathConfig
    parquet_dir = PathConfig.PROCESSED_DATA_DIR / str(year)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = parquet_dir / f"flights_{year}_{month:02d}.parquet"
    df.to_parquet(parquet_path, index=False, compression="snappy")

    logger.info(f"Saved transformed data: {parquet_path}")
    context["task_instance"].xcom_push(key="parquet_path", value=str(parquet_path))
    context["task_instance"].xcom_push(key="transform_stats", value=stats)

    return stats


def task_run_quality_checks(**context) -> dict:
    """Run data quality checks. Fails task if checks don't pass."""
    from src.quality.data_quality_checks import run_all_checks, print_quality_report
    from loguru import logger
    import pandas as pd

    parquet_path = context["task_instance"].xcom_pull(
        task_ids="transform.clean_data", key="parquet_path"
    )
    df = pd.read_parquet(parquet_path)
    quality_results, all_passed = run_all_checks(df)
    print_quality_report(quality_results)

    if not all_passed:
        failed_checks = [r["check_name"] for r in quality_results if not r["passed"]]
        raise ValueError(f"Data quality checks failed: {failed_checks}")

    context["task_instance"].xcom_push(key="quality_results", value=quality_results)
    logger.success("All data quality checks passed")
    return {"all_passed": True, "check_count": len(quality_results)}


def task_load_to_warehouse(**context) -> dict:
    """Load the transformed data into PostgreSQL warehouse."""
    from src.load.load_to_postgres import load_pipeline
    from loguru import logger
    import pandas as pd

    parquet_path = context["task_instance"].xcom_pull(
        task_ids="transform.clean_data", key="parquet_path"
    )
    year = context["task_instance"].xcom_pull(task_ids="extract.download_bts_data", key="year")
    month = context["task_instance"].xcom_pull(task_ids="extract.download_bts_data", key="month")

    df = pd.read_parquet(parquet_path)
    load_stats = load_pipeline(
        df=df,
        source_file=parquet_path,
        year=year,
        month=month,
        overwrite=False,
    )

    logger.success(f"Loaded {load_stats.get('rows_loaded', 0):,} rows")
    return load_stats


def task_refresh_views(**context) -> None:
    """Refresh materialised views after new data is loaded."""
    from src.load.load_to_postgres import get_engine
    from sqlalchemy import text

    engine = get_engine()
    views_to_refresh = [
        "warehouse.mv_carrier_performance",
        "warehouse.mv_route_analysis",
        "warehouse.mv_monthly_summary",
    ]

    with engine.connect() as conn:
        with conn.begin():
            for view in views_to_refresh:
                try:
                    conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
                except Exception as e:
                    # Views might not exist yet on first run — log but don't fail
                    print(f"Could not refresh {view}: {e}")


# ─────────────────────────────────────────
# DAG definition
# ─────────────────────────────────────────

with DAG(
    dag_id="flight_delay_pipeline",
    description="Monthly ETL pipeline for BTS flight delay data",
    default_args=default_args,
    schedule_interval="0 6 5 * *",  # 6am UTC on the 5th of every month
    catchup=False,                   # Don't backfill missed runs automatically
    max_active_runs=1,               # Only one run at a time
    tags=["flight-delay", "etl", "bts"],
    doc_md="""
    ## Flight Delay Pipeline

    Monthly ETL pipeline that:
    1. Downloads BTS On-Time Performance data
    2. Transforms and cleans the data
    3. Runs data quality checks
    4. Loads to PostgreSQL warehouse

    **Schedule**: 5th of each month at 6am UTC
    **Data lag**: Processes data from ~35 days prior (BTS publication delay)
    """,
) as dag:

    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")
    already_processed = EmptyOperator(task_id="already_processed")

    # Branch: skip if already loaded
    check_processed = BranchPythonOperator(
        task_id="check_already_processed",
        python_callable=task_check_already_processed,
    )

    with TaskGroup("extract") as extract_group:
        download_bts = PythonOperator(
            task_id="download_bts_data",
            python_callable=task_download_bts,
        )

    with TaskGroup("transform") as transform_group:
        clean_data = PythonOperator(
            task_id="clean_data",
            python_callable=task_transform,
        )

    with TaskGroup("quality") as quality_group:
        quality_checks = PythonOperator(
            task_id="run_quality_checks",
            python_callable=task_run_quality_checks,
        )

    with TaskGroup("load") as load_group:
        load_warehouse = PythonOperator(
            task_id="load_to_warehouse",
            python_callable=task_load_to_warehouse,
        )
        refresh_views = PythonOperator(
            task_id="refresh_materialized_views",
            python_callable=task_refresh_views,
        )
        load_warehouse >> refresh_views

    # ── Task dependencies ─────────────────────────────────
    start >> check_processed
    check_processed >> [download_bts, already_processed]
    download_bts >> clean_data
    clean_data >> quality_checks
    quality_checks >> load_warehouse
    already_processed >> end
    refresh_views >> end
